"""统计报表服务。全部参数化查询，无动态 NL2SQL（P2 迭代）。

报表口径（对应 docs/11-报表口径说明.md）：
1. 订单量 = 已确认及以上状态订单
2. 服务占比分母 = 已完成订单
3. 复购率 = 同宠物历史至少 2 次已完成洗护的宠物数 / 有已完成洗护的宠物数
4. 爽约率 = 爽约订单 / 已确认订单总数
5. 店员工作量 = 归属该 staff_id 且状态已完成的洗护记录数
6. 高峰期 = 按 1 小时粒度统计预约提交量
7. 流失预警 = 超过 churn_days 无已完成洗护记录的宠物
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    APPOINTMENT_STATUS_LABEL,
    RISK_LEVEL_LABEL,
    SERVICE_TYPE_LABEL,
    AppointmentStatus,
    RiskLevel,
    UserRole,
)
from app.models import Appointment, Pet, RiskReport, User
from app.services import setting_service

CONFIRMED_OR_BEYOND = {
    AppointmentStatus.CONFIRMED.value,
    AppointmentStatus.ARRIVED.value,
    AppointmentStatus.IN_SERVICE.value,
    AppointmentStatus.COMPLETED.value,
    AppointmentStatus.NO_SHOW.value,
    AppointmentStatus.ARRIVED_GIVE_UP.value,
    AppointmentStatus.WASH_INTERRUPT.value,
}


def _rate(numerator: float, denominator: float) -> float:
    """比率计算：分母为 0 时返回 0，避免除零把报表打挂。


    """
    return round(numerator / denominator * 100, 2) if denominator else 0.0


async def summary(
    db: AsyncSession,
    start: date,
    end: date,
    staff_scope_id: int | None = None,
) -> dict:
    """经营报表口径：订单量、完成/取消/爽约率、复购率、服务结构、每日趋势、高峰时段、店员负载、流失与高风险数。"""
    base = [Appointment.deleted_at.is_(None),
            Appointment.appoint_date >= start,
            Appointment.appoint_date <= end]
    if staff_scope_id:
        base.append(Appointment.staff_id == staff_scope_id)

    def _q(*extra):
        return select(func.count()).select_from(Appointment).where(*base, *extra)

    total_orders = int(await db.scalar(_q(Appointment.status.in_(CONFIRMED_OR_BEYOND))) or 0)
    completed = int(await db.scalar(_q(Appointment.status == AppointmentStatus.COMPLETED.value)) or 0)
    cancelled = int(await db.scalar(_q(Appointment.status == AppointmentStatus.CANCELLED.value)) or 0)
    no_show = int(await db.scalar(_q(Appointment.status == AppointmentStatus.NO_SHOW.value)) or 0)
    confirmed_total = int(await db.scalar(_q(Appointment.status.in_(CONFIRMED_OR_BEYOND))) or 0)
    give_up = int(await db.scalar(
        _q(Appointment.status.in_([AppointmentStatus.ARRIVED_GIVE_UP.value,
                                    AppointmentStatus.WASH_INTERRUPT.value]))) or 0)

    # 服务占比（分母 = 已完成）
    service_rows = (
        await db.execute(
            select(Appointment.service_type, func.count())
            .where(*base, Appointment.status == AppointmentStatus.COMPLETED.value)
            .group_by(Appointment.service_type)
        )
    ).all()
    service_ratio = [
        {"label": SERVICE_TYPE_LABEL.get(t, t), "value": _rate(c, completed)} for t, c in service_rows
    ]

    # 状态分布
    status_rows = (
        await db.execute(select(Appointment.status, func.count()).where(*base).group_by(Appointment.status))
    ).all()
    status_distribution = [
        {"label": APPOINTMENT_STATUS_LABEL.get(s, s), "value": c} for s, c in status_rows
    ]

    # 日趋势
    trend_rows = (
        await db.execute(
            select(Appointment.appoint_date, func.count())
            .where(*base).group_by(Appointment.appoint_date).order_by(Appointment.appoint_date)
        )
    ).all()
    daily_trend = [
        {"label": d.strftime("%m-%d"), "value": c} for d, c in trend_rows
    ]

    # 高峰时段（按提交时间 1 小时粒度）
    peak_rows = (
        await db.execute(
            select(func.hour(Appointment.created_at), func.count())
            .where(*base).group_by(func.hour(Appointment.created_at)).order_by(func.hour(Appointment.created_at))
        )
    ).all()
    hour_map = {int(h): c for h, c in peak_rows}
    peak_hours = [{"label": f"{h:02d}:00", "value": hour_map.get(h, 0)} for h in range(8, 21)]

    # 店员工作量
    workload_rows = (
        await db.execute(
            select(Appointment.staff_id, User.real_name, func.count())
            .outerjoin(User, User.id == Appointment.staff_id)
            .where(*base, Appointment.status == AppointmentStatus.COMPLETED.value,
                   Appointment.staff_id.is_not(None))
            .group_by(Appointment.staff_id, User.real_name)
            .order_by(func.count().desc())
        )
    ).all()
    staff_workload = [
        {"staff_id": sid, "staff_name": name or f"店员#{sid}", "finished_count": c}
        for sid, name, c in workload_rows
    ]

    # 复购率（宠物维度）
    pet_rows = (
        await db.execute(
            select(Appointment.pet_id, func.count())
            .where(*base, Appointment.status == AppointmentStatus.COMPLETED.value)
            .group_by(Appointment.pet_id)
        )
    ).all()
    pets_with_wash = len(pet_rows)
    repurchase_pets = sum(1 for _, c in pet_rows if c >= 2)
    repurchase_rate = _rate(repurchase_pets, pets_with_wash)

    # 高风险报告数
    risk_high = int(
        await db.scalar(
            select(func.count()).select_from(RiskReport)
            .where(RiskReport.risk_level == RiskLevel.HIGH.value,
                   RiskReport.invalidated == 0)
        ) or 0
    )

    # 流失预警
    churn_days = await setting_service.get_int(db, "churn_days")
    threshold = date.today() - timedelta(days=churn_days)
    last_wash = (
        select(Appointment.pet_id, func.max(Appointment.appoint_date).label("last_date"))
        .where(Appointment.status == AppointmentStatus.COMPLETED.value)
        .group_by(Appointment.pet_id)
        .subquery()
    )
    churn_stmt = (
        select(Pet, last_wash.c.last_date)
        .outerjoin(last_wash, last_wash.c.pet_id == Pet.id)
        .where(Pet.deleted_at.is_(None),
               (last_wash.c.last_date.is_(None)) | (last_wash.c.last_date <= threshold))
        # 注意：MySQL 不支持 NULLS FIRST 语法；ASC 排序本身即把 NULL 排在最前
        .order_by(last_wash.c.last_date.asc())
        .limit(20)
    )
    churn_rows = (await db.execute(churn_stmt)).all()
    churn_pets = []
    for pet, last_date in churn_rows:
        churn_pets.append({
            "pet_id": pet.id,
            "pet_name": pet.name,
            "owner_name": None,
            "last_wash_date": last_date.strftime("%Y-%m-%d") if last_date else None,
            "idle_days": (date.today() - last_date).days if last_date else None,
        })

    return {
        "range_start": start.strftime("%Y-%m-%d"),
        "range_end": end.strftime("%Y-%m-%d"),
        "total_orders": total_orders,
        "completed_orders": completed,
        "cancelled_orders": cancelled,
        "no_show_orders": no_show,
        "no_show_rate": _rate(no_show, confirmed_total),
        "repurchase_rate": repurchase_rate,
        "service_ratio": service_ratio,
        "status_distribution": status_distribution,
        "daily_trend": daily_trend,
        "peak_hours": peak_hours,
        "staff_workload": staff_workload,
        "churn_pets": churn_pets,
        "risk_high_count": risk_high,
        "give_up_count": give_up,
        "churn_days": churn_days,
    }


def default_range() -> tuple[date, date]:
    """默认统计区间（近 30 天）。"""
    today = date.today()
    return today - timedelta(days=29), today
