"""V6 定时任务回归：验证任务「真的产生了业务结果」，而不只是返回 success。

冒烟测试只能验证任务可执行（HTTP 层），这里用直接造数据的方式验证：
1. SLA 超时 → 预约自动取消 + 风险报告作废 + 站内信；
2. 复购回访 → 站内信真实发出，且当天重复执行不重复发送（幂等去重）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, select

from app.database import AsyncSessionLocal
from app.models import Appointment, Message, RiskReport
from app.services import appointment_service
from app.tasks import run_job
from app.utils.datetime_util import gen_order_no
from tests.conftest import cleanup, create_test_pets, get_user_id, rand_future_date, rand_tag

SLA_HOURS_BACK = 5  # 门店配置默认 2 小时超时，回拨 5 小时必然触发


async def test_sla_scan_cancels_overdue_and_invalidates_report():
    """超时未确认的预约被自动取消，风险报告同步作废，并给宠主发站内信。"""
    owner_id = await get_user_id("demo")
    tag = rand_tag("v6sla")
    target = rand_future_date()
    pet_ids = await create_test_pets(owner_id, tag, 1)
    appt_id = report_id = None
    try:
        async with AsyncSessionLocal() as db:
            appt = Appointment(
                order_no=gen_order_no(), user_id=owner_id, pet_id=pet_ids[0],
                service_type="basic_bath", appoint_date=target, slot_time="17:00",
                status="pending", created_by="form", idempotent_key=f"{tag}-sla",
            )
            # 显式回拨创建时间，模拟「提交后一直没人确认」
            appt.created_at = datetime.now() - timedelta(hours=SLA_HOURS_BACK)
            db.add(appt)
            await db.flush()
            report = RiskReport(
                appointment_id=appt.id, pet_id=pet_ids[0], risk_level="low",
                engine_type="rule", risk_items="[]", ai_summary="定时任务回归测试",
                suggestion="", knowledge_refs="[]",
            )
            db.add(report)
            await db.commit()
            appt_id, report_id = appt.id, report.id

        async with AsyncSessionLocal() as db:
            result = await appointment_service.sla_scan(db)
        assert result["escalated"] >= 1, f"未识别出超时预约：{result}"

        async with AsyncSessionLocal() as db:
            appt = await db.get(Appointment, appt_id)
            report = await db.get(RiskReport, report_id)
            assert appt.status == "cancelled", f"预约未自动取消：{appt.status}"
            assert appt.cancel_reason and "超时" in appt.cancel_reason, appt.cancel_reason
            assert report.invalidated == 1, "风险报告未作废"
            notice = await db.scalar(
                select(func.count()).select_from(Message).where(Message.biz_id == appt_id)
            )
            assert int(notice or 0) >= 1, "未发送取消通知"
    finally:
        if appt_id:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(Message).where(Message.biz_id == appt_id))
                await db.execute(delete(RiskReport).where(RiskReport.appointment_id == appt_id))
                await db.commit()
        async with AsyncSessionLocal() as db:
            await cleanup(db, pet_ids=pet_ids)


async def test_repurchase_reminder_sends_once_per_day():
    """长期未洗护的宠物会收到回访提醒，且同一天重复执行不会重复发送。"""
    owner_id = await get_user_id("demo")
    tag = rand_tag("v6churn")
    pet_ids = await create_test_pets(owner_id, tag, 1)
    pet_id = pet_ids[0]
    try:
        # 造一条 120 天前完成的洗护预约（默认 churn_days = 60，必然进入预警）
        async with AsyncSessionLocal() as db:
            db.add(Appointment(
                order_no=gen_order_no(), user_id=owner_id, pet_id=pet_id,
                service_type="basic_bath", appoint_date=date.today() - timedelta(days=120),
                slot_time="10:00", status="completed", created_by="form",
                idempotent_key=f"{tag}-old",
            ))
            await db.commit()

        async def remind_count() -> int:
            async with AsyncSessionLocal() as db:
                return int(await db.scalar(
                    select(func.count()).select_from(Message).where(
                        Message.msg_type == "repurchase_remind", Message.biz_id == pet_id
                    )
                ) or 0)

        async with AsyncSessionLocal() as db:
            first = await run_job(db, "repurchase_reminder", trigger="manual")
        assert first["status"] == "success", first
        assert await remind_count() == 1, "未发出复购回访提醒"

        async with AsyncSessionLocal() as db:
            await run_job(db, "repurchase_reminder", trigger="manual")
        assert await remind_count() == 1, "同日重复执行又发了一条（去重失效）"
    finally:
        async with AsyncSessionLocal() as db:
            await cleanup(db, pet_ids=pet_ids)
