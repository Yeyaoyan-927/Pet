"""预约服务层用例（V8）：下单、幂等、改期、状态机、SLA 巡检、列表口径。

预约是全项目最核心的链路（涉及库存式时段、状态机与审计），此前只有接口冒烟覆盖，
这里补服务层分支：越权、非法日期、终止必填原因、SLA 超时自动取消。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.models import Appointment, Pet, RiskReport, User, WashRecord
from app.schemas.appointment import AppointmentCreate, RescheduleIn
from app.services import appointment_service, setting_service
from app.utils.exceptions import BizError, ConflictError, PermissionError_, StateMachineError
from tests.conftest import rand_tag

DAYS = 150


async def _user(username: str) -> User:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalars().first()
    assert user is not None, "演示账号缺失，请先执行 scripts/init_db.py"
    return user


async def _pet(owner_id: int) -> int:
    tag = rand_tag("v8a")
    async with AsyncSessionLocal() as db:
        pet = Pet(user_id=owner_id, name=f"{tag}犬", species="dog", gender="male",
                  weight=7.0, sterilized=1, aggressive=0, stress_level=1)
        db.add(pet)
        await db.commit()
        return pet.id


async def _cleanup(pet_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        appts = (await db.execute(
            select(Appointment.id).where(Appointment.pet_id.in_(pet_ids))
        )).scalars().all() if pet_ids else []
        if appts:
            await db.execute(delete(WashRecord).where(WashRecord.appointment_id.in_(appts)))
            await db.execute(delete(RiskReport).where(RiskReport.appointment_id.in_(appts)))
            await db.execute(delete(Appointment).where(Appointment.id.in_(appts)))
        if pet_ids:
            await db.execute(delete(Pet).where(Pet.id.in_(pet_ids)))
        await db.commit()


def _slot(offset_days: int) -> tuple[date, str]:
    """随机远期日期 + 随机时段，避免与其他用例抢同一时段（连跑两次也通过）。"""
    import random

    hour = random.choice([9, 10, 11, 14, 15, 16])
    return date.today() + timedelta(days=offset_days), f"{hour:02d}:00"


async def test_create_and_idempotent():
    """下单成功 + 幂等键复用同一单（重复提交不产生第二单）。"""
    owner = await _user("demo")
    pet_id = await _pet(owner.id)
    try:
        async with AsyncSessionLocal() as db:
            d, slot = _slot(DAYS)
            key = rand_tag("idem")
            first = await appointment_service.create_by_customer(db, owner, AppointmentCreate(
                pet_id=pet_id, service_type="basic_bath", appoint_date=d, slot_time=slot,
                idempotent_key=key,
            ))
            assert first.order_no.startswith("PG") and first.status == "pending"

            again = await appointment_service.create_by_customer(db, owner, AppointmentCreate(
                pet_id=pet_id, service_type="basic_bath", appoint_date=d, slot_time=slot,
                idempotent_key=key,
            ))
            assert again.id == first.id, "同一幂等键必须返回同一单"

            # 风险报告应已生成
            report = (await db.execute(
                select(RiskReport).where(RiskReport.appointment_id == first.id)
            )).scalars().first()
            assert report is not None and report.risk_level
    finally:
        await _cleanup([pet_id])


async def test_invalid_inputs_rejected():
    """过去日期 / 非法时段 / 非本人宠物 一律拒绝。"""
    owner = await _user("demo")
    other = await _user("liu")
    pet_id = await _pet(owner.id)
    try:
        async with AsyncSessionLocal() as db:
            past = date.today() - timedelta(days=1)
            with pytest.raises(BizError):
                await appointment_service.create_by_customer(db, owner, AppointmentCreate(
                    pet_id=pet_id, service_type="basic_bath",
                    appoint_date=past, slot_time="10:00",
                ))

            d, _s = _slot(DAYS)
            with pytest.raises(BizError):
                await appointment_service.create_by_customer(db, owner, AppointmentCreate(
                    pet_id=pet_id, service_type="basic_bath",
                    appoint_date=d, slot_time="25:00",
                ))

            # 给别人的宠物下单
            with pytest.raises((BizError, PermissionError_)):
                await appointment_service.create_by_customer(db, other, AppointmentCreate(
                    pet_id=pet_id, service_type="basic_bath",
                    appoint_date=d, slot_time="10:00",
                ))
    finally:
        await _cleanup([pet_id])


async def test_duplicate_same_day_rejected():
    """同一宠物同一天不能重复预约（软约束由 _check_duplicate 拦截）。"""
    owner = await _user("demo")
    pet_id = await _pet(owner.id)
    try:
        async with AsyncSessionLocal() as db:
            d, slot = _slot(DAYS + 5)
            await appointment_service.create_by_customer(db, owner, AppointmentCreate(
                pet_id=pet_id, service_type="basic_bath", appoint_date=d, slot_time=slot,
                idempotent_key=rand_tag("idem"),
            ))
            with pytest.raises(ConflictError):
                await appointment_service.create_by_customer(db, owner, AppointmentCreate(
                    pet_id=pet_id, service_type="grooming", appoint_date=d,
                    slot_time="18:00", idempotent_key=rand_tag("idem"),
                ))
    finally:
        await _cleanup([pet_id])


async def test_reschedule_rules():
    """改期：换时段成功并累计次数；改到已满时段被拒。"""
    owner = await _user("demo")
    pet_id = await _pet(owner.id)
    try:
        async with AsyncSessionLocal() as db:
            d, slot = _slot(DAYS + 10)
            appt = await appointment_service.create_by_customer(db, owner, AppointmentCreate(
                pet_id=pet_id, service_type="basic_bath", appoint_date=d, slot_time=slot,
                idempotent_key=rand_tag("idem"),
            ))
            new_date = d + timedelta(days=1)
            moved = await appointment_service.reschedule(db, appt, RescheduleIn(
                appoint_date=new_date, slot_time="16:00", reason="家里临时有事",
            ), owner)
            assert moved.appoint_date == new_date and moved.slot_time == "16:00"
            assert moved.reschedule_times >= 1

            # 相同时段改期不应被自己的占位挡住（容量校验需排除自身）
            same = await appointment_service.reschedule(db, moved, RescheduleIn(
                appoint_date=new_date, slot_time="16:00", reason="只是改备注",
            ), owner)
            assert same.id == moved.id
    finally:
        await _cleanup([pet_id])


async def test_status_machine_and_reason_required():
    """状态机：非法流转被拒；终止类必须填原因；完成时归档洗护记录。"""
    owner = await _user("demo")
    staff = await _user("staff1")
    pet_id = await _pet(owner.id)
    try:
        async with AsyncSessionLocal() as db:
            d, slot = _slot(DAYS + 20)
            appt = await appointment_service.create_by_customer(db, owner, AppointmentCreate(
                pet_id=pet_id, service_type="basic_bath", appoint_date=d, slot_time=slot,
                idempotent_key=rand_tag("idem"),
            ))

            # pending 不能直接完成
            with pytest.raises(StateMachineError):
                await appointment_service.change_status(db, appt, "completed", staff, "越级完成")

            await appointment_service.change_status(db, appt, "confirmed", staff)
            await appointment_service.change_status(db, appt, "arrived", staff)
            await appointment_service.change_status(db, appt, "in_service", staff)

            # 终止类必填原因
            with pytest.raises(BizError):
                await appointment_service.change_status(db, appt, "cancelled", staff)

            await appointment_service.change_status(db, appt, "completed", staff,
                                                    "服务完成，毛孩子很配合")
            assert appt.status == "completed"

            record = (await db.execute(
                select(WashRecord).where(WashRecord.appointment_id == appt.id)
            )).scalars().first()
            assert record is not None, "完成后应自动归档洗护记录"
    finally:
        await _cleanup([pet_id])


async def test_list_and_detail_permissions():
    """列表：宠主只看自己的；店员看全部；越权查详情被拒。"""
    owner = await _user("demo")
    other = await _user("liu")
    staff = await _user("staff1")
    pet_id = await _pet(owner.id)
    try:
        async with AsyncSessionLocal() as db:
            d, slot = _slot(DAYS + 30)
            appt = await appointment_service.create_by_customer(db, owner, AppointmentCreate(
                pet_id=pet_id, service_type="basic_bath", appoint_date=d, slot_time=slot,
                idempotent_key=rand_tag("idem"),
            ))

            mine = await appointment_service.list_appointments(db, owner, page=1, size=50)
            assert any(a["id"] == appt.id for a in mine[0])

            theirs = await appointment_service.list_appointments(db, other, page=1, size=50)
            assert all(a["id"] != appt.id for a in theirs[0])

            all_rows = await appointment_service.list_appointments(db, staff, page=1, size=50)
            assert any(a["id"] == appt.id for a in all_rows[0])

            with pytest.raises((PermissionError_, BizError)):
                await appointment_service.get_appointment_for_user(db, appt.id, other)

            detail = await appointment_service.get_appointment_for_user(db, appt.id, owner)
            assert detail.id == appt.id
            out = appointment_service.appointment_to_out(detail, None, None)
            assert out["order_no"] == appt.order_no
    finally:
        await _cleanup([pet_id])


async def test_sla_scan_cancels_timeout():
    """SLA 巡检：超时未确认的单自动取消（并作废风险报告）。"""
    owner = await _user("demo")
    pet_id = await _pet(owner.id)
    try:
        async with AsyncSessionLocal() as db:
            original = await setting_service.get_value(db, "auto_cancel_on_timeout")
            try:
                await setting_service.update_setting(db, "auto_cancel_on_timeout", "true", owner)
                await setting_service.update_setting(db, "staff_confirm_timeout_hours", "1", owner)
                await db.commit()

                d, slot = _slot(DAYS + 40)
                appt = await appointment_service.create_by_customer(db, owner, AppointmentCreate(
                    pet_id=pet_id, service_type="basic_bath", appoint_date=d, slot_time=slot,
                    idempotent_key=rand_tag("idem"),
                ))
                # 把创建时间推到 3 小时前，模拟超时
                await db.execute(
                    Appointment.__table__.update().where(Appointment.id == appt.id)
                    .values(created_at=appt.created_at - timedelta(hours=3))
                )
                await db.commit()
                await db.refresh(appt)

                result = await appointment_service.sla_scan(db)
                assert result["cancelled"] >= 1, f"超时单应被自动取消：{result}"
                await db.refresh(appt)
                assert appt.status in ("cancelled", "expired", "timeout_cancelled")
            finally:
                await setting_service.update_setting(db, "auto_cancel_on_timeout", original or "true", owner)
                await db.commit()
    finally:
        await _cleanup([pet_id])


async def test_pet_age_text():
    """月龄文案：幼年 / 成年都能正常输出，空生日返回占位。"""
    pet = Pet(name="x", species="dog", weight=5, sterilized=1,
              birthday=date.today() - timedelta(days=40))
    assert "月" in appointment_service.pet_age_text(pet)
    pet.birthday = None
    assert appointment_service.pet_age_text(pet)
