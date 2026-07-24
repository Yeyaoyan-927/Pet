"""预约接口（表单入口；Agent 工具入口在 V4 复用同一 service）。"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import APPOINTMENT_STATUS_LABEL, SERVICE_TYPE_LABEL, ServiceType, UserRole
from app.database import get_db
from app.deps.auth import get_current_user, get_staff_user, get_manager_user
from app.models import User
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentStatusChange,
    RescheduleIn,
    StaffAppointmentCreate,
)
from app.schemas.common import ok
from app.services import appointment_service, setting_service
from app.utils.exceptions import PermissionError_

router = APIRouter(prefix="/appointments", tags=["预约"])


@router.get("/slots", summary="可预约时段（含剩余容量）")
async def slots(
    appoint_date: date = Query(..., description="查询日期"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """可预约时段（含剩余容量）。"""
    from sqlalchemy import func, select

    from app.constants import ACTIVE_APPOINTMENT_STATUS
    from app.models import Appointment

    capacity = await setting_service.get_int(db, "default_slot_capacity")
    rows = (
        await db.execute(
            select(Appointment.slot_time, func.count())
            .where(Appointment.appoint_date == appoint_date,
                   Appointment.status.in_(ACTIVE_APPOINTMENT_STATUS))
            .group_by(Appointment.slot_time)
        )
    ).all()
    used = {slot: int(c) for slot, c in rows}
    result = []
    for slot in settings.slot_list():
        taken = used.get(slot, 0)
        result.append({
            "slot_time": slot,
            "capacity": capacity,
            "used": taken,
            "remain": max(capacity - taken, 0),
            "disabled": taken >= capacity,
        })
    return ok({"appoint_date": str(appoint_date), "slots": result, "capacity": capacity})


@router.get("/options", summary="预约表单选项")
async def options(user: User = Depends(get_current_user)):
    """预约表单选项。"""
    return ok({
        "services": [{"value": k, "label": v} for k, v in SERVICE_TYPE_LABEL.items()],
        "statuses": [{"value": k, "label": v} for k, v in APPOINTMENT_STATUS_LABEL.items()],
    })


@router.get("", summary="预约列表")
async def list_appointments(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    status: str | None = None,
    appoint_date: date | None = None,
    keyword: str | None = None,
    mine: bool = Query(False, description="店员仅看归属自己的订单"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """预约列表。"""
    items, total = await appointment_service.list_appointments(
        db, user, page=page, size=size, status=status, appoint_date=appoint_date,
        keyword=keyword, mine=mine,
    )
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.post("", summary="宠主提交预约（表单入口）")
async def create_appointment(
    payload: AppointmentCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """宠主提交预约（表单入口）。"""
    appointment = await appointment_service.create_by_customer(db, user, payload, request)
    return ok(appointment_service.appointment_to_out(appointment, None, None), "预约已提交，等待门店确认")


@router.post("/staff", summary="店员代客预约（手机号不存在则创建临时用户）")
async def create_by_staff(
    payload: StaffAppointmentCreate,
    request: Request,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """店员代客预约（手机号不存在则创建临时用户）。"""
    appointment = await appointment_service.create_by_staff(db, staff, payload, request)
    return ok({"id": appointment.id, "order_no": appointment.order_no}, "代客预约已创建")


@router.get("/{appointment_id}", summary="预约详情")
async def detail(
    appointment_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """预约详情。"""
    appointment = await appointment_service.get_appointment_for_user(db, appointment_id, user)
    return ok(appointment_service.appointment_to_out(appointment, None, None))


@router.post("/{appointment_id}/status", summary="状态流转（确认/到店/洗护中/完成/取消/爽约/放弃/中断）")
async def change_status(
    appointment_id: int,
    payload: AppointmentStatusChange,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """状态流转（确认/到店/洗护中/完成/取消/爽约/放弃/中断）。"""
    appointment = await appointment_service.get_appointment_for_user(db, appointment_id, user)
    appointment = await appointment_service.change_status(
        db, appointment, payload.status, user, payload.reason, request
    )
    return ok(appointment_service.appointment_to_out(appointment, None, None), "状态已更新")


@router.post("/{appointment_id}/reschedule", summary="改期")
async def reschedule(
    appointment_id: int,
    payload: RescheduleIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """改期。"""
    if user.role == UserRole.CUSTOMER.value:
        raise PermissionError_("宠主改期请先取消后重新预约")
    appointment = await appointment_service.get_appointment_for_user(db, appointment_id, user)
    appointment = await appointment_service.reschedule(db, appointment, payload, user, request)
    return ok(appointment_service.appointment_to_out(appointment, None, None), "预约已改期")


@router.post("/sla/scan", summary="[运维] 手动触发店员确认 SLA 巡检")
async def sla_scan(
    request: Request,
    _: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    """[运维] 手动触发店员确认 SLA 巡检。"""
    result = await appointment_service.sla_scan(db, request)
    return ok(result, "SLA 巡检完成")


@router.get("/stats/overview", summary="工作台概览卡片")
async def overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """工作台概览卡片。"""
    from sqlalchemy import func, select

    from app.constants import AppointmentStatus
    from app.models import Appointment

    today = date.today()
    cond = [Appointment.deleted_at.is_(None), Appointment.appoint_date == today]
    if user.role == UserRole.CUSTOMER.value:
        cond.append(Appointment.user_id == user.id)

    async def count(*extra):
        return int(await db.scalar(select(func.count()).select_from(Appointment).where(*cond, *extra)) or 0)

    return ok({
        "today_total": await count(),
        "today_pending": await count(Appointment.status == AppointmentStatus.PENDING.value),
        "today_confirmed": await count(Appointment.status == AppointmentStatus.CONFIRMED.value),
        "today_arrived": await count(Appointment.status == AppointmentStatus.ARRIVED.value),
        "today_finished": await count(Appointment.status == AppointmentStatus.COMPLETED.value),
        "week_total": int(
            await db.scalar(
                select(func.count()).select_from(Appointment).where(
                    Appointment.deleted_at.is_(None),
                    Appointment.appoint_date >= today - timedelta(days=6),
                    Appointment.appoint_date <= today,
                )
            ) or 0
        ),
    })
