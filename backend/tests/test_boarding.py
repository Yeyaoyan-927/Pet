"""V7.1 寄养核心回归：房态并发防超卖。

寄养与预约是**同类风险**：`check-then-act`（先统计重叠订单，再插入）在并发下会双开同一间房。
这里用真实并发 + 独立会话验证「锁 room 行 + 当前读统计」这套组合确实生效 ——
沿用 V6 的结论：只加锁不做当前读，在 REPEATABLE READ 下等于没防。
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from sqlalchemy import delete, select

from app.constants import BoardingOrderStatus
from app.database import AsyncSessionLocal
from app.models import BoardingOrder, BoardingRoom, Pet, User, VaccineRecord
from app.schemas.boarding import BoardingOrderCreate
from app.services import boarding_service
from app.utils.exceptions import BizError, ConflictError
from tests.conftest import cleanup, create_test_pets, get_user_id, rand_tag


async def _prepare(owner_id: int, tag: str) -> tuple[int, int, str, str]:
    """造一只带有效疫苗的宠物 + 一间专属房舍，返回 (pet_id, room_id, check_in, check_out)。"""
    async with AsyncSessionLocal() as db:
        pet = Pet(user_id=owner_id, name=f"{tag}寄养犬", species="dog", gender="male",
                  weight=12, sterilized=1)
        db.add(pet)
        await db.flush()
        # 疫苗必须覆盖入住日：校验口径就是「入住当天仍有效」
        db.add(VaccineRecord(pet_id=pet.id, record_type="vaccine", name="狂犬疫苗",
                             record_date=date.today(),
                             next_date=date.today() + timedelta(days=200)))
        room = BoardingRoom(room_no=f"T{tag[-6:]}", room_type="standard", name="并发回归房",
                            species_limit="all", weight_limit=30, ratio_percent=100, capacity=1)
        db.add(room)
        await db.commit()
        check_in = (date.today() + timedelta(days=30)).isoformat()
        check_out = (date.today() + timedelta(days=33)).isoformat()
        return pet.id, room.id, check_in, check_out


async def _book(owner_id: int, pet_id: int, room_id: int, check_in: str, check_out: str, key: str) -> str:
    async with AsyncSessionLocal() as db:
        owner = await db.get(User, owner_id)
        payload = BoardingOrderCreate(
            pet_id=pet_id, room_id=room_id,
            check_in_date=date.fromisoformat(check_in), check_out_date=date.fromisoformat(check_out),
            terms_confirmed=True, idempotent_key=key,
        )
        try:
            await boarding_service.create_order(db, owner, payload)
            return "ok"
        except (ConflictError, BizError):
            await db.rollback()
            return "conflict"
        except Exception as exc:
            await db.rollback()
            return f"error:{type(exc).__name__}"


async def test_concurrent_boarding_no_double_booking():
    """4 个并发请求抢同一间房同一区间：恰好 1 单成功，库里也只落 1 单。"""
    owner_id = await get_user_id("demo")
    tag = rand_tag("v7board")
    pet_id, room_id, check_in, check_out = await _prepare(owner_id, tag)
    try:
        results = await asyncio.gather(*[
            _book(owner_id, pet_id, room_id, check_in, check_out, f"{tag}-{i}") for i in range(4)
        ])
        assert results.count("ok") == 1, f"房态超卖：成功 {results.count('ok')} 单 → {results}"
        assert results.count("conflict") == 3, results

        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(BoardingOrder.id).where(
                        BoardingOrder.room_id == room_id,
                        BoardingOrder.status.in_([
                            BoardingOrderStatus.PENDING.value,
                            BoardingOrderStatus.CONFIRMED.value,
                            BoardingOrderStatus.WAITING_CHECKIN.value,
                            BoardingOrderStatus.CHECKED_IN.value,
                            BoardingOrderStatus.WAITING_PICKUP.value,
                        ]),
                    )
                )
            ).scalars().all()
        assert len(rows) == 1, f"数据库实存 {len(rows)} 单，房型容量为 1"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(BoardingOrder).where(BoardingOrder.room_id == room_id))
            await db.execute(delete(BoardingRoom).where(BoardingRoom.id == room_id))
            await db.commit()
        async with AsyncSessionLocal() as db:
            await cleanup(db, pet_ids=[pet_id])


async def test_boarding_requires_valid_vaccine():
    """疫苗是硬门槛：无有效疫苗记录时下单被拒（规则卡死，不依赖人工判断）。"""
    owner_id = await get_user_id("demo")
    tag = rand_tag("v7vac")
    pet_id, room_id, check_in, check_out = await _prepare(owner_id, tag)
    try:
        # 把疫苗改成已过期，模拟「疫苗到期未补种」
        async with AsyncSessionLocal() as db:
            rec = (
                await db.execute(select(VaccineRecord).where(VaccineRecord.pet_id == pet_id))
            ).scalars().first()
            rec.next_date = date.today() - timedelta(days=1)
            await db.commit()

        async with AsyncSessionLocal() as db:
            owner = await db.get(User, owner_id)
            try:
                await boarding_service.create_order(db, owner, BoardingOrderCreate(
                    pet_id=pet_id, room_id=room_id,
                    check_in_date=date.fromisoformat(check_in),
                    check_out_date=date.fromisoformat(check_out),
                    terms_confirmed=True, idempotent_key=f"{tag}-expired",
                ))
                raise AssertionError("疫苗过期仍下单成功，硬门槛失效")
            except BizError as exc:
                assert "疫苗" in str(exc), str(exc)
                await db.rollback()
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(BoardingRoom).where(BoardingRoom.id == room_id))
            await db.commit()
        async with AsyncSessionLocal() as db:
            await cleanup(db, pet_ids=[pet_id])
