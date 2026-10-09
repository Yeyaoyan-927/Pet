"""V6 核心回归：时段容量并发防超卖。

为什么必须用**真实并发 + 独立会话**：
- 顺序调用永远测不出 check-then-act 竞态；
- 复用同一个会话只会测到 SQLAlchemy 的会话缓存，测不到数据库的隔离级别行为。

本用例的真实价值（修复过程记录）：
- 第一版只加了 `SELECT ... FOR UPDATE` 行锁，10 并发 **10 单全部成功** —— 因为容量校验用的
  `SELECT COUNT(*)` 在 MySQL 默认 REPEATABLE READ 下是**快照读**，等锁的事务读到的是自己
  事务开始时的旧快照；
- 把容量校验也改成当前读（`FOR UPDATE`）后，才真正做到「恰好容量数成功」。
"""
from __future__ import annotations

import asyncio

from sqlalchemy import delete, select

from app.constants import ACTIVE_APPOINTMENT_STATUS
from app.database import AsyncSessionLocal
from app.models import Appointment, StoreSetting, User
from app.schemas.appointment import AppointmentCreate
from app.services import appointment_service
from app.utils.exceptions import BizError, ConflictError
from tests.conftest import cleanup, create_test_pets, get_user_id, rand_future_date, rand_tag

CAPACITY = 2
RACERS = 10
SLOT = "15:00"


async def _set_capacity(value: int) -> None:
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(StoreSetting).where(StoreSetting.setting_key == "default_slot_capacity")
            )
        ).scalars().first()
        if row is not None:
            row.setting_value = str(value)
            await db.commit()


async def _book(owner_id: int, pet_id: int, target, key: str) -> str:
    """一次并发下单：独占会话（等价于一个独立 HTTP 请求）。"""
    async with AsyncSessionLocal() as db:
        owner = await db.get(User, owner_id)
        payload = AppointmentCreate(
            pet_id=pet_id, service_type="basic_bath", appoint_date=target,
            slot_time=SLOT, idempotent_key=key,
        )
        try:
            await appointment_service.create_by_customer(db, owner, payload)
            return "ok"
        except (ConflictError, BizError):
            await db.rollback()
            return "conflict"
        except Exception as exc:  # 任何其他异常都算失败，便于定位
            await db.rollback()
            return f"error:{type(exc).__name__}"


async def test_concurrent_booking_never_oversells():
    """10 并发抢 2 个名额 → 恰好 2 单成功，其余全部因容量被拒，库里也只落 2 单。"""
    owner_id = await get_user_id("demo")
    tag = rand_tag("v6race")
    target = rand_future_date()
    pet_ids = await create_test_pets(owner_id, tag, RACERS)
    await _set_capacity(CAPACITY)
    try:
        results = await asyncio.gather(*[
            _book(owner_id, pet_ids[i], target, f"{tag}-{i}") for i in range(RACERS)
        ])

        ok = results.count("ok")
        assert ok == CAPACITY, f"超卖：成功 {ok} 单（容量 {CAPACITY}）→ {results}"
        assert results.count("conflict") == RACERS - CAPACITY, f"拒绝数不符 → {results}"

        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(Appointment.id).where(
                        Appointment.appoint_date == target,
                        Appointment.slot_time == SLOT,
                        Appointment.status.in_(ACTIVE_APPOINTMENT_STATUS),
                    )
                )
            ).scalars().all()
        assert len(rows) == CAPACITY, f"数据库实存 {len(rows)} 单，超出容量 {CAPACITY}"
    finally:
        await _set_capacity(3)
        async with AsyncSessionLocal() as db:
            await cleanup(db, pet_ids=pet_ids, keys_like=f"{tag}-%")
            await db.execute(delete(Appointment).where(Appointment.appoint_date == target))
            await db.commit()


async def test_reschedule_to_same_slot_does_not_self_block():
    """改期到**相同时段**只累计次数：容量校验不能把本单自己算进去而误判已满。"""
    owner_id = await get_user_id("demo")
    tag = rand_tag("v6same")
    target = rand_future_date()
    pet_ids = await create_test_pets(owner_id, tag, 1)
    try:
        async with AsyncSessionLocal() as db:
            owner = await db.get(User, owner_id)
            appt = await appointment_service.create_by_customer(db, owner, AppointmentCreate(
                pet_id=pet_ids[0], service_type="basic_bath", appoint_date=target,
                slot_time=SLOT, idempotent_key=f"{tag}-a",
            ))
            appt_id = appt.id

        # 容量压到 1：此时该时段只有本单占位，改期到同一时段不应被判「已约满」
        await _set_capacity(1)
        async with AsyncSessionLocal() as db:
            appt = await db.get(Appointment, appt_id)
            owner = await db.get(User, owner_id)
            from app.schemas.appointment import RescheduleIn

            updated = await appointment_service.reschedule(
                db, appt, RescheduleIn(appoint_date=target, slot_time=SLOT, reason="同段改期回归"),
                owner,
            )
            assert updated.reschedule_times == 1
            assert updated.appoint_date == target and updated.slot_time == SLOT
    finally:
        await _set_capacity(3)
        async with AsyncSessionLocal() as db:
            await cleanup(db, pet_ids=pet_ids, keys_like=f"{tag}-%")
