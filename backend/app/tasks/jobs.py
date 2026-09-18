"""定时任务实现。

设计原则：**任务逻辑与调度器解耦** —— 任务函数只依赖 `AsyncSession` 与门店配置，
既可由进程内置调度器（`app/tasks/scheduler.py`）驱动，也可平滑迁到 arq / Celery：
届时只需把 `JOBS` 里的函数注册成 worker 任务，函数体一行都不用改。

并发与幂等：
- 每个任务执行前先对 `task_run` 行加 `FOR UPDATE NOWAIT`，拿不到锁说明**其他实例正在跑同一任务**，
  立即跳过（多实例部署不会重复执行，也不会互相等待）；
- 同一行还持久化了 `last_started_at`，因此**进程重启后不会立刻重跑**，仍按配置间隔触发；
- 站内信类任务按「当天是否已发过」判重，避免重复骚扰宠主。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import MessageType
from app.models import Appointment, Message, Pet, TaskRun, User, VaccineRecord
from app.services import appointment_service, chat_service, message_service, setting_service
from app.utils.datetime_util import now
from app.config import settings
from app.utils.logger import logger

RECORD_TYPE_LABEL = {"vaccine": "疫苗", "deworm_inner": "体内驱虫", "deworm_outer": "体外驱虫"}


async def job_sla_scan(db: AsyncSession) -> dict:
    """店员确认 SLA 巡检：超时未确认升级提醒，按门店配置决定是否自动取消。"""
    return await appointment_service.sla_scan(db)


async def job_vaccine_reminder(db: AsyncSession) -> dict:
    """疫苗 / 驱虫临期提醒：到期前 N 天给宠主发站内信（N 取门店配置 vaccine_remind_days）。"""
    days = await setting_service.get_int(db, "vaccine_remind_days")
    deadline = date.today() + timedelta(days=days)

    rows = (
        await db.execute(
            select(VaccineRecord, Pet)
            .join(Pet, Pet.id == VaccineRecord.pet_id)
            .where(
                Pet.deleted_at.is_(None),
                VaccineRecord.next_date.is_not(None),
                VaccineRecord.next_date <= deadline,
                VaccineRecord.next_date >= date.today(),
            )
        )
    ).all()

    sent = 0
    for record, pet in rows:
        label = RECORD_TYPE_LABEL.get(record.record_type, "疫苗")
        biz_id = record.id
        if await _already_notified_today(db, pet.user_id, MessageType.VACCINE_REMIND.value, biz_id):
            continue
        await message_service.create_message(
            db,
            user_id=pet.user_id,
            title=f"{pet.name} 的{label}快到期啦",
            content=(
                f"{pet.name} 的{label}建议日期是 {record.next_date}（还有 "
                f"{(record.next_date - date.today()).days} 天）。"
                "为保障洗护安全与寄养门槛，建议提前安排接种，到店时出示记录即可。"
            ),
            msg_type=MessageType.VACCINE_REMIND.value,
            biz_id=biz_id,
        )
        sent += 1
    await db.commit()
    return {"checked": len(rows), "sent": sent, "remind_days": days}


async def job_repurchase_reminder(db: AsyncSession) -> dict:
    """复购回访提醒：超过门店配置 churn_days 天未洗护的宠物，给宠主发一条温柔提醒。"""
    churn_days = await setting_service.get_int(db, "churn_days")
    threshold = date.today() - timedelta(days=churn_days)

    # 每只宠物的最后一次完成洗护日期
    last_wash = (
        select(
            Pet.id.label("pet_id"),
            Pet.user_id.label("user_id"),
            Pet.name.label("pet_name"),
            func.max(Appointment.appoint_date).label("last_date"),
        )
        .join(Appointment, Appointment.pet_id == Pet.id)
        .where(
            Pet.deleted_at.is_(None),
            Appointment.status == "completed",
            Appointment.appoint_date.is_not(None),
        )
        .group_by(Pet.id, Pet.user_id, Pet.name)
    ).subquery()

    rows = (
        await db.execute(
            select(last_wash).where(last_wash.c.last_date <= threshold)
        )
    ).all()

    sent = 0
    for row in rows:
        if await _already_notified_today(db, row.user_id, MessageType.REPURCHASE_REMIND.value, row.pet_id):
            continue
        idle = (date.today() - row.last_date).days
        await message_service.create_message(
            db,
            user_id=row.user_id,
            title=f"{row.pet_name} 该洗个香喷喷的澡啦",
            content=(
                f"{row.pet_name} 上次洗护是 {row.last_date}，已经 {idle} 天没有护理了。"
                "毛发打结、耳道与皮肤状况都建议定期检查，需要的话可以直接在预约页挑选时段 🐾"
            ),
            msg_type=MessageType.REPURCHASE_REMIND.value,
            biz_id=row.pet_id,
        )
        sent += 1
    await db.commit()
    return {"checked": len(rows), "sent": sent, "churn_days": churn_days}


async def job_session_cleanup(db: AsyncSession) -> dict:
    """AI 会话清理：按门店配置 session_retention_days 物理删除超期会话。"""
    retention = await setting_service.get_int(db, "session_retention_days")
    removed = await chat_service.purge_expired(db, retention)
    return {"removed": removed, "retention_days": retention}


async def job_lock_cleanup(db: AsyncSession) -> dict:
    """清理历史时段锁行（只保留今天及以后，避免锁表无限增长）。"""
    from sqlalchemy import delete

    from app.models import SlotLock

    result = await db.execute(delete(SlotLock).where(SlotLock.appoint_date < date.today()))
    await db.commit()
    return {"removed": int(result.rowcount or 0)}


async def job_boarding_scan(db: AsyncSession) -> dict:
    """寄养巡检：① 明天离店 → 提醒宠主准备接回并推进「待接回」；② 超过离店日未接回 → 标记超时。

    自动流转需要操作人主体，这里取一位店长作为「系统操作人」并在审计里注明来源为定时任务；
    没有可用店长时只发提醒、不改状态（绝不无主体地改业务数据）。
    """
    from app.constants import (
        BOARDING_STATUS_LABEL,
        BoardingOrderStatus as BS,
    )
    from app.models import BoardingOrder
    from app.services import boarding_service

    today = date.today()
    tomorrow = today + timedelta(days=1)
    operator = (
        await db.execute(select(User).where(User.role == "manager", User.deleted_at.is_(None))
                         .order_by(User.id).limit(1))
    ).scalars().first()

    reminded, advanced, overdue = 0, 0, 0

    # ① 明天离店
    soon = (
        await db.execute(
            select(BoardingOrder).where(
                BoardingOrder.check_out_date == tomorrow,
                BoardingOrder.status.in_([BS.CHECKED_IN.value, BS.WAITING_PICKUP.value]),
            )
        )
    ).scalars().all()
    for order in soon:
        if not await _already_notified_today(db, order.user_id, MessageType.BOARDING_STATUS.value, order.id):
            await message_service.create_message(
                db, user_id=order.user_id,
                title=f"{order.order_no} 明天可以接回啦",
                content=(f"寄养计划明天（{order.check_out_date}）到期，"
                         "请安排时间来接，或直接回复需要延长寄养。"),
                msg_type=MessageType.BOARDING_STATUS.value, biz_id=order.id,
            )
            reminded += 1
        if operator is not None and order.status == BS.CHECKED_IN.value:
            await boarding_service.change_status(
                db, order, BS.WAITING_PICKUP.value, operator,
                reason="离店日前一天由定时任务自动置为待接回",
            )
            advanced += 1
    await db.commit()

    # ② 超期未接回
    over = (
        await db.execute(
            select(BoardingOrder).where(
                BoardingOrder.check_out_date < today,
                BoardingOrder.status.in_([BS.CHECKED_IN.value, BS.WAITING_PICKUP.value]),
            )
        )
    ).scalars().all()
    if operator is not None:
        for order in over:
            await boarding_service.change_status(
                db, order, BS.OVERDUE_UNPICKED.value, operator,
                reason=f"超过离店日期（{order.check_out_date}）未接回，按滞留处理",
            )
            overdue += 1
    return {
        "checked": len(soon), "reminded": reminded, "advanced": advanced,
        "overdue_orders": len(over), "marked_overdue": overdue,
        "status_label_example": BOARDING_STATUS_LABEL[BS.WAITING_PICKUP.value],
    }


async def job_camera_offline(db: AsyncSession) -> dict:
    """摄像头离线巡检：心跳超时判离线并提醒店长（不做自动恢复，避免掩盖真实故障）。"""
    from app.services import camera_service

    return await camera_service.offline_scan(db)


async def _already_notified_today(db: AsyncSession, user_id: int, msg_type: str, biz_id: int) -> bool:
    """同一天、同一业务对象只发一条提醒，避免重复骚扰。"""
    today_start = datetime.combine(date.today(), datetime.min.time())
    exist = await db.scalar(
        select(func.count()).select_from(Message).where(
            Message.user_id == user_id,
            Message.msg_type == msg_type,
            Message.biz_id == biz_id,
            Message.created_at >= today_start,
        )
    )
    return bool(int(exist or 0) > 0)


# ---------------------------------------------------------------- 任务注册表
# interval_env：调度间隔（分钟）取自 .env；生产切 arq 时这里可整体替换为 worker 注册
JOBS: dict[str, dict] = {
    "sla_scan": {
        "label": "店员确认 SLA 巡检",
        "desc": "超时未确认预约升级提醒；按门店配置自动取消并作废风险报告",
        "handler": job_sla_scan,
        "interval_env": "TASK_SLA_INTERVAL_MINUTES",
        "default_interval": 15,
    },
    "vaccine_reminder": {
        "label": "疫苗 / 驱虫临期提醒",
        "desc": "到期前 N 天给宠主发站内信（N 由门店配置 vaccine_remind_days 决定）",
        "handler": job_vaccine_reminder,
        "interval_env": "TASK_REMINDER_INTERVAL_MINUTES",
        "default_interval": 720,
    },
    "repurchase_reminder": {
        "label": "复购回访提醒",
        "desc": "超过 churn_days 未洗护的宠物，给宠主发回访提醒",
        "handler": job_repurchase_reminder,
        "interval_env": "TASK_REMINDER_INTERVAL_MINUTES",
        "default_interval": 720,
    },
    "session_cleanup": {
        "label": "AI 会话清理",
        "desc": "按 session_retention_days 物理删除超期会话",
        "handler": job_session_cleanup,
        "interval_env": "TASK_CLEANUP_INTERVAL_MINUTES",
        "default_interval": 1440,
    },
    "boarding_scan": {
        "label": "寄养巡检",
        "desc": "离店日前一天提醒并置为待接回；超过离店日未接回自动标记超时",
        "handler": job_boarding_scan,
        "interval_env": "TASK_REMINDER_INTERVAL_MINUTES",
        "default_interval": 720,
    },
    "camera_offline": {
        "label": "摄像头离线巡检",
        "desc": "心跳超时的设备判为离线并提醒店长",
        "handler": job_camera_offline,
        "interval_env": "TASK_SLA_INTERVAL_MINUTES",
        "default_interval": 15,
    },
    "lock_cleanup": {
        "label": "时段锁行清理",
        "desc": "删除历史日期的 slot_lock 行",
        "handler": job_lock_cleanup,
        "interval_env": "TASK_CLEANUP_INTERVAL_MINUTES",
        "default_interval": 1440,
    },
}


def interval_minutes(name: str) -> int:
    """读取任务间隔：优先环境变量，缺省用任务自带默认值。


    """
    meta = JOBS[name]
    return int(getattr(settings, meta["interval_env"], meta["default_interval"]) or meta["default_interval"])


async def run_job(db: AsyncSession, name: str, *, trigger: str = "schedule") -> dict:
    """执行一个任务：拿行锁 → 跑任务 → 落执行记录。

    返回 {"name","status","summary","data"}，status ∈ success / failed / skipped。
    """
    if name not in JOBS:
        return {"name": name, "status": "failed", "summary": f"未知任务 {name}"}

    # 多实例互斥：拿不到行锁（其他实例正在跑）立即跳过，不等待
    try:
        row = (
            await db.execute(
                select(TaskRun).where(TaskRun.name == name).with_for_update(nowait=True)
            )
        ).scalars().first()
        skip_reason = None
    except OperationalError:
        await db.rollback()
        logger.info("task_skipped_locked", extra={"extra_fields": {"task": name}})
        return {"name": name, "status": "skipped", "summary": "已有实例在执行（行锁未获取）"}

    if row is None:
        row = TaskRun(name=name, run_count=0)
        db.add(row)
        await db.flush()

    started = now()
    row.last_started_at = started
    row.last_trigger = trigger
    try:
        data = await JOBS[name]["handler"](db)  # handler 内部自行 commit
        row.last_status = "success"
        row.last_summary = _short(data)
        row.run_count = int(row.run_count or 0) + 1
        status = "success"
    except Exception as exc:  # 单个任务失败不影响其他任务，也不影响主进程
        await db.rollback()
        row = (
            await db.execute(select(TaskRun).where(TaskRun.name == name))
        ).scalars().first()
        if row is not None:
            row.last_status = "failed"
            row.last_summary = f"{type(exc).__name__}: {exc}"[:255]
        data = {"error": f"{type(exc).__name__}: {exc}"}
        status = "failed"
        logger.error("task_failed", extra={"extra_fields": {"task": name, "error": str(exc)}})
    finally:
        if row is not None:
            row.last_finished_at = now()
            await db.commit()

    return {"name": name, "status": status, "summary": row.last_summary if row else "",
            "data": data}


def _short(data: dict) -> str:
    import json

    return json.dumps(data, ensure_ascii=False)[:255]


def job_manifest() -> list[dict]:
    """任务清单，供运维接口展示。"""
    return [
        {"name": name, "label": meta["label"], "desc": meta["desc"],
         "interval_minutes": interval_minutes(name)}
        for name, meta in JOBS.items()
    ]
