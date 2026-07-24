"""宠物寄养业务服务（V7.1）。

工程纪律与既有模块完全一致：
- **写操作只在本服务**（Agent / 表单同一入口），状态流转走集中定义的流转表，非法流转 409；
- **房态防超卖**：锁 `boarding_room` 行 + 当前读统计重叠订单（复用 V6 的「锁 + 当前读」结论）；
- **金额全部用「分」整数计算**：定价含房型系数、节假日系数、长住折扣三次百分比乘法，
  浮点会累积误差（40×1.3×1.2 这类乘法用 float 会得到 62.400000000000006）；
- **疫苗完整是硬门槛**：不通过直接拒绝下单（防传染病，规则卡死，不是 AI 建议）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    BOARDING_ACTIVE_STATUS,
    BOARDING_REASON_REQUIRED_STATUS,
    BOARDING_ROOM_STATUS_LABEL,
    BOARDING_STATUS_LABEL,
    BOARDING_TERMINAL_STATUS,
    BOARDING_TRANSITIONS,
    DROPOFF_METHOD_LABEL,
    FEEDING_PLAN_LABEL,
    PICKUP_BACK_METHOD_LABEL,
    PICKUP_TASK_STATUS_LABEL,
    SHIPPING_METHOD_LABEL,
    BoardingOrderStatus,
    BoardingRoomStatus,
    FeedingPlan,
    MessageType,
    ShippingMethod,
    UserRole,
)
from app.models import (
    BoardingCareLog,
    BoardingCarePlan,
    BoardingEarlyPickup,
    BoardingOrder,
    BoardingPickupTask,
    BoardingRoom,
    Pet,
    User,
    VaccineRecord,
)
from app.schemas.boarding import BoardingOrderCreate
from app.services import message_service, setting_service
from app.services.audit_service import write_log
from app.services.pet_service import get_pet_or_404
from app.utils.crypto import encrypt_text, mask_phone
from app.utils.datetime_util import gen_order_no, now
from app.utils.exceptions import BizError, ConflictError, NotFoundError, StateMachineError
from app.utils.logger import logger

SELECTABLE_STATUS = set(BOARDING_TRANSITIONS)

# 房间型展示名与设施（种子数据用）
ROOM_TYPE_LABEL = {
    "standard": "标准单间",
    "garden": "花园景房",
    "sunny": "阳光房",
    "vip": "VIP 套房",
}

# 口语 → 房型：用户/模型说的是「标准房」「VIP 套房」，不是房号
ROOM_TYPE_ALIASES: dict[str, str] = {
    "标准": "standard", "标准房": "standard", "标准间": "standard", "标准单间": "standard",
    "普通房": "standard", "普通间": "standard", "basic": "standard",
    "花园": "garden", "花园房": "garden", "花园景房": "garden", "景观房": "garden",
    "花园景观房": "garden",
    "阳光": "sunny", "阳光房": "sunny", "朝阳房": "sunny", "sun": "sunny",
    "vip": "vip", "vip房": "vip", "vip套房": "vip", "套房": "vip", "贵宾房": "vip",
    "豪华房": "vip", "豪华间": "vip",
}


def normalize_room_type(value: str | None) -> str | None:
    """把「标准房 / 套房 / VIP」这类口语归一成 room_type；认不出返回 None。

    Agent 里的用户常说房型而不是房号（「我要标准房」），早期实现直接把这句话当房号去匹配，
    于是固定回一句「没有找到房号 标准房 的宠舍」——用户根本没法继续。
    """
    if not value:
        return None
    key = str(value).strip().lower().replace(" ", "")
    if key in ROOM_TYPE_LABEL:
        return key
    return ROOM_TYPE_ALIASES.get(key)


def resolve_room(
    rooms: list[dict], room_no: str | None = None, room_type: str | None = None
) -> tuple[dict | None, str]:
    """从可选房舍里挑一间：优先指定房号 → 房型（口语也算）→ 最便宜的可订房。

    返回 (room, 错误提示)。房型命中时**自动挑该房型最便宜的可订房**，
    而不是反问用户房号 —— 说「标准房」的用户本来就不关心是 A103 还是 A107。
    """
    wanted_type = normalize_room_type(room_type) or normalize_room_type(room_no)
    if wanted_type:
        pool = [r for r in rooms if r["room_type"] == wanted_type and r["available"]]
        if not pool:
            label = ROOM_TYPE_LABEL.get(wanted_type, wanted_type)
            return None, f"「{label}」这几天都订满了，换个房型或日期试试？"
        return min(pool, key=lambda r: r.get("est_daily_cents") or 10**9), ""

    if room_no:
        target = str(room_no).strip().lower()
        room = next((r for r in rooms if r["room_no"].lower() == target), None)
        if room is None:
            listing = "、".join(sorted({r["room_type_label"] for r in rooms})) or "（暂无房型）"
            return None, (f"没有找到房号「{room_no}」的宠舍。也可以直接说房型：{listing}")
        if not room["available"]:
            return None, (f"{room['room_no']} 这几天订不了："
                          f"{room.get('unavailable_note') or '房态不可用'}")
        return room, ""

    pool = [r for r in rooms if r["available"]]
    if not pool:
        return None, "这几天没有可用的宠舍，换个日期试试？"
    return min(pool, key=lambda r: r.get("est_daily_cents") or 10**9), ""


# ---------------------------------------------------------------- 定价
async def _base_price_cents(db: AsyncSession, pet: Pet) -> tuple[int, str]:
    """按物种与体重档取基准日价（分）。"""
    if pet.species == "cat":
        return await setting_service.get_int(db, "board_price_cat") * 100, "猫"
    weight = float(pet.weight) if pet.weight is not None else 0.0
    if weight <= 0:
        return await setting_service.get_int(db, "board_price_small") * 100, "小型犬（体重未填，按小型犬计）"
    if weight <= 7.5:
        return await setting_service.get_int(db, "board_price_small") * 100, "小型犬"
    if weight <= 20:
        return await setting_service.get_int(db, "board_price_medium") * 100, "中型犬"
    if weight <= 30:
        return await setting_service.get_int(db, "board_price_large") * 100, "大型犬"
    return await setting_service.get_int(db, "board_price_giant") * 100, "超大型犬"


def _holiday_set(raw: str) -> set[date]:
    """把「逗号分隔的节假日日期」解析成日期集合，非法项直接忽略。


    """
    days: set[date] = set()
    for chunk in (raw or "").replace("，", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            days.add(date.fromisoformat(chunk))
        except ValueError:
            continue
    return days


async def quote(
    db: AsyncSession,
    *,
    pet: Pet,
    room: BoardingRoom,
    check_in: date,
    check_out: date,
    feeding_plan: str = FeedingPlan.SELF.value,
    dropoff_method: str = "self",
    pickup_back_method: str = "self",
) -> dict:
    """费用预估：逐晚计价（节假日系数按天生效）→ 长住折扣 → 接送费 → 粮费加价。

    日费 = 体重档基准价 × 房型系数 ；命中节假日的晚按 节假日系数 再乘一次。
    """
    nights = (check_out - check_in).days
    min_nights = await setting_service.get_int(db, "board_min_nights")
    if nights < min_nights:
        raise BizError(f"寄养最少 {min_nights} 晚，当前选择 {nights} 晚")

    base_cents, weight_label = await _base_price_cents(db, pet)
    holiday_percent = await setting_service.get_int(db, "board_holiday_percent")
    holidays = _holiday_set(await setting_service.get_value(db, "board_holiday_dates"))

    subtotal = 0
    holiday_nights = 0
    for offset in range(nights):
        night = check_in + timedelta(days=offset)
        yuan = base_cents * room.ratio_percent // 100
        if night in holidays:
            yuan = yuan * holiday_percent // 100
            holiday_nights += 1
        subtotal += yuan

    long_days = await setting_service.get_int(db, "board_long_stay_days")
    discount_percent = 100
    if nights >= long_days:
        discount_percent = await setting_service.get_int(db, "board_long_stay_percent")
    discounted = subtotal * discount_percent // 100

    # 粮费加价（按晚）
    feed_per_day = 0
    if feeding_plan == FeedingPlan.PREMIUM.value:
        feed_per_day = await setting_service.get_int(db, "board_premium_fee")
    elif feeding_plan == FeedingPlan.PRESCRIPTION.value:
        feed_per_day = await setting_service.get_int(db, "board_prescription_fee")
    feeding_fee = feed_per_day * 100 * nights

    # 送宠到店与离店接宠是两个独立选项，可能同时产生费用（上门接 + 送宠到家）
    pickup_fee = 0
    if dropoff_method == "pickup":
        pickup_fee = await setting_service.get_int(db, "board_pickup_fee") * 100
    return_fee = 0
    if pickup_back_method == "return":
        return_fee = await setting_service.get_int(db, "board_return_fee") * 100
    shipping_fee = pickup_fee + return_fee

    total = discounted + feeding_fee + shipping_fee
    return {
        "nights": nights,
        "weight_label": weight_label,
        "base_price_cents": base_cents,
        "room_ratio_percent": room.ratio_percent,
        "daily_fee_cents": subtotal // nights if nights else 0,
        "subtotal_cents": subtotal,
        "holiday_nights": holiday_nights,
        "discount_percent": discount_percent,
        "discounted_cents": discounted,
        "feeding_fee_cents": feeding_fee,
        "shipping_fee_cents": shipping_fee,
        "pickup_fee_cents": pickup_fee,
        "return_fee_cents": return_fee,
        "total_cents": total,
    }


# ---------------------------------------------------------------- 房态
async def _lock_room_and_check(db: AsyncSession, room_id: int) -> BoardingRoom:
    """锁住房号行（`FOR UPDATE`）并校验状态，供后续容量当前读使用。"""
    room = (
        await db.execute(select(BoardingRoom).where(BoardingRoom.id == room_id).with_for_update())
    ).scalars().first()
    if room is None:
        raise NotFoundError("宠舍不存在")
    if room.status == BoardingRoomStatus.MAINTENANCE.value:
        raise ConflictError(f"{room.room_no} 正在维护中，暂不可预订")
    return room


async def _count_overlap(
    db: AsyncSession, room_id: int, check_in: date, check_out: date, *, exclude_order_id: int | None = None
) -> int:
    """统计与该日期区间重叠的**有效**订单数。

    用 `FOR UPDATE` 做**当前读**：V6 的教训 —— 只加行锁不做当前读，
    在 REPEATABLE READ 下读到的仍是旧快照，锁等于白加。
    """
    cond = [
        BoardingOrder.room_id == room_id,
        BoardingOrder.status.in_(BOARDING_ACTIVE_STATUS),
        BoardingOrder.check_in_date < check_out,
        BoardingOrder.check_out_date > check_in,
    ]
    if exclude_order_id is not None:
        cond.append(BoardingOrder.id != exclude_order_id)
    rows = (await db.execute(select(BoardingOrder.id).where(*cond).with_for_update())).scalars().all()
    return len(rows)


async def _check_room_capacity(
    db: AsyncSession, room: BoardingRoom, check_in: date, check_out: date, pet: Pet,
    *, exclude_order_id: int | None = None,
) -> None:
    """房态校验：统计与该区间重叠的占用单，超容量则拒绝。


        查询必须用加锁读，否则 REPEATABLE READ 下读到旧快照会超卖。
    """
    if room.species_limit not in ("all", pet.species):
        raise BizError(f"{room.room_no} 不接待该物种（{room.species_limit}）")
    if room.weight_limit and pet.weight is not None and float(pet.weight) > room.weight_limit:
        raise BizError(f"{room.room_no} 限重 {room.weight_limit}kg，当前 {pet.weight}kg，请选择更大房型")

    used = await _count_overlap(db, room.id, check_in, check_out, exclude_order_id=exclude_order_id)
    # 未绝育 / 有攻击倾向强制单间：房型容量再大也只能住一只
    force_single = pet.sterilized == 0 or pet.aggressive == 1
    capacity = 1 if force_single else max(room.capacity, 1)
    if used >= capacity:
        reason = "未绝育或有攻击倾向，需独占房间" if force_single else f"容量 {capacity} 只"
        raise ConflictError(f"{check_in} ~ {check_out} 期间 {room.room_no} 已满（{reason}），请更换房型或日期")


async def list_rooms(
    db: AsyncSession, *, pet: Pet | None = None, check_in: date | None = None, check_out: date | None = None
) -> list[dict]:
    """房型列表；给出日期区间时附带「可订 / 剩余」信息。"""
    rooms = (
        await db.execute(
            select(BoardingRoom).where(BoardingRoom.status != BoardingRoomStatus.MAINTENANCE.value)
            .order_by(BoardingRoom.ratio_percent, BoardingRoom.room_no)
        )
    ).scalars().all()

    base_cents, weight_label = (0, "")
    if pet is not None:
        base_cents, weight_label = await _base_price_cents(db, pet)

    items = []
    for room in rooms:
        usable = True
        note = ""
        if pet is not None:
            if room.species_limit not in ("all", pet.species):
                usable, note = False, "不接待该物种"
            elif room.weight_limit and pet.weight is not None and float(pet.weight) > room.weight_limit:
                usable, note = False, f"限重 {room.weight_limit}kg"
        if usable and pet is not None and check_in and check_out:
            used = await _count_overlap(db, room.id, check_in, check_out)
            force_single = pet.sterilized == 0 or pet.aggressive == 1
            capacity = 1 if force_single else max(room.capacity, 1)
            if used >= capacity:
                usable, note = False, "该日期已满"

        # 预估日费只做「体重档 × 房型系数」，**不能复用 quote()**：
        # quote() 带「最少 N 晚」校验，传 1 天区间会直接抛错，
        # 导致整份房型列表 400（真实 bug：选了宠物+日期后房卡全空）。
        est_daily = base_cents * room.ratio_percent // 100 if pet is not None else 0

        items.append({
            **room_to_out(room),
            "available": usable,
            "unavailable_note": note,
            "est_daily_cents": est_daily,
            "weight_label": weight_label,
        })
    return items


# ---------------------------------------------------------------- 下单
async def _check_vaccine(db: AsyncSession, pet: Pet, check_in: date) -> tuple[bool, str]:
    """疫苗硬门槛：入住日仍有有效的疫苗记录（狂犬 / 联苗均记在 vaccine 类型下）。

    失败时必须说清「哪只宠物、现有有效期到哪天、怎么补救」——
    只回一句「疫苗缺失或已过期」，用户根本不知道是日期选远了还是没登记（V8.2 修）。
    """
    rows = (
        await db.execute(
            select(VaccineRecord).where(
                VaccineRecord.pet_id == pet.id,
                VaccineRecord.record_type == "vaccine",
                VaccineRecord.next_date.is_not(None),
                VaccineRecord.next_date >= check_in,
            )
        )
    ).scalars().all()
    if rows:
        names = "、".join((r.name or "疫苗") for r in rows[:3])
        return True, f"有效期至 {max(r.next_date for r in rows)}（{names}）"

    latest = await db.scalar(
        select(func.max(VaccineRecord.next_date)).where(
            VaccineRecord.pet_id == pet.id,
            VaccineRecord.record_type == "vaccine",
            VaccineRecord.next_date.is_not(None),
        )
    )
    tip = "可在「宠物档案 → 疫苗驱虫记录」补录新记录"
    if latest:
        return False, (
            f"「{pet.name}」的疫苗有效期到 {latest}，覆盖不到入住日 {check_in}。"
            f"{tip}，或把入住日期改到 {latest} 之前"
        )
    return False, (
        f"「{pet.name}」还没有疫苗记录。寄养要求入住当天疫苗仍在有效期内，"
        f"请先{tip}后再来预约"
    )


async def eligibility(db: AsyncSession, pet: Pet, check_in: date) -> dict:
    """寄养资格预检：一次返回「能不能订 + 不能订的原因 + 补救信息」。

    下单页选完宠物与日期就先调它，把拦截提前到提交之前；
    只在下单时才报错，用户会以为是功能坏了（V8.2 反馈的就是这个）。
    """
    ok, note = await _check_vaccine(db, pet, check_in)
    latest = await db.scalar(
        select(func.max(VaccineRecord.next_date)).where(
            VaccineRecord.pet_id == pet.id,
            VaccineRecord.record_type == "vaccine",
            VaccineRecord.next_date.is_not(None),
        )
    )
    _, weight_label = await _base_price_cents(db, pet)
    return {
        "ok": ok,
        "code": "ok" if ok else "vaccine",
        "message": note,
        "pet_id": pet.id,
        "pet_name": pet.name,
        "check_in": check_in.isoformat(),
        "vaccine_until": latest.isoformat() if latest else None,
        "weight_kg": float(pet.weight or 0),
        "weight_label": weight_label,
        "min_nights": await setting_service.get_int(db, "board_min_nights"),
    }


async def create_order(
    db: AsyncSession, user: User, payload: BoardingOrderCreate, request: Request | None = None
) -> BoardingOrder:
    """寄养下单主链路：疫苗硬门槛 → 日期与晚数校验 → 房态锁 + 重叠占用校验 →

        三重定价 → 落库（订单 + 照护计划 + 接送任务）→ 审计与站内信。
    """
    existed = None
    if payload.idempotent_key:
        existed = (
            await db.execute(select(BoardingOrder).where(BoardingOrder.idempotent_key == payload.idempotent_key))
        ).scalars().first()
    if existed is not None:
        return existed

    pet = await get_pet_or_404(db, payload.pet_id)
    if user.role == UserRole.CUSTOMER.value and pet.user_id != user.id:
        from app.utils.exceptions import PermissionError_

        raise PermissionError_("只能为自己的宠物预约寄养")

    if payload.check_out_date <= payload.check_in_date:
        raise BizError("离店日期必须晚于入住日期")
    if payload.check_in_date < date.today():
        raise BizError("入住日期不能早于今天")

    # 硬门槛：疫苗
    vaccine_ok, vaccine_note = await _check_vaccine(db, pet, payload.check_in_date)
    if not vaccine_ok:
        raise BizError(vaccine_note)

    # 条款确认（责任划分留证）
    if not payload.terms_confirmed:
        raise BizError("请先阅读并确认寄养条款与责任划分")

    room = await _lock_room_and_check(db, payload.room_id)
    await _check_room_capacity(db, room, payload.check_in_date, payload.check_out_date, pet)

    price = await quote(
        db, pet=pet, room=room, check_in=payload.check_in_date, check_out=payload.check_out_date,
        feeding_plan=payload.feeding_plan, dropoff_method=payload.dropoff_method,
        pickup_back_method=payload.pickup_back_method,
    )

    order = BoardingOrder(
        order_no=gen_order_no(prefix="BG"),
        user_id=pet.user_id,
        pet_id=pet.id,
        room_id=room.id,
        room_type=room.room_type,
        status=BoardingOrderStatus.PENDING.value,
        check_in_date=payload.check_in_date,
        check_out_date=payload.check_out_date,
        nights=price["nights"],
        feeding_plan=payload.feeding_plan,
        food_note=payload.food_note,
        shipping_method=payload.dropoff_method,  # 历史字段兼容
        dropoff_method=payload.dropoff_method,
        pickup_back_method=payload.pickup_back_method,
        shipping_address=payload.shipping_address,
        shipping_slot=payload.shipping_slot,
        shipping_fee_cents=price["shipping_fee_cents"],
        daily_fee_cents=price["daily_fee_cents"],
        subtotal_cents=price["subtotal_cents"],
        discount_percent=price["discount_percent"],
        extra_fee_cents=price["feeding_fee_cents"],
        total_cents=price["total_cents"],
        vaccine_ok=1,
        vaccine_note=vaccine_note,
        isolate_required=1 if (pet.skin_disease or "").strip() else 0,
        risk_level=None,
        emergency_contact=payload.emergency_contact,
        emergency_phone_encrypted=encrypt_text(payload.emergency_phone) if payload.emergency_phone else None,
        medical_authorized=1 if payload.medical_authorized else 0,
        terms_confirmed_at=now(),
        terms_ip=(request.client.host if request and request.client else None),
        idempotent_key=payload.idempotent_key,
        remark=payload.remark,
    )
    db.add(order)
    await db.flush()

    # 照护计划条目
    for idx, item in enumerate(payload.care_items or []):
        db.add(BoardingCarePlan(
            order_id=order.id, item_type=item.item_type, content=item.content,
            frequency=item.frequency, need_staff=1 if item.need_staff else 0, sort_no=idx,
        ))

    # 接送任务：到店接宠与离店送宠各自一条，互不影响
    if payload.dropoff_method == "pickup":
        db.add(BoardingPickupTask(
            order_id=order.id, task_type="pickup", status="pending",
            address=payload.shipping_address, slot_time=payload.shipping_slot,
            fee_cents=price["pickup_fee_cents"],
        ))
    if payload.pickup_back_method == "return":
        db.add(BoardingPickupTask(
            order_id=order.id, task_type="return", status="pending",
            address=payload.shipping_address, slot_time=payload.shipping_slot,
            fee_cents=price["return_fee_cents"],
        ))

    await message_service.create_message(
        db, user_id=order.user_id,
        title=f"寄养申请已提交：{order.order_no}",
        content=(f"{pet.name} 的寄养申请已提交（{payload.check_in_date} ~ {payload.check_out_date}，"
                 f"{price['nights']} 晚，"
                 f"{DROPOFF_METHOD_LABEL.get(payload.dropoff_method, '')} / "
                 f"{PICKUP_BACK_METHOD_LABEL.get(payload.pickup_back_method, '')}，"
                 f"预计 {price['total_cents'] / 100:.2f} 元），等待门店确认。"
                 f"{'（需隔离观察：有皮肤病史）' if order.isolate_required else ''}"),
        msg_type=MessageType.BOARDING_CREATED.value, biz_id=order.id,
    )
    await write_log(
        db, module="boarding", action="create", user_id=order.user_id, biz_id=order.id,
        after=_snapshot(order), request=request,
        detail=f"房型={room.room_no} 晚数={order.nights} 疫苗={vaccine_note}",
    )
    await db.commit()
    await db.refresh(order)
    logger.info("boarding_order_created",
                extra={"extra_fields": {"order_no": order.order_no, "nights": order.nights,
                                        "total_cents": order.total_cents}})
    return order


# ---------------------------------------------------------------- 查询
async def list_orders(
    db: AsyncSession, user: User, *, status: str | None = None, pet_id: int | None = None,
    page: int = 1, size: int = 10,
) -> tuple[list[tuple[BoardingOrder, Pet, User | None]], int]:
    """寄养分页列表：宠主收敛到本人，店员/店长可看全店，支持状态与宠物筛选。"""
    cond = []
    if user.role == UserRole.CUSTOMER.value:
        cond.append(BoardingOrder.user_id == user.id)
    if status:
        cond.append(BoardingOrder.status == status)
    if pet_id:
        cond.append(BoardingOrder.pet_id == pet_id)
    total = int(await db.scalar(select(func.count()).select_from(BoardingOrder).where(*cond)) or 0)
    rows = (
        await db.execute(
            select(BoardingOrder, Pet, User)
            .join(Pet, Pet.id == BoardingOrder.pet_id)
            .join(User, User.id == BoardingOrder.user_id)
            .where(*cond).order_by(BoardingOrder.id.desc())
            .offset((page - 1) * size).limit(size)
        )
    ).all()
    return [(r[0], r[1], r[2]) for r in rows], total


async def get_order(db: AsyncSession, order_id: int) -> BoardingOrder:
    """按 ID 取单，不存在抛 NotFoundError。"""
    order = (await db.execute(select(BoardingOrder).where(BoardingOrder.id == order_id))).scalars().first()
    if order is None:
        raise NotFoundError("寄养订单不存在")
    return order


async def get_order_for_user(db: AsyncSession, order_id: int, user: User) -> BoardingOrder:
    """按角色取单：宠主只能看自己的寄养单。"""
    order = await get_order(db, order_id)
    if user.role == UserRole.CUSTOMER.value and order.user_id != user.id:
        from app.utils.exceptions import PermissionError_

        raise PermissionError_("无权查看他人的寄养订单")
    return order


# ---------------------------------------------------------------- 状态流转
async def change_status(
    db: AsyncSession, order: BoardingOrder, target: str, operator: User,
    reason: str | None = None, request: Request | None = None, **extra,
) -> BoardingOrder:
    """状态流转（与预约状态机同一套纪律：非法流转 409、终止类必填原因、全量审计）。"""
    if target not in BOARDING_STATUS_LABEL:
        raise BizError(f"未知的寄养状态：{target}")
    allowed = BOARDING_TRANSITIONS.get(order.status, set())
    if target not in allowed:
        raise StateMachineError(
            f"寄养单当前状态「{BOARDING_STATUS_LABEL.get(order.status, order.status)}」"
            f"不允许变更为「{BOARDING_STATUS_LABEL[target]}」"
        )
    if target in BOARDING_REASON_REQUIRED_STATUS and not (reason or "").strip():
        raise BizError(f"变更为「{BOARDING_STATUS_LABEL[target]}」必须填写原因")

    before = _snapshot(order)
    order.status = target
    if target == BoardingOrderStatus.CHECKED_IN.value:
        order.checkin_at = now()
    if target in (BoardingOrderStatus.COMPLETED.value, BoardingOrderStatus.EARLY_PICKUP.value):
        order.checkout_at = now()
    if target in (BoardingOrderStatus.CANCELLED.value, BoardingOrderStatus.NO_SHOW.value):
        order.cancel_reason = reason
    if target in (BoardingOrderStatus.EARLY_PICKUP.value, BoardingOrderStatus.MEDICAL_TERMINATED.value,
                  BoardingOrderStatus.OVERDUE_UNPICKED.value):
        order.terminate_reason = reason

    for key, value in extra.items():
        if hasattr(order, key) and value is not None:
            setattr(order, key, value)

    # 提前接回 / 健康异常终止：按实际入住天数结算，输出结算说明（退款线下处理）
    if target in (BoardingOrderStatus.EARLY_PICKUP.value, BoardingOrderStatus.MEDICAL_TERMINATED.value):
        actual_days = max((date.today() - order.check_in_date).days, 1) if order.checkin_at else order.nights
        actual_days = min(actual_days, order.nights)
        order.settle_note = (
            f"按实际 {actual_days} 晚结算（原 {order.nights} 晚），差额由门店线下退还/补收"
        )

    # 房态联动：入住占用，终态释放并转清洁中
    room = (await db.execute(select(BoardingRoom).where(BoardingRoom.id == order.room_id))).scalars().first()
    if room is not None:
        if target == BoardingOrderStatus.CHECKED_IN.value:
            room.status = BoardingRoomStatus.OCCUPIED.value
        elif target in (BoardingOrderStatus.COMPLETED.value, BoardingOrderStatus.EARLY_PICKUP.value,
                        BoardingOrderStatus.OVERDUE_UNPICKED.value,
                        BoardingOrderStatus.MEDICAL_TERMINATED.value):
            room.status = BoardingRoomStatus.CLEANING.value  # 退房后消杀，确认清洁后方可转空闲
        elif target in (BoardingOrderStatus.CANCELLED.value, BoardingOrderStatus.NO_SHOW.value):
            room.status = BoardingRoomStatus.IDLE.value

    await message_service.create_message(
        db, user_id=order.user_id,
        title=f"寄养状态更新：{BOARDING_STATUS_LABEL[target]}",
        content=(f"寄养单 {order.order_no} 状态变更为「{BOARDING_STATUS_LABEL[target]}」。"
                 + (f"原因：{reason}" if reason else "")
                 + (f"　{order.settle_note}" if order.settle_note else "")),
        msg_type=MessageType.BOARDING_STATUS.value, biz_id=order.id,
    )
    await write_log(
        db, module="boarding", action=f"status_{target}", user_id=operator.id,
        staff_id=operator.id if operator.role != UserRole.CUSTOMER.value else None,
        biz_id=order.id, before=before, after=_snapshot(order), request=request, detail=reason,
    )
    await db.commit()
    await db.refresh(order)
    return order


async def extend_order(
    db: AsyncSession, order: BoardingOrder, new_check_out: date, operator: User,
    request: Request | None = None,
) -> BoardingOrder:
    """延期：重新校验房态（冲突则拒绝），并按新时长重算费用。"""
    # 待确认也允许延期：宠主刚下单就改主意是最常见的场景；延期同样要重新校验房态并重算费用，
    # 因此不放开这个口子只会把需求赶到线下。
    if order.status not in (BoardingOrderStatus.PENDING.value, BoardingOrderStatus.CONFIRMED.value,
                            BoardingOrderStatus.WAITING_CHECKIN.value,
                            BoardingOrderStatus.CHECKED_IN.value, BoardingOrderStatus.WAITING_PICKUP.value):
        raise StateMachineError("当前状态不支持延期")
    if new_check_out <= order.check_out_date:
        raise BizError("新的离店日期必须晚于原离店日期")

    pet = await get_pet_or_404(db, order.pet_id)
    await _lock_room_and_check(db, order.room_id)
    # 只校验新增日期段的冲突（原区间已被本单占用，需排除自身）
    await _check_room_capacity(db, await _load_room(db, order.room_id),
                               order.check_out_date, new_check_out, pet, exclude_order_id=order.id)

    before = _snapshot(order)
    order.check_out_date = new_check_out
    order.nights = (new_check_out - order.check_in_date).days
    order.extend_times += 1
    room = await _load_room(db, order.room_id)
    price = await quote(db, pet=pet, room=room, check_in=order.check_in_date,
                        check_out=new_check_out, feeding_plan=order.feeding_plan,
                        dropoff_method=order.dropoff_method,
                        pickup_back_method=order.pickup_back_method)
    order.daily_fee_cents = price["daily_fee_cents"]
    order.subtotal_cents = price["subtotal_cents"]
    order.discount_percent = price["discount_percent"]
    order.extra_fee_cents = price["feeding_fee_cents"]
    order.total_cents = price["total_cents"] + order.shipping_fee_cents

    await message_service.create_message(
        db, user_id=order.user_id, title=f"寄养已延期：{order.order_no}",
        content=f"新的离店日期为 {new_check_out}，共 {order.nights} 晚，应付总额已重算。",
        msg_type=MessageType.BOARDING_STATUS.value, biz_id=order.id,
    )
    await write_log(db, module="boarding", action="extend", user_id=operator.id, biz_id=order.id,
                    before=before, after=_snapshot(order), request=request,
                    detail=f"{before['check_out_date']} → {new_check_out}")
    await db.commit()
    await db.refresh(order)
    return order


async def _load_room(db: AsyncSession, room_id: int) -> BoardingRoom:
    room = (await db.execute(select(BoardingRoom).where(BoardingRoom.id == room_id))).scalars().first()
    if room is None:
        raise NotFoundError("宠舍不存在")
    return room


# ---------------------------------------------------------------- 照护闭环
async def add_care_log(
    db: AsyncSession, order: BoardingOrder, operator: User, payload, request: Request | None = None
) -> BoardingCareLog:
    """提交每日照护日志；异常记录立即单独推送宠主 + 提示店长关注。"""
    if order.status not in (BoardingOrderStatus.CHECKED_IN.value, BoardingOrderStatus.WAITING_PICKUP.value):
        raise StateMachineError("仅「寄养中 / 待接回」的订单可以填写照护日志")

    log = BoardingCareLog(
        order_id=order.id, log_date=payload.log_date or date.today(),
        eating=payload.eating, drinking=payload.drinking, stool=payload.stool,
        spirit=payload.spirit, activity=payload.activity,
        abnormal=1 if payload.abnormal else 0, abnormal_note=payload.abnormal_note,
        photos=",".join(payload.photos or []), sop_checked=",".join(payload.sop_checked or []),
        staff_id=operator.id,
    )
    db.add(log)
    await db.flush()

    if payload.abnormal:
        # 异常：立即推送（不合并到日报）
        await message_service.create_message(
            db, user_id=order.user_id,
            title=f"{order.order_no} 宠物状态异常提醒",
            content=(f"店员记录到异常：{payload.abnormal_note or '详见照护日志'}。"
                     "门店已按流程处理并持续观察，如有需要会第一时间联系您。"),
            msg_type=MessageType.BOARDING_ABNORMAL.value, biz_id=order.id,
        )
        logger.warning("boarding_abnormal",
                       extra={"extra_fields": {"order_no": order.order_no,
                                               "note": (payload.abnormal_note or "")[:80]}})
    else:
        await message_service.create_message(
            db, user_id=order.user_id,
            title=f"{order.order_no} 今日照护日报",
            content=(f"进食：{payload.eating or '正常'}；饮水：{payload.drinking or '正常'}；"
                     f"精神：{payload.spirit or '正常'}；活动：{payload.activity or '正常'}。"
                     f"{'（含照片）' if payload.photos else '（今日暂无照片）'}"),
            msg_type=MessageType.BOARDING_LOG.value, biz_id=order.id,
        )

    await write_log(db, module="boarding", action="care_log", user_id=operator.id, staff_id=operator.id,
                    biz_id=order.id, after={"abnormal": log.abnormal, "log_date": str(log.log_date)},
                    request=request, detail=payload.abnormal_note)
    await db.commit()
    await db.refresh(log)
    return log


async def list_care_logs(db: AsyncSession, order_id: int) -> list[BoardingCareLog]:
    """某寄养单的每日照护日志（按日期倒序）。"""
    return list((
        await db.execute(
            select(BoardingCareLog).where(BoardingCareLog.order_id == order_id)
            .order_by(BoardingCareLog.log_date.desc(), BoardingCareLog.id.desc())
        )
    ).scalars().all())


async def list_care_plans(db: AsyncSession, order_id: int) -> list[BoardingCarePlan]:
    """某寄养单的照护计划条目（用药/喂食/遛放/禁忌）。"""
    return list((
        await db.execute(
            select(BoardingCarePlan).where(BoardingCarePlan.order_id == order_id)
            .order_by(BoardingCarePlan.sort_no, BoardingCarePlan.id)
        )
    ).scalars().all())


async def list_pickup_tasks(
    db: AsyncSession, user: User, *, status: str | None = None
) -> list[tuple[BoardingPickupTask, BoardingOrder]]:
    """接送任务列表，返回 (任务, 订单) 元组；宠主只能看到自己的。"""
    cond = []
    if status:
        cond.append(BoardingPickupTask.status == status)
    if user.role == UserRole.CUSTOMER.value:
        cond.append(BoardingOrder.user_id == user.id)
    rows = (
        await db.execute(
            select(BoardingPickupTask, BoardingOrder)
            .join(BoardingOrder, BoardingOrder.id == BoardingPickupTask.order_id)
            .where(*cond).order_by(BoardingPickupTask.id.desc()).limit(50)
        )
    ).all()
    return [(r[0], r[1]) for r in rows]


PICKUP_FLOW = {
    "pending": "departed",
    "departed": "picked",
    "picked": "arrived",
}


async def advance_pickup(
    db: AsyncSession, task_id: int, operator: User, target: str | None = None,
    sign_off_by: str | None = None, request: Request | None = None,
) -> BoardingPickupTask:
    """推进接送任务状态（不传 target 则按流程自动进入下一状态）。"""
    task = (
        await db.execute(select(BoardingPickupTask).where(BoardingPickupTask.id == task_id))
    ).scalars().first()
    if task is None:
        raise NotFoundError("接送任务不存在")

    nxt = target or PICKUP_FLOW.get(task.status)
    if nxt is None or nxt not in PICKUP_TASK_STATUS_LABEL:
        raise StateMachineError(f"接送任务当前状态「{PICKUP_TASK_STATUS_LABEL.get(task.status)}」无法继续推进")
    if target and PICKUP_FLOW.get(task.status) != target:
        raise StateMachineError(
            f"接送任务只能从「{PICKUP_TASK_STATUS_LABEL.get(task.status)}」推进到"
            f"「{PICKUP_TASK_STATUS_LABEL.get(PICKUP_FLOW.get(task.status, ''), '无')}」"
        )

    task.status = nxt
    if nxt == "departed":
        task.departed_at = now()
    elif nxt == "picked":
        task.picked_at = now()
    elif nxt == "arrived":
        task.arrived_at = now()
        task.sign_off_by = sign_off_by
    await write_log(db, module="boarding", action=f"pickup_{nxt}", user_id=operator.id,
                    staff_id=operator.id, biz_id=task.order_id, request=request,
                    detail=f"task={task.id} type={task.task_type}")
    await db.commit()
    await db.refresh(task)
    return task


# ---------------------------------------------------------------- 店长看板
async def dashboard(db: AsyncSession, start: date, end: date) -> dict:
    """寄养经营看板：入住率、客单价、收入、房型占比、异常发生率。"""
    rooms = (await db.execute(select(BoardingRoom))).scalars().all()
    total_rooms = len(rooms)

    orders = (
        await db.execute(
            select(BoardingOrder).where(
                BoardingOrder.check_in_date >= start,
                BoardingOrder.check_in_date <= end,
            )
        )
    ).scalars().all()

    valid = [o for o in orders if o.status != BoardingOrderStatus.CANCELLED.value]
    revenue = sum(o.total_cents for o in valid) / 100
    avg_days = round(sum(o.nights for o in valid) / len(valid), 1) if valid else 0
    avg_price = round(revenue / len(valid), 2) if valid else 0

    type_stat: dict[str, dict] = {}
    for order in valid:
        item = type_stat.setdefault(order.room_type, {"count": 0, "revenue": 0.0})
        item["count"] += 1
        item["revenue"] = round(item["revenue"] + order.total_cents / 100, 2)

    status_stat: dict[str, int] = {}
    for order in orders:
        status_stat[order.status] = status_stat.get(order.status, 0) + 1

    occupied_now = int(await db.scalar(
        select(func.count()).select_from(BoardingOrder).where(
            BoardingOrder.status == BoardingOrderStatus.CHECKED_IN.value
        )
    ) or 0)
    logs = (
        await db.execute(
            select(BoardingCareLog).where(BoardingCareLog.log_date >= start, BoardingCareLog.log_date <= end)
        )
    ).scalars().all()
    abnormal_count = sum(1 for lg in logs if lg.abnormal)

    return {
        "range_start": str(start), "range_end": str(end),
        "orders": len(orders),
        "revenue": round(revenue, 2),
        "avg_nights": avg_days,
        "avg_price": avg_price,
        "total_rooms": total_rooms,
        "occupied_now": occupied_now,
        "occupancy_rate": round(occupied_now / total_rooms * 100, 1) if total_rooms else 0.0,
        "room_type_stat": [
            {"room_type": k, "label": ROOM_TYPE_LABEL.get(k, k), **v} for k, v in type_stat.items()
        ],
        "status_stat": [
            {"status": k, "label": BOARDING_STATUS_LABEL.get(k, k), "count": v}
            for k, v in status_stat.items()
        ],
        "care_logs": len(logs),
        "abnormal_logs": abnormal_count,
        "abnormal_rate": round(abnormal_count / len(logs) * 100, 1) if logs else 0.0,
        "room_status_stat": {
            BOARDING_ROOM_STATUS_LABEL[k]: v for k, v in _room_status_counter(rooms).items()
        },
    }


def _room_status_counter(rooms: list[BoardingRoom]) -> dict[str, int]:
    counter: dict[str, int] = {}
    for room in rooms:
        counter[room.status] = counter.get(room.status, 0) + 1
    return counter


# ---------------------------------------------------------------- 序列化
def _snapshot(order: BoardingOrder) -> dict:
    return {
        "order_no": order.order_no, "status": order.status, "room_id": order.room_id,
        "check_in_date": str(order.check_in_date), "check_out_date": str(order.check_out_date),
        "nights": order.nights, "total_cents": order.total_cents,
    }


def room_to_out(room: BoardingRoom) -> dict:
    """房型序列化：补房态中文名与预估日费。"""
    return {
        "id": room.id, "room_no": room.room_no, "room_type": room.room_type,
        "room_type_label": ROOM_TYPE_LABEL.get(room.room_type, room.room_type),
        "name": room.name, "species_limit": room.species_limit, "weight_limit": room.weight_limit,
        "ratio_percent": room.ratio_percent, "capacity": room.capacity,
        "status": room.status, "status_label": BOARDING_ROOM_STATUS_LABEL.get(room.status, room.status),
        "facilities": [f for f in (room.facilities or "").split(",") if f],
        "remark": room.remark,
    }


def order_to_out(
    order: BoardingOrder, pet: Pet | None = None, owner: User | None = None, room: BoardingRoom | None = None
) -> dict:
    """寄养订单序列化：金额由「分」转「元」，补状态、接送、房型等中文标签。"""
    from app.utils.crypto import decrypt_text

    return {
        "id": order.id, "order_no": order.order_no,
        "user_id": order.user_id, "pet_id": order.pet_id,
        "pet_name": pet.name if pet else None,
        "pet_species": pet.species if pet else None,
        "owner_name": owner.real_name if owner else None,
        "owner_phone": mask_phone(decrypt_text(owner.phone_encrypted)) if owner else None,
        "room_id": order.room_id, "room_no": room.room_no if room else None,
        "room_type": order.room_type, "room_type_label": ROOM_TYPE_LABEL.get(order.room_type, order.room_type),
        "status": order.status, "status_label": BOARDING_STATUS_LABEL.get(order.status, order.status),
        "check_in_date": order.check_in_date, "check_out_date": order.check_out_date,
        "nights": order.nights, "extend_times": order.extend_times,
        "feeding_plan": order.feeding_plan,
        "feeding_plan_label": FEEDING_PLAN_LABEL.get(order.feeding_plan, order.feeding_plan),
        "food_note": order.food_note,
        "dropoff_method": order.dropoff_method,
        "dropoff_method_label": DROPOFF_METHOD_LABEL.get(order.dropoff_method, order.dropoff_method),
        "pickup_back_method": order.pickup_back_method,
        "pickup_back_method_label": PICKUP_BACK_METHOD_LABEL.get(order.pickup_back_method, order.pickup_back_method),
        "shipping_method": order.shipping_method,
        "shipping_method_label": SHIPPING_METHOD_LABEL.get(order.shipping_method, order.shipping_method),
        "shipping_address": order.shipping_address, "shipping_slot": order.shipping_slot,
        # 金额：分与元都给，前端展示直接用 amount 字段
        "daily_fee": order.daily_fee_cents / 100,
        "subtotal": order.subtotal_cents / 100,
        "discount_percent": order.discount_percent,
        "extra_fee": order.extra_fee_cents / 100,
        "shipping_fee": order.shipping_fee_cents / 100,
        "total_amount": order.total_cents / 100,
        "settle_note": order.settle_note,
        "vaccine_ok": order.vaccine_ok, "vaccine_note": order.vaccine_note,
        "isolate_required": order.isolate_required, "risk_level": order.risk_level,
        "emergency_contact": order.emergency_contact,
        "emergency_phone": mask_phone(decrypt_text(order.emergency_phone_encrypted))
        if order.emergency_phone_encrypted else None,
        "medical_authorized": order.medical_authorized,
        "terms_confirmed_at": order.terms_confirmed_at,
        "staff_id": order.staff_id,
        "checkin_at": order.checkin_at, "checkout_at": order.checkout_at,
        "checkin_note": order.checkin_note, "checkout_note": order.checkout_note,
        "cancel_reason": order.cancel_reason, "terminate_reason": order.terminate_reason,
        "remark": order.remark, "created_at": order.created_at,
    }


def care_log_to_out(log: BoardingCareLog) -> dict:
    """照护日志序列化：图片与 SOP 勾选项由逗号串转数组。"""
    return {
        "id": log.id, "log_date": log.log_date,
        "eating": log.eating, "drinking": log.drinking, "stool": log.stool,
        "spirit": log.spirit, "activity": log.activity,
        "abnormal": log.abnormal, "abnormal_note": log.abnormal_note,
        "photos": [p for p in (log.photos or "").split(",") if p],
        "sop_checked": [s for s in (log.sop_checked or "").split(",") if s],
        "staff_id": log.staff_id, "created_at": log.created_at,
    }


def care_plan_to_out(plan: BoardingCarePlan) -> dict:
    """照护计划序列化：条目类型转中文标签。"""
    return {
        "id": plan.id, "item_type": plan.item_type, "content": plan.content,
        "frequency": plan.frequency, "need_staff": plan.need_staff,
    }


def pickup_task_to_out(task: BoardingPickupTask, order: BoardingOrder | None = None) -> dict:
    """接送任务序列化：补单号与类型中文名。"""
    return {
        "id": task.id, "order_id": task.order_id,
        "order_no": order.order_no if order else None,
        "task_type": task.task_type,
        "task_type_label": "上门接宠" if task.task_type == "pickup" else "送宠到家",
        "status": task.status, "status_label": PICKUP_TASK_STATUS_LABEL.get(task.status, task.status),
        "address": task.address, "slot_time": task.slot_time, "staff_id": task.staff_id,
        "fee": task.fee_cents / 100,
        "departed_at": task.departed_at, "picked_at": task.picked_at, "arrived_at": task.arrived_at,
        "sign_off_by": task.sign_off_by, "remark": task.remark,
    }


# ---------------------------------------------------------------- 种子房型
SEED_ROOMS: list[dict] = [
    {"room_no": "A101", "room_type": "standard", "name": "标准单间 A101",
     "species_limit": "all", "weight_limit": 10, "ratio_percent": 100, "capacity": 1,
     "facilities": "独立通风,24h监控"},
    {"room_no": "A102", "room_type": "standard", "name": "标准单间 A102",
     "species_limit": "all", "weight_limit": 10, "ratio_percent": 100, "capacity": 1,
     "facilities": "独立通风,24h监控"},
    {"room_no": "B201", "room_type": "garden", "name": "花园景房 B201",
     "species_limit": "dog", "weight_limit": 25, "ratio_percent": 120, "capacity": 1,
     "facilities": "户外活动区,恒温"},
    {"room_no": "B202", "room_type": "garden", "name": "花园景房 B202",
     "species_limit": "dog", "weight_limit": 25, "ratio_percent": 120, "capacity": 1,
     "facilities": "户外活动区,恒温"},
    {"room_no": "C301", "room_type": "sunny", "name": "阳光房 C301",
     "species_limit": "cat", "weight_limit": 8, "ratio_percent": 130, "capacity": 1,
     "facilities": "观景窗,猫爬架"},
    {"room_no": "V901", "room_type": "vip", "name": "VIP 套房 V901",
     "species_limit": "all", "weight_limit": 40, "ratio_percent": 200, "capacity": 1,
     "facilities": "独立小院,专人看护,24h监控"},
]


async def seed_rooms(db: AsyncSession) -> int:
    """灌入种子房型（幂等：按房号判重）。"""
    exist = {r for r in (await db.execute(select(BoardingRoom.room_no))).scalars().all()}
    added = 0
    for item in SEED_ROOMS:
        if item["room_no"] in exist:
            continue
        db.add(BoardingRoom(**item))
        added += 1
    if added:
        await db.flush()
    return added


# ---------------------------------------------------------------- 提前接回（宠主申请 → 门店审核）
EARLY_PICKUP_STATUS_LABEL = {"pending": "待审核", "approved": "已通过", "rejected": "已驳回"}


def early_pickup_to_out(req: BoardingEarlyPickup, order: BoardingOrder | None = None,
                        pet: Pet | None = None) -> dict:
    return {
        "id": req.id,
        "order_id": req.order_id,
        "order_no": order.order_no if order else None,
        "pet_name": pet.name if pet else None,
        "expect_pickup_date": req.expect_pickup_date,
        "reason": req.reason,
        "status": req.status,
        "status_label": EARLY_PICKUP_STATUS_LABEL.get(req.status, req.status),
        "review_note": req.review_note,
        "reviewed_by": req.reviewed_by,
        "reviewed_at": req.reviewed_at,
        "created_at": req.created_at,
    }


async def request_early_pickup(
    db: AsyncSession, order: BoardingOrder, user: User, expect_date: date, reason: str | None
) -> BoardingEarlyPickup:
    """宠主提交提前接回申请（不改订单状态，等门店审核）。"""
    allowed = {BoardingOrderStatus.CHECKED_IN.value, BoardingOrderStatus.WAITING_PICKUP.value}
    if order.status not in allowed:
        raise BizError("只有「寄养中 / 待接回」的订单可以申请提前接回")
    if expect_date < date.today():
        raise BizError("接回日期不能早于今天")
    if expect_date >= order.check_out_date:
        raise BizError(f"提前接回要早于原定离店日 {order.check_out_date}；如需改期请用「延期」")
    pending = await db.scalar(
        select(func.count()).select_from(BoardingEarlyPickup).where(
            BoardingEarlyPickup.order_id == order.id,
            BoardingEarlyPickup.status == "pending",
        )
    )
    if pending:
        raise BizError("已经有一条待审核的提前接回申请，等门店处理即可")

    req = BoardingEarlyPickup(
        order_id=order.id, user_id=user.id, expect_pickup_date=expect_date,
        reason=(reason or "").strip() or None, status="pending",
    )
    db.add(req)
    await db.flush()
    await message_service.create_message(
        db, user_id=user.id,
        title=f"提前接回申请已提交（{order.order_no}）",
        content=f"期望 {expect_date} 接回，门店审核后会通知你。",
        msg_type="boarding", biz_id=order.id,
    )
    await db.commit()
    return req


async def list_early_pickups(
    db: AsyncSession, status: str | None = None, user_id: int | None = None
) -> list[dict]:
    """提前接回申请列表（店员/店长看全部；宠主只看自己的）。"""
    cond = []
    if status:
        cond.append(BoardingEarlyPickup.status == status)
    if user_id:
        cond.append(BoardingEarlyPickup.user_id == user_id)
    reqs = (await db.execute(
        select(BoardingEarlyPickup).where(*cond).order_by(BoardingEarlyPickup.id.desc()).limit(50)
    )).scalars().all()
    if not reqs:
        return []
    order_ids = {r.order_id for r in reqs}
    orders = {o.id: o for o in (await db.execute(
        select(BoardingOrder).where(BoardingOrder.id.in_(order_ids))
    )).scalars().all()}
    pets = {p.id: p for p in (await db.execute(
        select(Pet).where(Pet.id.in_([o.pet_id for o in orders.values()]))
    )).scalars().all()} if orders else {}
    return [
        early_pickup_to_out(r, orders.get(r.order_id),
                            pets.get(orders[r.order_id].pet_id) if r.order_id in orders else None)
        for r in reqs
    ]


async def latest_early_pickup(db: AsyncSession, order_id: int) -> dict | None:
    """订单详情里展示最近一条申请（待审核 / 已通过 / 已驳回）。"""
    req = (await db.execute(
        select(BoardingEarlyPickup).where(BoardingEarlyPickup.order_id == order_id)
        .order_by(BoardingEarlyPickup.id.desc())
    )).scalars().first()
    return early_pickup_to_out(req) if req else None


async def review_early_pickup(
    db: AsyncSession, req: BoardingEarlyPickup, approve: bool, note: str | None,
    operator: User, request: Request | None = None,
) -> dict:
    """门店审核：通过时执行 early_pickup 状态流转（走状态机 + 归档 + 释放房态）。"""
    if req.status != "pending":
        raise BizError("这条申请已经处理过了")
    order = (await db.execute(
        select(BoardingOrder).where(BoardingOrder.id == req.order_id)
    )).scalars().first()
    if order is None:
        raise NotFoundError("寄养单不存在")

    text = (note or "").strip() or None
    if approve:
        reason = f"宠主申请提前接回（期望 {req.expect_pickup_date}）" + (f"：{text}" if text else "")
        # change_status 内部会 commit（审计 + 归档洗护记录 + 释放房态）
        await change_status(db, order, BoardingOrderStatus.EARLY_PICKUP.value,
                            operator, reason=reason, request=request)
        req.status = "approved"
    else:
        req.status = "rejected"
        await message_service.create_message(
            db, user_id=req.user_id,
            title=f"提前接回申请未通过（{order.order_no}）",
            content=text or "门店未通过该申请，可直接联系店员了解原因。",
            msg_type="boarding", biz_id=order.id,
        )
    req.review_note = text
    req.reviewed_by = operator.id
    req.reviewed_at = now()
    await db.commit()
    return early_pickup_to_out(req, order)
