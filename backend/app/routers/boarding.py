"""宠物寄养接口（V7.1）。

权限口径：
- 房型浏览 / 费用预估 / 下单 / 查看自己的订单 / 取消 / 延期 → 登录用户（宠主自助）
- 确认、入住、退房、照护日志、接送任务、异常终止 → 店员 / 店长
- 房型维护、房态调整、经营看板 → 店长
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import BOARDING_STATUS_LABEL, UserRole
from app.database import get_db
from app.deps.auth import get_current_user, get_manager_user, get_staff_user
from app.models import BoardingEarlyPickup, BoardingOrder, BoardingRoom, User
from app.schemas.boarding import (
    BoardingExtendIn,
    BoardingOrderCreate,
    BoardingQuoteIn,
    BoardingRoomIn,
    BoardingRoomStatusIn,
    BoardingStatusIn,
    CareLogIn,
    EarlyPickupIn,
    EarlyPickupReviewIn,
)
from app.schemas.common import ok
from app.services import boarding_service, setting_service
from app.services.pet_service import assert_can_access, get_pet_or_404
from app.utils.exceptions import BizError, NotFoundError


router = APIRouter(prefix="/boarding", tags=["宠物寄养"])


def _guard_owner(order, user: User) -> None:
    """宠主只能操作自己的寄养单。"""
    from app.constants import UserRole
    from app.utils.exceptions import PermissionError_

    if user.role == UserRole.CUSTOMER.value and order.user_id != user.id:
        raise PermissionError_("无权操作他人的寄养订单")


# ---------------------------------------------------------------- 房型与报价
@router.get("/eligibility", summary="寄养资格预检（疫苗 / 体重，下单前先问一次）")
async def eligibility(
    pet_id: int = Query(..., gt=0),
    check_in: date = Query(..., description="入住日期"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """寄养资格预检（疫苗 / 体重，下单前先问一次）。

    返回 ok=false 时带上「哪只宠物、疫苗有效期到哪天、怎么补录」，
    前端据此提示，而不是等用户填完整张表单再报错。
    """
    pet = await get_pet_or_404(db, pet_id)
    assert_can_access(pet, user)
    return ok(await boarding_service.eligibility(db, pet, check_in))


@router.get("/rooms", summary="房型列表（可选带宠物与日期，返回可订状态与预估日费）")
async def list_rooms(
    pet_id: int | None = Query(None, description="传入宠物后按物种 / 体重过滤并给出预估日费"),
    check_in: date | None = Query(None),
    check_out: date | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """房型列表（可选带宠物与日期，返回可订状态与预估日费）。"""
    pet = await get_pet_or_404(db, pet_id) if pet_id else None
    return ok(await boarding_service.list_rooms(db, pet=pet, check_in=check_in, check_out=check_out))


@router.get("/meta", summary="寄养字典与规则（状态 / 喂食 / 接送 / 房态 / 定价参数）")
async def meta(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """寄养字典与规则（状态 / 喂食 / 接送 / 房态 / 定价参数）。"""
    from app.constants import (
        BOARDING_ROOM_STATUS_LABEL,
        FEEDING_PLAN_LABEL,
        PICKUP_TASK_STATUS_LABEL,
        DROPOFF_METHOD_LABEL,
        PICKUP_BACK_METHOD_LABEL,
        SHIPPING_METHOD_LABEL,
    )

    return ok({
        "order_status": BOARDING_STATUS_LABEL,
        "room_type": boarding_service.ROOM_TYPE_LABEL,
        "room_status": BOARDING_ROOM_STATUS_LABEL,
        "feeding_plan": FEEDING_PLAN_LABEL,
        "shipping_method": SHIPPING_METHOD_LABEL,
        "dropoff_method": DROPOFF_METHOD_LABEL,
        "pickup_back_method": PICKUP_BACK_METHOD_LABEL,
        "pickup_status": PICKUP_TASK_STATUS_LABEL,
        "care_item_types": {"medication": "用药", "feeding": "喂食", "walk": "遛放", "taboo": "禁忌"},
        # 定价与规则全部来自门店配置（店长可调），前端据此展示与校验
        "rules": {
            "min_nights": await setting_service.get_int(db, "board_min_nights"),
            "long_stay_days": await setting_service.get_int(db, "board_long_stay_days"),
            "long_stay_percent": await setting_service.get_int(db, "board_long_stay_percent"),
            "holiday_percent": await setting_service.get_int(db, "board_holiday_percent"),
            "pickup_fee": await setting_service.get_int(db, "board_pickup_fee"),
            "return_fee": await setting_service.get_int(db, "board_return_fee"),
            "premium_fee": await setting_service.get_int(db, "board_premium_fee"),
            "prescription_fee": await setting_service.get_int(db, "board_prescription_fee"),
        },
    })


@router.get("/quote", summary="费用预估（不落库）")
async def quote(
    pet_id: int = Query(...),
    room_id: int = Query(...),
    check_in_date: date = Query(...),
    check_out_date: date = Query(...),
    feeding_plan: str = Query("self"),
    dropoff_method: str = Query("self", description="送宠到店：self 自行送到 / pickup 上门接宠"),
    pickup_back_method: str = Query("self", description="离店接宠：self 自行接取 / return 送宠到家"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """费用预估（不落库）。"""
    pet = await get_pet_or_404(db, pet_id)
    room = await boarding_service._load_room(db, room_id)
    return ok(await boarding_service.quote(
        db, pet=pet, room=room, check_in=check_in_date, check_out=check_out_date,
        feeding_plan=feeding_plan, dropoff_method=dropoff_method,
        pickup_back_method=pickup_back_method,
    ))


# ---------------------------------------------------------------- 订单
@router.post("/orders", summary="提交寄养申请（疫苗完整为硬门槛）")
async def create_order(
    payload: BoardingOrderCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提交寄养申请（疫苗完整为硬门槛）。"""
    order = await boarding_service.create_order(db, user, payload, request)
    room = await boarding_service._load_room(db, order.room_id)
    pet = await get_pet_or_404(db, order.pet_id)
    return ok(boarding_service.order_to_out(order, pet=pet, owner=user, room=room), "寄养申请已提交")


@router.get("/orders", summary="寄养订单列表（宠主仅自己；店员 / 店长全部）")
async def list_orders(
    status: str | None = Query(None),
    pet_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """寄养订单列表（宠主仅自己；店员 / 店长全部）。"""
    rows, total = await boarding_service.list_orders(
        db, user, status=status, pet_id=pet_id, page=page, size=size
    )
    rooms = {
        r.id: r for r in (await db.execute(select(BoardingRoom))).scalars().all()
    }
    return ok({
        "items": [
            boarding_service.order_to_out(o, pet=p, owner=ow, room=rooms.get(o.room_id))
            for o, p, ow in rows
        ],
        "total": total, "page": page, "size": size,
    })


@router.get("/orders/{order_id}", summary="寄养订单详情（含照护计划与照护日志）")
async def order_detail(
    order_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """寄养订单详情（含照护计划与照护日志）。"""
    order = await boarding_service.get_order_for_user(db, order_id, user)
    pet = await get_pet_or_404(db, order.pet_id)
    room = await boarding_service._load_room(db, order.room_id)
    owner = (await db.execute(select(User).where(User.id == order.user_id))).scalars().first()
    data = boarding_service.order_to_out(order, pet=pet, owner=owner, room=room)
    # 提前接回申请（宠主发起、门店审核）：详情页要能显示当前进度
    data["early_pickup"] = await boarding_service.latest_early_pickup(db, order.id)
    data["care_plans"] = [
        boarding_service.care_plan_to_out(p) for p in await boarding_service.list_care_plans(db, order.id)
    ]
    data["care_logs"] = [
        boarding_service.care_log_to_out(lg) for lg in await boarding_service.list_care_logs(db, order.id)
    ]
    tasks = await boarding_service.list_pickup_tasks(db, user)
    data["pickup_tasks"] = [
        boarding_service.pickup_task_to_out(t, o) for t, o in tasks if t.order_id == order.id
    ]
    return ok(data)


@router.post("/orders/{order_id}/cancel", summary="取消寄养申请（仅待确认）")
async def cancel_order(
    order_id: int,
    payload: BoardingStatusIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消寄养申请（仅待确认）。"""
    order = await boarding_service.get_order_for_user(db, order_id, user)
    _guard_owner(order, user)
    updated = await boarding_service.change_status(
        db, order, "cancelled", user,
        reason=payload.reason or "宠主取消", request=request,
    )
    return ok({"id": updated.id, "status": updated.status}, "寄养申请已取消")


@router.post("/orders/{order_id}/extend", summary="寄养延期（重新校验房态并重算费用）")
async def extend_order(
    order_id: int,
    payload: BoardingExtendIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """寄养延期（重新校验房态并重算费用）。"""
    order = await boarding_service.get_order_for_user(db, order_id, user)
    _guard_owner(order, user)
    updated = await boarding_service.extend_order(db, order, payload.check_out_date, user, request)
    pet = await get_pet_or_404(db, updated.pet_id)
    room = await boarding_service._load_room(db, updated.room_id)
    return ok(boarding_service.order_to_out(updated, pet=pet, owner=user, room=room), "已延期")


@router.post("/orders/{order_id}/status", summary="寄养状态流转（店员 / 店长，终止类必填原因）")
async def change_status(
    order_id: int,
    payload: BoardingStatusIn,
    request: Request,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """寄养状态流转（店员 / 店长，终止类必填原因）。"""
    order = await boarding_service.get_order(db, order_id)
    extra = {}
    if payload.checkin_note:
        extra["checkin_note"] = payload.checkin_note
    if payload.checkout_note:
        extra["checkout_note"] = payload.checkout_note
    if not order.staff_id and staff.role != "manager":
        extra["staff_id"] = staff.id
    updated = await boarding_service.change_status(
        db, order, payload.target_status, staff, reason=payload.reason, request=request, **extra
    )
    return ok({
        "id": updated.id, "status": updated.status,
        "status_label": BOARDING_STATUS_LABEL.get(updated.status, updated.status),
        "settle_note": updated.settle_note,
    }, "状态已更新")


# ---------------------------------------------------------------- 照护
@router.get("/orders/{order_id}/care-logs", summary="照护日志列表")
async def care_logs(
    order_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """照护日志列表。"""
    order = await boarding_service.get_order_for_user(db, order_id, user)
    return ok([boarding_service.care_log_to_out(lg) for lg in
               await boarding_service.list_care_logs(db, order.id)])


@router.post("/orders/{order_id}/care-logs", summary="填写每日照护日志（店员 / 店长）")
async def add_care_log(
    order_id: int,
    payload: CareLogIn,
    request: Request,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """填写每日照护日志（店员 / 店长）。"""
    order = await boarding_service.get_order(db, order_id)
    log = await boarding_service.add_care_log(db, order, staff, payload, request)
    return ok(boarding_service.care_log_to_out(log), "照护日志已提交" + ("（异常已推送宠主）" if log.abnormal else ""))


# ---------------------------------------------------------------- 接送任务
@router.get("/pickup-tasks", summary="接送任务列表")
async def pickup_tasks(
    status: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """接送任务列表。"""
    rows = await boarding_service.list_pickup_tasks(db, user, status=status)
    return ok([boarding_service.pickup_task_to_out(t, o) for t, o in rows])


@router.post("/pickup-tasks/{task_id}/advance", summary="推进接送任务状态（店员 / 店长）")
async def advance_pickup(
    task_id: int,
    request: Request,
    payload: dict | None = None,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """推进接送任务状态（店员 / 店长）。"""
    target = (payload or {}).get("target_status")
    sign_off_by = (payload or {}).get("sign_off_by")
    task = await boarding_service.advance_pickup(db, task_id, staff, target, sign_off_by, request)
    return ok(boarding_service.pickup_task_to_out(task), "接送任务已推进")


# ---------------------------------------------------------------- 店长：房型与看板
@router.get("/dashboard", summary="寄养经营看板（仅店长）")
async def boarding_dashboard(
    start: date = Query(...),
    end: date = Query(...),
    manager: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    """寄养经营看板（仅店长）。"""
    return ok(await boarding_service.dashboard(db, start, end))


@router.post("/rooms", summary="新增 / 编辑宠舍（店员 / 店长）")
async def upsert_room(
    payload: BoardingRoomIn,
    request: Request,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """新增 / 编辑宠舍（店员 / 店长）。

    同一个接口两种用法：不带 `id` 新增、带 `id` 编辑；房号全局唯一，
    编辑时若把房号改成别的宠舍在用，直接 409 而不是悄悄改错房间。
    """
    from app.services.audit_service import write_log

    data = payload.model_dump(exclude={"id"})
    room: BoardingRoom | None = None
    if payload.id is not None:
        # 编辑：按 id 定位，并且房号不能撞上别的宠舍
        room = (
            await db.execute(select(BoardingRoom).where(BoardingRoom.id == payload.id))
        ).scalars().first()
        if room is None:
            raise NotFoundError("宠舍不存在")
        conflict = (
            await db.execute(
                select(BoardingRoom.id).where(
                    BoardingRoom.room_no == data["room_no"], BoardingRoom.id != room.id
                )
            )
        ).scalars().first()
        if conflict:
            raise BizError(f"房号 {data['room_no']} 已被占用，请换一个")
    else:
        # 新增：房号已存在就是冲突，**不能**静默当成编辑（否则会把别人的房间名改掉）
        exists = (
            await db.execute(
                select(BoardingRoom.id).where(BoardingRoom.room_no == data["room_no"])
            )
        ).scalars().first()
        if exists:
            raise BizError(f"房号 {data['room_no']} 已存在，请直接编辑该宠舍或换一个房号")

    if room is None:
        room = BoardingRoom(**data)
        db.add(room)
        action = "create_room"
    else:
        for key, value in data.items():
            setattr(room, key, value)
        action = "update_room"
    await db.flush()
    await write_log(db, module="boarding", action=action, user_id=staff.id,
                    biz_id=room.id, after=data, request=request)
    await db.commit()
    return ok(boarding_service.room_to_out(room), "宠舍已保存")


@router.delete("/rooms/{room_id}", summary="删除宠舍（店员 / 店长）")
async def delete_room(
    room_id: int,
    request: Request,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """删除宠舍（店员 / 店长）。

    有寄养单引用时**不允许删**（订单会指向不存在的房间，历史记录直接坏掉）——
    这种情况提示改用「维护中」停用。只在完全没有订单时物理删除。
    """
    from app.services.audit_service import write_log

    room = (
        await db.execute(select(BoardingRoom).where(BoardingRoom.id == room_id))
    ).scalars().first()
    if room is None:
        raise NotFoundError("宠舍不存在")
    used = await db.scalar(
        select(func.count()).select_from(BoardingOrder).where(BoardingOrder.room_id == room_id)
    )
    if used:
        raise BizError(f"该宠舍有 {used} 张寄养单记录，不能删除；如需停用请把房态改为「维护中」")
    await write_log(db, module="boarding", action="delete_room", user_id=staff.id,
                    biz_id=room.id, before={"room_no": room.room_no, "name": room.name},
                    request=request)
    await db.delete(room)
    await db.commit()
    return ok({"id": room_id}, "宠舍已删除")


@router.patch("/rooms/{room_id}/status", summary="调整房态（店员 / 店长，如消杀完成转空闲）")
async def update_room_status(
    room_id: int,
    payload: BoardingRoomStatusIn,
    request: Request,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """调整房态（店员 / 店长，如消杀完成转空闲）。"""
    from app.services.audit_service import write_log

    room = (
        await db.execute(select(BoardingRoom).where(BoardingRoom.id == room_id))
    ).scalars().first()
    if room is None:
        raise NotFoundError("宠舍不存在")
    if payload.status == "occupied":
        raise BizError("「占用中」由入住流程自动设置，不支持手工修改")
    before = room.status
    room.status = payload.status
    await write_log(db, module="boarding", action="update_room_status", user_id=staff.id,
                    biz_id=room.id, before={"status": before}, after={"status": room.status},
                    request=request)
    await db.commit()
    return ok(boarding_service.room_to_out(room), "房态已更新")


# ---------------------------------------------------------------- 提前接回（宠主申请 → 门店审核）
@router.post("/orders/{order_id}/early-pickup", summary="申请提前接回（宠主）")
async def apply_early_pickup(
    order_id: int,
    payload: EarlyPickupIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """宠主提交提前接回申请（不改订单状态，等门店审核）。"""
    order = await boarding_service.get_order_for_user(db, order_id, user)
    _guard_owner(order, user)
    req = await boarding_service.request_early_pickup(
        db, order, user, payload.expect_pickup_date, payload.reason
    )
    return ok(boarding_service.early_pickup_to_out(req, order), "申请已提交，等待门店审核")


@router.get("/early-pickups", summary="提前接回申请列表（宠主看自己的，店员/店长看全部）")
async def early_pickups(
    status: str | None = Query(None, description="pending / approved / rejected"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提前接回申请列表。"""
    owner_id = user.id if user.role == UserRole.CUSTOMER.value else None
    return ok(await boarding_service.list_early_pickups(db, status=status, user_id=owner_id))


@router.post("/early-pickups/{req_id}/review", summary="审核提前接回申请（店员 / 店长）")
async def review_early_pickup(
    req_id: int,
    payload: EarlyPickupReviewIn,
    request: Request,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """审核提前接回：通过会执行状态流转（归档洗护记录、释放房态），驳回需写意见。"""
    req = (
        await db.execute(select(BoardingEarlyPickup).where(BoardingEarlyPickup.id == req_id))
    ).scalars().first()
    if req is None:
        raise NotFoundError("申请不存在")
    data = await boarding_service.review_early_pickup(
        db, req, payload.approve, payload.note, staff, request
    )
    return ok(data, "已通过，订单已按提前接回处理" if payload.approve else "已驳回")
