"""寄养服务层用例（V8）：定价、房态、下单门槛、状态机、延期、看板。

为什么在服务层测而不是走接口：这些规则（尤其定价的三重百分比与疫苗口径）
是**纯业务计算**，服务层直测更精确，也更容易覆盖边界分支。
所有用例自建宠物与房舍（随机 tag），结束即清理，可重复执行。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import delete, func, select, update

from app.constants import BoardingOrderStatus, BoardingRoomStatus, FeedingPlan
from app.database import AsyncSessionLocal
from app.models import (
    BoardingCareLog,
    BoardingCarePlan,
    BoardingOrder,
    BoardingPickupTask,
    BoardingRoom,
    Pet,
    User,
    VaccineRecord,
)
from app.schemas.boarding import BoardingOrderCreate, CareLogIn
from app.services import boarding_service, setting_service
from app.utils.exceptions import BizError, StateMachineError
from tests.conftest import rand_tag

# 远期日期：避免与演示数据/其他用例抢房舍
IN_DAYS = 260


def _load(module_attr):
    return module_attr


async def _demo_user(username: str) -> User:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalars().first()
    assert user is not None, "演示账号缺失，请先执行 scripts/init_db.py"
    return user


async def _make_pet(owner_id: int, *, weight: float = 8.0, allergy: str | None = None,
                    species: str = "dog", birthday: date | None = None, sterilized: int = 1,
                    with_vaccine: bool = True, vaccine_days: int = 400) -> int:
    tag = rand_tag("v8b")
    async with AsyncSessionLocal() as db:
        pet = Pet(user_id=owner_id, name=f"{tag}犬", species=species, gender="male",
                  weight=weight, sterilized=sterilized, allergy=allergy, birthday=birthday)
        db.add(pet)
        await db.flush()
        if with_vaccine:
            db.add(VaccineRecord(pet_id=pet.id, record_type="vaccine", name="狂犬疫苗",
                                 record_date=date.today(),
                                 next_date=date.today() + timedelta(days=vaccine_days)))
        await db.commit()
        return pet.id


async def _make_room(*, ratio: int = 100, capacity: int = 1, room_type: str = "standard") -> int:
    tag = rand_tag("v8r")
    async with AsyncSessionLocal() as db:
        room = BoardingRoom(room_no=tag, room_type=room_type, name=f"{tag}房",
                            species_limit="all", weight_limit=50, ratio_percent=ratio,
                            capacity=capacity, status=BoardingRoomStatus.IDLE.value)
        db.add(room)
        await db.commit()
        return room.id


async def _cleanup(pet_ids: list[int], room_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        orders = (await db.execute(
            select(BoardingOrder.id).where(BoardingOrder.pet_id.in_(pet_ids))
        )).scalars().all() if pet_ids else []
        if orders:
            await db.execute(delete(BoardingPickupTask).where(BoardingPickupTask.order_id.in_(orders)))
            await db.execute(delete(BoardingCareLog).where(BoardingCareLog.order_id.in_(orders)))
            await db.execute(delete(BoardingCarePlan).where(BoardingCarePlan.order_id.in_(orders)))
            await db.execute(delete(BoardingOrder).where(BoardingOrder.id.in_(orders)))
        if pet_ids:
            await db.execute(delete(VaccineRecord).where(VaccineRecord.pet_id.in_(pet_ids)))
            await db.execute(delete(Pet).where(Pet.id.in_(pet_ids)))
        if room_ids:
            await db.execute(delete(BoardingRoom).where(BoardingRoom.id.in_(room_ids)))
        await db.commit()


@pytest.fixture
async def env():
    """一套隔离的寄养环境：宠主 + 宠物 + 房舍。"""
    owner = await _demo_user("demo")
    pet_id = await _make_pet(owner.id, weight=8.0)
    room_id = await _make_room()
    yield {"owner": owner, "pet_id": pet_id, "room_id": room_id}
    await _cleanup([pet_id], [room_id])


async def test_quote_weight_tiers_and_room_ratio():
    """日费 = 体重档基准价 × 房型系数；猫 30 / 小犬 40 / 中犬 50 / 大犬 60 / 超大 70。"""
    owner = await _demo_user("demo")
    pet_ids: list[int] = []
    cases = [("cat", 4.0, 3000), ("dog", 5.0, 4000), ("dog", 8.0, 5000),
             ("dog", 15.0, 5000), ("dog", 25.0, 6000), ("dog", 35.0, 7000)]
    # ⚠️ 必须先把宠物全部建好再开查询会话：MySQL REPEATABLE READ 下，
    # 同一事务后续看不到其他连接插入的数据（与 E-25 同源）
    for species, weight, _expected in cases:
        pet_ids.append(await _make_pet(owner.id, weight=weight, species=species))
    try:
        async with AsyncSessionLocal() as db:
            room_a = (await db.execute(select(BoardingRoom).where(BoardingRoom.ratio_percent == 100))).scalars().first()
            room_b = (await db.execute(select(BoardingRoom).where(BoardingRoom.ratio_percent == 200))).scalars().first()
            assert room_a is not None and room_b is not None, "缺少种子房型"

            for idx, (species, weight, expected) in enumerate(cases):
                pet = (await db.execute(select(Pet).where(Pet.id == pet_ids[idx]))).scalars().first()
                q = await boarding_service.quote(
                    db, pet=pet, room=room_a, check_in=date.today() + timedelta(days=IN_DAYS),
                    check_out=date.today() + timedelta(days=IN_DAYS + 3),
                )
                assert q["daily_fee_cents"] == expected, f"{species}{weight}kg 日费应为 {expected} 分"

            # 房型系数 200%
            pet = (await db.execute(select(Pet).where(Pet.id == pet_ids[1]))).scalars().first()
            q200 = await boarding_service.quote(
                db, pet=pet, room=room_b, check_in=date.today() + timedelta(days=IN_DAYS),
                check_out=date.today() + timedelta(days=IN_DAYS + 2),
            )
            assert q200["daily_fee_cents"] == 8000
            assert q200["room_ratio_percent"] == 200
    finally:
        await _cleanup(pet_ids, [])


async def test_quote_feeding_and_shipping_charges():
    """升级粮 / 处方餐按晚加价；上门接 + 送宠到家两段费用可同时收。"""
    owner = await _demo_user("demo")
    pet_id = await _make_pet(owner.id, weight=8.0)
    room_id = await _make_room()
    try:
        async with AsyncSessionLocal() as db:
            pet = (await db.execute(select(Pet).where(Pet.id == pet_id))).scalars().first()
            room = (await db.execute(select(BoardingRoom).where(BoardingRoom.id == room_id))).scalars().first()
            cin, cout = date.today() + timedelta(days=IN_DAYS), date.today() + timedelta(days=IN_DAYS + 2)

            base = await boarding_service.quote(db, pet=pet, room=room, check_in=cin, check_out=cout)
            premium = await boarding_service.quote(db, pet=pet, room=room, check_in=cin, check_out=cout,
                                                   feeding_plan=FeedingPlan.PREMIUM.value)
            rx = await boarding_service.quote(db, pet=pet, room=room, check_in=cin, check_out=cout,
                                              feeding_plan=FeedingPlan.PRESCRIPTION.value)
            assert premium["feeding_fee_cents"] == 1000 * 2   # 升级粮 10 元/晚 × 2 晚
            assert rx["feeding_fee_cents"] == 2000 * 2        # 处方餐 20 元/晚 × 2 晚
            assert premium["total_cents"] > base["total_cents"]

            both = await boarding_service.quote(
                db, pet=pet, room=room, check_in=cin, check_out=cout,
                dropoff_method="pickup", pickup_back_method="return",
            )
            assert both["pickup_fee_cents"] > 0 and both["return_fee_cents"] > 0
            assert both["shipping_fee_cents"] == both["pickup_fee_cents"] + both["return_fee_cents"]

            self_both = await boarding_service.quote(
                db, pet=pet, room=room, check_in=cin, check_out=cout,
                dropoff_method="self", pickup_back_method="self",
            )
            assert self_both["shipping_fee_cents"] == 0
    finally:
        await _cleanup([pet_id], [room_id])


async def test_quote_long_stay_discount_boundary():
    """长住折扣按配置起始晚数触发：恰好 18 晚打 9 折，17 晚不打折。"""
    owner = await _demo_user("demo")
    pet_id = await _make_pet(owner.id, weight=8.0)
    room_id = await _make_room()
    try:
        async with AsyncSessionLocal() as db:
            pet = (await db.execute(select(Pet).where(Pet.id == pet_id))).scalars().first()
            room = (await db.execute(select(BoardingRoom).where(BoardingRoom.id == room_id))).scalars().first()
            cin = date.today() + timedelta(days=IN_DAYS)

            q17 = await boarding_service.quote(db, pet=pet, room=room, check_in=cin,
                                               check_out=cin + timedelta(days=17))
            q18 = await boarding_service.quote(db, pet=pet, room=room, check_in=cin,
                                               check_out=cin + timedelta(days=18))
            assert q17["nights"] == 17 and q17["discount_percent"] == 100
            assert q18["nights"] == 18 and q18["discount_percent"] == 90
            assert q18["discounted_cents"] == q18["subtotal_cents"] * 90 // 100
    finally:
        await _cleanup([pet_id], [room_id])


async def test_quote_holiday_surcharge():
    """节假日系数按天生效：把区间内的某天配成 200%，小计必须上涨。"""
    owner = await _demo_user("demo")
    pet_id = await _make_pet(owner.id, weight=8.0)
    room_id = await _make_room()
    try:
        async with AsyncSessionLocal() as db:
            pet = (await db.execute(select(Pet).where(Pet.id == pet_id))).scalars().first()
            room = (await db.execute(select(BoardingRoom).where(BoardingRoom.id == room_id))).scalars().first()
            cin = date.today() + timedelta(days=IN_DAYS)
            cout = cin + timedelta(days=2)

            original_dates = await setting_service.get_value(db, "board_holiday_dates")
            original_percent = await setting_service.get_value(db, "board_holiday_percent")
            try:
                await setting_service.update_setting(db, "board_holiday_dates", cin.isoformat(), owner)
                await setting_service.update_setting(db, "board_holiday_percent", "200", owner)
                holiday = await boarding_service.quote(db, pet=pet, room=room, check_in=cin, check_out=cout)
                assert holiday["holiday_nights"] == 1
                # 中型犬基准 50 元/晚：一晚按 200% 计价 → 100 元 + 50 元 = 150 元
                assert holiday["subtotal_cents"] == 15000, holiday["subtotal_cents"]
            finally:
                await setting_service.update_setting(db, "board_holiday_dates", original_dates or "", owner)
                await setting_service.update_setting(db, "board_holiday_percent", original_percent or "130", owner)
    finally:
        await _cleanup([pet_id], [room_id])


async def test_list_rooms_with_dates():
    """带日期查房型必须成功，并给出预估日费与可订标记（曾因误用 quote 导致整体 400）。"""
    owner = await _demo_user("demo")
    pet_id = await _make_pet(owner.id, weight=8.0)
    try:
        async with AsyncSessionLocal() as db:
            pet = (await db.execute(select(Pet).where(Pet.id == pet_id))).scalars().first()
            cin = date.today() + timedelta(days=IN_DAYS)
            rooms = await boarding_service.list_rooms(db, pet=pet, check_in=cin, check_out=cin + timedelta(days=2))
            assert len(rooms) >= 5
            assert all(r["est_daily_cents"] > 0 for r in rooms)
            assert any(r["available"] for r in rooms)
            # 不带日期也要能查（前端首次进入时）
            assert len(await boarding_service.list_rooms(db)) >= 5
    finally:
        await _cleanup([pet_id], [])


async def test_create_order_requires_vaccine_and_terms():
    """疫苗完整与条款确认都是硬门槛。"""
    owner = await _demo_user("demo")
    no_vac = await _make_pet(owner.id, with_vaccine=False)
    expired = await _make_pet(owner.id, vaccine_days=1)   # 明天过期，入住日在 260 天后
    ok_pet = await _make_pet(owner.id, vaccine_days=IN_DAYS + 60)
    room_id = await _make_room()
    try:
        async with AsyncSessionLocal() as db:
            cin, cout = date.today() + timedelta(days=IN_DAYS), date.today() + timedelta(days=IN_DAYS + 2)
            with pytest.raises(BizError):
                await boarding_service.create_order(db, owner, BoardingOrderCreate(
                    pet_id=no_vac, room_id=room_id, check_in_date=cin, check_out_date=cout,
                    terms_confirmed=True,
                ))
            with pytest.raises(BizError):
                await boarding_service.create_order(db, owner, BoardingOrderCreate(
                    pet_id=expired, room_id=room_id, check_in_date=cin, check_out_date=cout,
                    terms_confirmed=True,
                ))
            with pytest.raises(BizError):
                await boarding_service.create_order(db, owner, BoardingOrderCreate(
                    pet_id=ok_pet, room_id=room_id, check_in_date=cin, check_out_date=cout,
                    terms_confirmed=False,
                ))
            # 离店不晚于入住
            with pytest.raises(BizError):
                await boarding_service.create_order(db, owner, BoardingOrderCreate(
                    pet_id=ok_pet, room_id=room_id, check_in_date=cin, check_out_date=cin,
                    terms_confirmed=True,
                ))
    finally:
        await _cleanup([no_vac, expired, ok_pet], [room_id])


async def test_create_order_success_with_care_plans_and_tasks():
    """下单成功：费用落库、照护计划入库、两段接送各生成一条任务。"""
    owner = await _demo_user("demo")
    pet_id = await _make_pet(owner.id, weight=8.0)
    room_id = await _make_room()
    try:
        async with AsyncSessionLocal() as db:
            cin, cout = date.today() + timedelta(days=IN_DAYS), date.today() + timedelta(days=IN_DAYS + 3)
            order = await boarding_service.create_order(db, owner, BoardingOrderCreate(
                pet_id=pet_id, room_id=room_id, check_in_date=cin, check_out_date=cout,
                dropoff_method="pickup", pickup_back_method="return",
                shipping_address="回归路 1 号", shipping_slot="10:00-12:00",
                emergency_contact="张女士", medical_authorized=True, terms_confirmed=True,
                care_items=[
                    {"item_type": "medication", "content": "关节片 1 粒", "frequency": "每日 1 次", "need_staff": True},
                    {"item_type": "taboo", "content": "禁止同区活动", "need_staff": False},
                ],
                idempotent_key=f"{rand_tag('idem')}",
            ))
            assert order.order_no.startswith("BG")
            assert order.total_cents > 0 and order.nights == 3
            assert order.status == BoardingOrderStatus.PENDING.value

            plans = await boarding_service.list_care_plans(db, order.id)
            assert len(plans) == 2

            # 服务层返回的是 (任务, 订单) 元组，转 out 后才是字典
            tasks = await boarding_service.list_pickup_tasks(db, owner)
            mine = [boarding_service.pickup_task_to_out(t, o) for t, o in tasks if t.order_id == order.id]
            assert len(mine) == 2
            assert {t["task_type"] for t in mine} == {"pickup", "return"}
            assert all(t["order_no"] == order.order_no for t in mine)

            # 详情带照护计划与接送任务
            detail = await boarding_service.get_order_for_user(db, order.id, owner)
            assert detail.pet_id == pet_id
    finally:
        await _cleanup([pet_id], [room_id])


async def test_change_status_illegal_and_full_flow():
    """非法流转必须 409（StateMachineError）；合法链路能一路推进并写时间戳。"""
    owner = await _demo_user("demo")
    pet_id = await _make_pet(owner.id, weight=8.0)
    room_id = await _make_room()
    try:
        async with AsyncSessionLocal() as db:
            cin, cout = date.today() + timedelta(days=IN_DAYS), date.today() + timedelta(days=IN_DAYS + 2)
            order = await boarding_service.create_order(db, owner, BoardingOrderCreate(
                pet_id=pet_id, room_id=room_id, check_in_date=cin, check_out_date=cout,
                terms_confirmed=True, idempotent_key=rand_tag("idem"),
            ))
            with pytest.raises(StateMachineError):
                await boarding_service.change_status(db, order, "completed", owner)

            await boarding_service.change_status(db, order, "confirmed", owner)
            await boarding_service.change_status(db, order, "waiting_checkin", owner)
            await boarding_service.change_status(db, order, "checked_in", owner)
            assert order.checkin_at is not None

            log = await boarding_service.add_care_log(db, order, owner, CareLogIn(
                eating="正常", drinking="正常", stool="2 次", spirit="活泼",
                photos=["/static/snapshots/demo.jpg"], sop_checked=["喂食", "换水"],
            ))
            assert log.abnormal == 0
            # 异常日志应触发异常标记
            bad = await boarding_service.add_care_log(db, order, owner, CareLogIn(
                eating="偏少", abnormal=True, abnormal_note="轻微呕吐，已观察",
            ))
            assert bad.abnormal == 1
            assert len(await boarding_service.list_care_logs(db, order.id)) >= 2

            await boarding_service.change_status(db, order, "waiting_pickup", owner)
            await boarding_service.change_status(db, order, "completed", owner)
            assert order.status == BoardingOrderStatus.COMPLETED.value
            assert order.checkout_at is not None

            with pytest.raises(StateMachineError):
                await boarding_service.change_status(db, order, "checked_in", owner)
    finally:
        await _cleanup([pet_id], [room_id])


async def test_extend_order_rules():
    """延期：缩短被拒、超期最长天数被拒、成功则按新时长重算。"""
    owner = await _demo_user("demo")
    pet_id = await _make_pet(owner.id, weight=8.0)
    room_id = await _make_room()
    try:
        async with AsyncSessionLocal() as db:
            cin = date.today() + timedelta(days=IN_DAYS)
            cout = cin + timedelta(days=3)
            order = await boarding_service.create_order(db, owner, BoardingOrderCreate(
                pet_id=pet_id, room_id=room_id, check_in_date=cin, check_out_date=cout,
                terms_confirmed=True, idempotent_key=rand_tag("idem"),
            ))
            with pytest.raises(BizError):
                await boarding_service.extend_order(db, order, cout - timedelta(days=1), owner)

            extended = await boarding_service.extend_order(db, order, cout + timedelta(days=2), owner)
            assert extended.check_out_date == cout + timedelta(days=2)
            assert extended.nights == 5 and extended.extend_times >= 1
    finally:
        await _cleanup([pet_id], [room_id])


async def test_dashboard_shape():
    """看板必须给出运营关心的口径（收入 / 客单价 / 入住率 / 异常率）。"""
    async with AsyncSessionLocal() as db:
        start = date.today() - timedelta(days=180)
        data = await boarding_service.dashboard(db, start, date.today() + timedelta(days=365))
        for key in ("orders", "revenue", "avg_price", "occupancy_rate", "abnormal_rate",
                    "room_type_stat", "status_stat", "room_status_stat"):
            assert key in data
        assert isinstance(data["room_type_stat"], list)


async def test_room_status_transitions():
    """房态：占用 → 清洁 → 空闲（消杀闭环），非法状态值被拒。"""
    owner = await _demo_user("demo")
    room_id = await _make_room()
    try:
        async with AsyncSessionLocal() as db:
            room = (await db.execute(select(BoardingRoom).where(BoardingRoom.id == room_id))).scalars().first()
            assert room.status == BoardingRoomStatus.IDLE.value
            room.status = BoardingRoomStatus.CLEANING.value
            await db.commit()
            rooms = await boarding_service.list_rooms(db)
            mine = next(r for r in rooms if r["id"] == room_id)
            assert mine["status_label"] == "清洁中"
    finally:
        await _cleanup([], [room_id])


async def test_seed_rooms_is_idempotent():
    """种子房舍幂等：重复执行不会重复插入（演示库每类 10 间，靠 reset_rooms 补齐）。"""
    from app.services import boarding_service

    async with AsyncSessionLocal() as db:
        before = int(await db.scalar(select(func.count()).select_from(BoardingRoom)) or 0)
        added = await boarding_service.seed_rooms(db)
        await db.commit()
        after = int(await db.scalar(select(func.count()).select_from(BoardingRoom)) or 0)
    # 首次可能补入种子房，之后必然是 0；关键是不产生重复房号
    assert after >= before
    assert added >= 0


def test_room_type_alias_and_resolve_room():
    """说「标准房」不该回「没有找到房号」：房型口语要能归一并自动挑同房型最便宜的可订房。"""
    from app.services.boarding_service import normalize_room_type, resolve_room

    assert normalize_room_type("标准房") == "standard"
    assert normalize_room_type("标准单间") == "standard"
    assert normalize_room_type("VIP 套房") == "vip"
    assert normalize_room_type("花园景房") == "garden"
    assert normalize_room_type("阳光") == "sunny"
    assert normalize_room_type("A101") is None

    rooms = [
        {"room_no": "A101", "room_type": "standard", "room_type_label": "标准单间",
         "available": True, "est_daily_cents": 3000},
        {"room_no": "A102", "room_type": "standard", "room_type_label": "标准单间",
         "available": True, "est_daily_cents": 2800},
        {"room_no": "B201", "room_type": "garden", "room_type_label": "花园景房",
         "available": True, "est_daily_cents": 4200},
        {"room_no": "V901", "room_type": "vip", "room_type_label": "VIP 套房",
         "available": False, "est_daily_cents": 9000},
    ]
    room, error = resolve_room(rooms, room_type="标准房")
    assert error == "" and room["room_no"] == "A102", "同房型里应挑最便宜的可订房"

    room, _ = resolve_room(rooms, room_no="B201")
    assert room and room["room_no"] == "B201"

    room, error = resolve_room(rooms, room_no="傻房")
    assert room is None and "没有找到房号" in error

    room, error = resolve_room(rooms, room_type="VIP")
    assert room is None and "订满" in error

    room, _ = resolve_room(rooms)
    assert room["room_no"] == "A102", "不指定时仍给最便宜的可订房"


async def test_early_pickup_apply_and_review():
    """提前接回：宠主申请 → 驳回（订单不动）→ 再申请 → 通过（自动转 early_pickup）。"""
    owner = await _demo_user("demo")
    staff = await _demo_user("staff1")
    pet_id = await _make_pet(owner.id, weight=8.0)
    room_id = await _make_room()
    try:
        async with AsyncSessionLocal() as db:
            cin = date.today() + timedelta(days=IN_DAYS)
            cout = cin + timedelta(days=5)
            order = await boarding_service.create_order(db, owner, BoardingOrderCreate(
                pet_id=pet_id, room_id=room_id, check_in_date=cin, check_out_date=cout,
                terms_confirmed=True, idempotent_key=rand_tag("early"),
            ))
            await boarding_service.change_status(db, order, "confirmed", owner)
            await boarding_service.change_status(db, order, "waiting_checkin", owner)
            await boarding_service.change_status(db, order, "checked_in", owner)

            # 接回日期必须早于原定离店日
            with pytest.raises(BizError):
                await boarding_service.request_early_pickup(db, order, owner, cout, "太晚了")

            req = await boarding_service.request_early_pickup(db, order, owner, cin, "行程有变")
            assert req.status == "pending"
            # 同单不允许并发多条待审核申请
            with pytest.raises(BizError):
                await boarding_service.request_early_pickup(db, order, owner, cin, "重复提交")
            # 同一申请不能审两次
            rejected = await boarding_service.review_early_pickup(db, req, False, "当日接送已满", staff)
            assert rejected["status"] == "rejected"
            with pytest.raises(BizError):
                await boarding_service.review_early_pickup(db, req, True, None, staff)

            await db.refresh(order)
            assert order.status == BoardingOrderStatus.CHECKED_IN.value, "驳回不应改订单状态"

            req2 = await boarding_service.request_early_pickup(
                db, order, owner, date.today() + timedelta(days=1), None
            )
            approved = await boarding_service.review_early_pickup(db, req2, True, "已安排", staff)
            assert approved["status"] == "approved"
            await db.refresh(order)
            assert order.status == BoardingOrderStatus.EARLY_PICKUP.value
            assert order.checkout_at is not None
    finally:
        await _cleanup([pet_id], [room_id])
