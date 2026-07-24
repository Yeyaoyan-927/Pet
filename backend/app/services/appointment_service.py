"""预约业务服务：状态机 / 时段容量 / 幂等 / 权限 / 事务 / 审计。

铁律：Agent 与表单两个入口最终都落到本服务，任何写操作不得由 LLM 直接执行 SQL。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    ACTIVE_APPOINTMENT_STATUS,
    APPOINTMENT_STATUS_LABEL,
    APPOINTMENT_TRANSITIONS,
    RISK_LEVEL_LABEL,
    SERVICE_TYPE_LABEL,
    AppointmentStatus,
    MessageType,
    UserRole,
)
from app.models import Appointment, Pet, RiskReport, SlotLock, User, WashRecord
from app.schemas.appointment import AppointmentCreate, RescheduleIn, StaffAppointmentCreate
from app.services import message_service, risk_service, setting_service
from app.services.audit_service import write_log
from app.services.pet_service import get_pet_or_404
from app.utils.crypto import encrypt_text, mask_phone, phone_hmac
from app.utils.datetime_util import calc_age_month, gen_order_no, gen_random_str, now, validate_slot
from app.utils.exceptions import (
    BizError,
    ConflictError,
    NotFoundError,
    PermissionError_,
    StateMachineError,
)
from app.utils.security import hash_password

SELECTABLE_STATUS = set(APPOINTMENT_TRANSITIONS)


async def _find_by_idempotent(db: AsyncSession, key: str | None) -> Appointment | None:
    if not key:
        return None
    return (
        await db.execute(select(Appointment).where(Appointment.idempotent_key == key))
    ).scalars().first()


async def _lock_slot(db: AsyncSession, appoint_date: date, slot_time: str) -> None:
    """对「日期 + 时段」加行锁，把并发占位串行化，杜绝 check-then-act 超卖。

    - 锁行表 `slot_lock` 用 `INSERT ... ON DUPLICATE KEY UPDATE` 保证存在（MySQL 方言，幂等）；
    - 再 `SELECT ... FOR UPDATE` 取行锁，**锁随事务提交/回滚自动释放**，不会像 `GET_LOCK()` 那样泄漏；
    - 必须与容量校验、插入处于同一事务，否则锁提前释放等于没加。

    锁粒度说明：容量约束的维度是「日期 + 时段」，故锁这一维度；
    「同宠物同日重复预约」是软约束（不同时段不冲突），不额外加锁，由 `_check_duplicate` 尽力拦截。
    """
    await db.execute(
        text(
            "INSERT INTO slot_lock (appoint_date, slot_time, created_at, updated_at) "
            "VALUES (:d, :t, NOW(), NOW()) "
            "ON DUPLICATE KEY UPDATE updated_at = NOW()"
        ),
        {"d": appoint_date, "t": slot_time},
    )
    await db.execute(
        select(SlotLock.id)
        .where(SlotLock.appoint_date == appoint_date, SlotLock.slot_time == slot_time)
        .with_for_update()
    )


async def _check_capacity(db: AsyncSession, appoint_date: date, slot_time: str) -> None:
    """容量校验（**必须用当前读**）。

    MySQL 默认隔离级别是 REPEATABLE READ：普通 `SELECT COUNT(*)` 是**快照读**，
    即使外层已经用 `slot_lock` 把并发串行化，后到的事务读到的仍是「自己事务开始时的旧快照」，
    看不到前一个事务刚提交的预约 —— 结果就是**锁加了照样超卖**（实测 6 并发 6 单全成功）。

    `SELECT ... FOR UPDATE` 是**加锁读（当前读）**，能读到最新已提交数据；
    配合 `_lock_slot` 的行锁，形成「先串行化、再当前读」的双重保障。
    """
    capacity = await setting_service.get_int(db, "default_slot_capacity")
    used_rows = (
        await db.execute(
            select(Appointment.id).where(
                Appointment.appoint_date == appoint_date,
                Appointment.slot_time == slot_time,
                Appointment.status.in_(ACTIVE_APPOINTMENT_STATUS),
            ).with_for_update()
        )
    ).scalars().all()
    if len(used_rows) >= capacity:
        raise ConflictError(
            f"{appoint_date} {slot_time} 时段已约满（容量 {capacity}），请选择其他时段"
        )


async def _check_duplicate(db: AsyncSession, pet_id: int, appoint_date: date) -> None:
    exist = await db.scalar(
        select(func.count()).select_from(Appointment).where(
            Appointment.pet_id == pet_id,
            Appointment.appoint_date == appoint_date,
            Appointment.status.in_(ACTIVE_APPOINTMENT_STATUS),
        )
    ) or 0
    if int(exist) > 0:
        raise ConflictError("该宠物当天已存在有效预约，请勿重复提交")


def _validate_date(appoint_date: date, slot_time: str) -> None:
    if not validate_slot(slot_time):
        raise BizError("预约时段不在营业时间内（09:00 - 18:00）")
    if appoint_date < date.today():
        raise BizError("预约日期不能早于今天")


async def _create(
    db: AsyncSession,
    *,
    owner: User,
    pet: Pet,
    payload: AppointmentCreate,
    created_by: str,
    operator_staff_id: int | None,
    request: Request | None,
) -> Appointment:
    # 1) 幂等：双入口统一幂等键，命中直接返回既有订单，绝不重复落库
    existed = await _find_by_idempotent(db, payload.idempotent_key)
    if existed is not None:
        return existed

    _validate_date(payload.appoint_date, payload.slot_time)
    # 先取时段行锁再校验容量：并发请求在此串行化，容量校验结果才可信
    await _lock_slot(db, payload.appoint_date, payload.slot_time)
    await _check_capacity(db, payload.appoint_date, payload.slot_time)
    await _check_duplicate(db, pet.id, payload.appoint_date)

    appointment = Appointment(
        order_no=gen_order_no(),
        user_id=owner.id,
        pet_id=pet.id,
        service_type=payload.service_type,
        appoint_date=payload.appoint_date,
        slot_time=payload.slot_time,
        status=AppointmentStatus.PENDING.value,
        staff_id=operator_staff_id,
        operator_staff_id=operator_staff_id,
        created_by=created_by,
        idempotent_key=payload.idempotent_key,
        remark=payload.remark,
    )
    db.add(appointment)
    await db.flush()

    # 2) 风险判别：预约提交自动触发，规则引擎初筛
    await risk_service.assess_risk(db, appointment, pet)

    # 3) 站内信通知宠主
    await message_service.create_message(
        db,
        user_id=owner.id,
        title=f"预约已提交：{appointment.order_no}",
        content=(
            f"宠物 {pet.name} 已预约 {payload.appoint_date} {payload.slot_time} "
            f"{SERVICE_TYPE_LABEL.get(payload.service_type, payload.service_type)}，"
            f"等待门店确认。"
        ),
        msg_type=MessageType.APPOINTMENT_CREATED.value,
        biz_id=appointment.id,
    )

    await write_log(
        db, module="appointment", action="create", user_id=owner.id, staff_id=operator_staff_id,
        biz_id=appointment.id, after=_snapshot(appointment), request=request,
        detail=f"入口={created_by}",
    )
    await db.commit()
    await db.refresh(appointment)
    return appointment


async def create_by_customer(
    db: AsyncSession, user: User, payload: AppointmentCreate, request: Request | None = None
) -> Appointment:
    """宠主自助下单：校验日期/时段 → 取时段行锁 → 容量校验 → 同日重复拦截 →

        风险判别 → 落库 + 审计 + 站内信。幂等键命中时直接回已有单。
    """
    pet = await get_pet_or_404(db, payload.pet_id)
    if pet.user_id != user.id and user.role == UserRole.CUSTOMER.value:
        raise PermissionError_("只能为自己的宠物预约")
    return await _create(
        db, owner=user, pet=pet, payload=payload, created_by="form",
        operator_staff_id=None, request=request,
    )


async def create_by_staff(
    db: AsyncSession, staff: User, payload: StaffAppointmentCreate, request: Request | None = None
) -> Appointment:
    """店员代客预约：手机号不存在则创建临时用户，用户登录后可认领。"""
    owner = (
        await db.execute(select(User).where(User.phone_hash == phone_hmac(payload.phone)))
    ).scalars().first()
    created_temp = False
    if owner is None:
        owner = User(
            username=f"temp_{payload.phone[-6:]}_{gen_random_str(6)}",
            password_hash=hash_password(gen_random_str(12)),
            real_name=f"临时客户{payload.phone[-4:]}",
            phone_encrypted=encrypt_text(payload.phone),
            phone_hash=phone_hmac(payload.phone),
            role=UserRole.CUSTOMER.value,
            is_temp=1,
        )
        db.add(owner)
        await db.flush()
        created_temp = True

    pet: Pet | None = None
    if payload.pet_id:
        pet = await get_pet_or_404(db, payload.pet_id)
        if pet.user_id != owner.id:
            raise BizError("所选宠物不属于该手机号对应的宠主")
    if pet is None:
        pet = Pet(
            user_id=owner.id,
            staff_id=staff.id,
            name=payload.pet_name or "待补充宠物",
            species="dog",
            gender="male",
        )
        db.add(pet)
        await db.flush()

    appointment = await _create(
        db, owner=owner, pet=pet, payload=payload, created_by="staff",
        operator_staff_id=staff.id, request=request,
    )
    await write_log(
        db, module="appointment", action="create_for_customer", user_id=staff.id, staff_id=staff.id,
        biz_id=appointment.id, request=request,
        detail=f"代客预约，临时用户创建={created_temp}",
    )
    await db.commit()
    return appointment


async def reschedule(
    db: AsyncSession, appointment: Appointment, payload: RescheduleIn, operator: User,
    request: Request | None = None,
) -> Appointment:
    """改期：仅待确认/已确认可改，受最大改期次数限制；改到相同时段时跳过容量校验

        （否则本单会被自己占位挡住），改期后重写排期并通知宠主。
    """
    if appointment.status not in {AppointmentStatus.PENDING.value, AppointmentStatus.CONFIRMED.value}:
        raise StateMachineError("仅待确认 / 已确认的预约可以改期")

    max_times = await setting_service.get_int(db, "max_reschedule_times")
    if appointment.reschedule_times >= max_times:
        raise StateMachineError(f"该预约已改期 {appointment.reschedule_times} 次，达到上限 {max_times}")

    _validate_date(payload.appoint_date, payload.slot_time)
    # 目的地与当前时段相同则只累计改期次数：否则容量校验会把本单自己算进去而误判「已约满」
    if (payload.appoint_date, payload.slot_time) != (appointment.appoint_date, appointment.slot_time):
        await _lock_slot(db, payload.appoint_date, payload.slot_time)
        await _check_capacity(db, payload.appoint_date, payload.slot_time)

    before = _snapshot(appointment)
    appointment.appoint_date = payload.appoint_date
    appointment.slot_time = payload.slot_time
    appointment.reschedule_times += 1
    if payload.reason:
        appointment.remark = payload.reason
    await db.flush()

    await message_service.create_message(
        db, user_id=appointment.user_id, title=f"预约已改期：{appointment.order_no}",
        content=f"新的到店时间为 {payload.appoint_date} {payload.slot_time}。",
        msg_type=MessageType.APPOINTMENT_CREATED.value, biz_id=appointment.id,
    )
    await write_log(
        db, module="appointment", action="reschedule", user_id=operator.id,
        staff_id=operator.id if operator.role != UserRole.CUSTOMER.value else None,
        biz_id=appointment.id, before=before, after=_snapshot(appointment), request=request,
    )
    await db.commit()
    await db.refresh(appointment)
    return appointment


async def change_status(
    db: AsyncSession,
    appointment: Appointment,
    target: str,
    operator: User,
    reason: str | None = None,
    request: Request | None = None,
) -> Appointment:
    """统一状态流转入口：校验状态机 + 归属权限 + 终止原因必填。"""
    if target not in SELECTABLE_STATUS:
        raise BizError(f"非法的目标状态：{target}")
    if target not in APPOINTMENT_TRANSITIONS.get(appointment.status, set()):
        raise StateMachineError(
            f"不允许从「{APPOINTMENT_STATUS_LABEL.get(appointment.status)}」变更为"
            f"「{APPOINTMENT_STATUS_LABEL.get(target)}」"
        )

    if operator.role == UserRole.CUSTOMER.value:
        if appointment.user_id != operator.id:
            raise PermissionError_("无权操作他人的预约")
        if target not in {AppointmentStatus.CANCELLED.value}:
            raise PermissionError_("宠主仅可取消自己的预约")
    elif operator.role == UserRole.STAFF.value:
        # 归属校验：未认领可认领，已归属他人则拒绝（店长不受限）
        if appointment.staff_id is not None and appointment.staff_id != operator.id:
            raise PermissionError_("该预约归属其他店员，无权操作")

    terminate_status = {
        AppointmentStatus.CANCELLED.value,
        AppointmentStatus.NO_SHOW.value,
        AppointmentStatus.ARRIVED_GIVE_UP.value,
        AppointmentStatus.WASH_INTERRUPT.value,
    }
    if target in terminate_status and not (reason or "").strip():
        raise BizError("该操作必须填写原因")

    before = _snapshot(appointment)
    appointment.status = target
    current = now()

    if target == AppointmentStatus.CONFIRMED.value:
        appointment.confirm_at = current
        if appointment.staff_id is None and operator.role != UserRole.CUSTOMER.value:
            appointment.staff_id = operator.id
    elif target == AppointmentStatus.ARRIVED.value:
        appointment.arrive_at = current
    elif target == AppointmentStatus.IN_SERVICE.value:
        appointment.start_at = current
        if appointment.staff_id is None and operator.role != UserRole.CUSTOMER.value:
            appointment.staff_id = operator.id
    elif target == AppointmentStatus.COMPLETED.value:
        appointment.finish_at = current
        await _archive_wash_record(db, appointment, operator)
    elif target == AppointmentStatus.CANCELLED.value:
        appointment.cancel_at = current
        appointment.cancel_reason = reason
        if not reason:
            appointment.cancel_reason = "用户取消"
    elif target in {AppointmentStatus.ARRIVED_GIVE_UP.value, AppointmentStatus.WASH_INTERRUPT.value}:
        appointment.terminate_reason = reason
    elif target == AppointmentStatus.NO_SHOW.value:
        appointment.terminate_reason = reason

    await db.flush()

    title, content = _notify_content(appointment, target, reason)
    await message_service.create_message(
        db, user_id=appointment.user_id, title=title, content=content,
        msg_type=_message_type(target), biz_id=appointment.id,
    )
    await write_log(
        db, module="appointment", action=f"status:{target}",
        user_id=operator.id,
        staff_id=operator.id if operator.role != UserRole.CUSTOMER.value else None,
        biz_id=appointment.id, before=before, after=_snapshot(appointment),
        request=request, detail=reason,
    )
    await db.commit()
    await db.refresh(appointment)
    return appointment


async def _archive_wash_record(db: AsyncSession, appointment: Appointment, operator: User) -> None:
    exists = await db.scalar(
        select(func.count()).select_from(WashRecord).where(
            WashRecord.appointment_id == appointment.id
        )
    )
    if exists:
        return
    db.add(
        WashRecord(
            appointment_id=appointment.id,
            pet_id=appointment.pet_id,
            staff_id=appointment.staff_id,
            service_type=appointment.service_type,
            wash_start=appointment.start_at,
            wash_end=now(),
        )
    )
    await db.flush()


def _message_type(target: str) -> str:
    mapping = {
        AppointmentStatus.CONFIRMED.value: MessageType.APPOINTMENT_CONFIRMED.value,
        AppointmentStatus.CANCELLED.value: MessageType.APPOINTMENT_CANCELLED.value,
        AppointmentStatus.COMPLETED.value: MessageType.APPOINTMENT_COMPLETED.value,
    }
    return mapping.get(target, MessageType.SYSTEM.value)


def _notify_content(appointment: Appointment, target: str, reason: str | None) -> tuple[str, str]:
    label = APPOINTMENT_STATUS_LABEL.get(target, target)
    title = f"预约状态更新为「{label}」：{appointment.order_no}"
    content = f"预约时间 {appointment.appoint_date} {appointment.slot_time}。"
    if reason:
        content += f" 原因：{reason}"
    return title, content


def _snapshot(appointment: Appointment) -> dict:
    return {
        "order_no": appointment.order_no,
        "status": appointment.status,
        "appoint_date": str(appointment.appoint_date),
        "slot_time": appointment.slot_time,
        "service_type": appointment.service_type,
        "staff_id": appointment.staff_id,
        "risk_level": appointment.risk_level,
        "reschedule_times": appointment.reschedule_times,
    }


async def get_appointment_for_user(db: AsyncSession, appointment_id: int, user: User) -> Appointment:
    """按角色取单：宠主只能看自己的，店员/店长可看全部门店数据。"""
    appointment = await db.get(Appointment, appointment_id)
    if appointment is None or appointment.deleted_at is not None:
        raise NotFoundError("预约不存在")
    if user.role == UserRole.CUSTOMER.value and appointment.user_id != user.id:
        raise PermissionError_("无权查看该预约")
    if user.role == UserRole.STAFF.value and appointment.staff_id not in (None, user.id):
        raise PermissionError_("该预约归属其他店员")
    return appointment


async def list_appointments(
    db: AsyncSession,
    user: User,
    *,
    page: int = 1,
    size: int = 10,
    status: str | None = None,
    appoint_date: date | None = None,
    keyword: str | None = None,
    mine: bool = False,
) -> tuple[list[dict], int]:
    """分页列表：宠主自动收敛到本人，店员/店长可按状态、日期、关键词筛选。"""
    cond = [Appointment.deleted_at.is_(None)]
    if user.role == UserRole.CUSTOMER.value:
        cond.append(Appointment.user_id == user.id)
    elif user.role == UserRole.STAFF.value and mine:
        cond.append(Appointment.staff_id == user.id)
    if status:
        cond.append(Appointment.status == status)
    if appoint_date:
        cond.append(Appointment.appoint_date == appoint_date)
    if keyword:
        cond.append(Appointment.order_no.like(f"%{keyword}%"))

    total = await db.scalar(select(func.count()).select_from(Appointment).where(*cond)) or 0
    stmt = (
        select(Appointment, Pet, User)
        .outerjoin(Pet, Pet.id == Appointment.pet_id)
        .outerjoin(User, User.id == Appointment.user_id)
        .where(*cond)
        .order_by(Appointment.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    rows = (await db.execute(stmt)).all()
    items = [appointment_to_out(a, p, u) for a, p, u in rows]
    return items, int(total)


def appointment_to_out(a: Appointment, pet: Pet | None, owner: User | None) -> dict:
    """序列化为接口结构：补宠物与宠主信息，手机号解密后由上层决定是否脱敏展示。"""
    from app.utils.crypto import decrypt_text

    return {
        "id": a.id,
        "order_no": a.order_no,
        "user_id": a.user_id,
        "pet_id": a.pet_id,
        "pet_name": pet.name if pet else None,
        "pet_breed": pet.breed if pet else None,
        "owner_name": getattr(owner, "real_name", None),
        "owner_phone": mask_phone(decrypt_text(owner.phone_encrypted)) if owner else None,
        "service_type": a.service_type,
        "service_type_label": SERVICE_TYPE_LABEL.get(a.service_type, a.service_type),
        "appoint_date": a.appoint_date,
        "slot_time": a.slot_time,
        "status": a.status,
        "status_label": APPOINTMENT_STATUS_LABEL.get(a.status, a.status),
        "staff_id": a.staff_id,
        "staff_name": None,
        "risk_level": a.risk_level,
        "risk_level_label": RISK_LEVEL_LABEL.get(a.risk_level or "", None),
        "remark": a.remark,
        "cancel_reason": a.cancel_reason,
        "terminate_reason": a.terminate_reason,
        "reschedule_times": a.reschedule_times,
        "confirm_at": a.confirm_at,
        "arrive_at": a.arrive_at,
        "finish_at": a.finish_at,
        "created_at": a.created_at,
    }


async def sla_scan(db: AsyncSession, request: Request | None = None) -> dict:
    """店员确认 SLA 巡检（V1 由启动时手动/定时调用；V4 交给 arq 定时任务）。"""
    timeout_hours = await setting_service.get_int(db, "staff_confirm_timeout_hours")
    auto_cancel = await setting_service.get_bool(db, "auto_cancel_on_timeout")
    deadline = now() - timedelta(hours=timeout_hours)
    pendings = (
        await db.execute(
            select(Appointment).where(
                Appointment.status == AppointmentStatus.PENDING.value,
                Appointment.created_at <= deadline,
            )
        )
    ).scalars().all()

    escalated, cancelled = 0, 0
    for appt in pendings:
        escalated += 1
        if auto_cancel:
            # 风险报告标记失效（预约已取消，风险报告不再生效）
            reports = (
                await db.execute(
                    select(RiskReport).where(
                        RiskReport.appointment_id == appt.id, RiskReport.invalidated == 0
                    )
                )
            ).scalars().all()
            for report in reports:
                report.invalidated = 1
            before = _snapshot(appt)
            appt.status = AppointmentStatus.CANCELLED.value
            appt.cancel_at = now()
            appt.cancel_reason = f"超时未确认（>{timeout_hours}h）自动取消，不计入爽约"
            await message_service.create_message(
                db, user_id=appt.user_id,
                title=f"预约已自动取消：{appt.order_no}",
                content=appt.cancel_reason, msg_type=MessageType.APPOINTMENT_CANCELLED.value,
                biz_id=appt.id,
            )
            await write_log(
                db, module="appointment", action="sla_auto_cancel", biz_id=appt.id,
                before=before, after=_snapshot(appt), request=request, detail="SLA 超时自动取消",
            )
            cancelled += 1
    await db.commit()
    return {"escalated": escalated, "cancelled": cancelled,
            "timeout_hours": timeout_hours, "auto_cancel": auto_cancel}


def pet_age_text(pet: Pet) -> str:
    """月龄文案（「1岁3个月」/「4个月」），生日缺失时返回「未知」。"""
    months = calc_age_month(pet.birthday)
    if months is None:
        return "未知"
    return f"{months // 12}岁{months % 12}个月" if months >= 12 else f"{months}个月"
