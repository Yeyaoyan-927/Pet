"""排期服务：按日期 × 时段输出门店排期视图（容量 / 占用 / 预约明细）。"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    ACTIVE_APPOINTMENT_STATUS,
    APPOINTMENT_STATUS_LABEL,
    SERVICE_TYPE_LABEL,
    UserRole,
)
from app.models import Appointment, Pet, User
from app.services import setting_service
from app.utils.crypto import decrypt_text, mask_phone


async def week_schedule(
    db: AsyncSession,
    user,
    *,
    start: date | None = None,
    days: int = 7,
    staff_id: int | None = None,
) -> dict:
    """周排期：按天聚合时段占用与预约，供排期页与门店看板使用。"""
    start = start or date.today()
    end = start + timedelta(days=days - 1)
    capacity = await setting_service.get_int(db, "default_slot_capacity")

    cond = [
        Appointment.deleted_at.is_(None),
        Appointment.appoint_date >= start,
        Appointment.appoint_date <= end,
    ]
    if user.role == UserRole.CUSTOMER.value:
        cond.append(Appointment.user_id == user.id)
    elif staff_id:
        cond.append(Appointment.staff_id == staff_id)

    rows = (
        await db.execute(
            select(Appointment, Pet, User)
            .outerjoin(Pet, Pet.id == Appointment.pet_id)
            .outerjoin(User, User.id == Appointment.user_id)
            .where(*cond)
            .order_by(Appointment.appoint_date, Appointment.slot_time)
        )
    ).all()

    slots = settings.slot_list()
    bucket: dict[str, dict[str, list]] = {}
    for appt, pet, owner in rows:
        key = appt.appoint_date.isoformat()
        bucket.setdefault(key, {}).setdefault(appt.slot_time, []).append((appt, pet, owner))

    days_out = []
    cursor = start
    for _ in range(days):
        key = cursor.isoformat()
        day_items = bucket.get(key, {})
        day_slots = []
        for slot in slots:
            items = day_items.get(slot, [])
            used = sum(1 for a, _, _ in items if a.status in ACTIVE_APPOINTMENT_STATUS)
            day_slots.append({
                "slot_time": slot,
                "capacity": capacity,
                "used": used,
                "remain": max(capacity - used, 0),
                "full": used >= capacity,
                "appointments": [_brief(a, p, o) for a, p, o in items],
            })
        days_out.append({
            "date": key,
            "weekday": "周" + "一二三四五六日"[cursor.weekday()],
            "is_today": cursor == date.today(),
            "total": len(day_items and [i for v in day_items.values() for i in v]),
            "slots": day_slots,
        })
        cursor += timedelta(days=1)

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "capacity": capacity,
        "days": days_out,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _brief(a: Appointment, p: Pet | None, owner: User | None) -> dict:
    return {
        "id": a.id,
        "order_no": a.order_no,
        "pet_name": p.name if p else None,
        "pet_species": p.species if p else None,
        "owner_name": getattr(owner, "real_name", None),
        "owner_phone": mask_phone(decrypt_text(owner.phone_encrypted)) if owner else None,
        "service_type": a.service_type,
        "service_type_label": SERVICE_TYPE_LABEL.get(a.service_type, a.service_type),
        "status": a.status,
        "status_label": APPOINTMENT_STATUS_LABEL.get(a.status, a.status),
        "risk_level": a.risk_level,
        "staff_id": a.staff_id,
    }


async def load_by_date(db: AsyncSession, user, appoint_date: date) -> dict:
    """单日排期（周视图的天数为 1 的特例）。"""
    return await week_schedule(db, user, start=appoint_date, days=1)


async def staff_load(db: AsyncSession, start: date, end: date) -> list[dict]:
    """店员排班负载：按店员统计区间内已完成 / 进行中订单数。"""
    rows = (
        await db.execute(
            select(
                Appointment.staff_id,
                User.real_name,
                func.count(),
            )
            .outerjoin(User, User.id == Appointment.staff_id)
            .where(
                Appointment.deleted_at.is_(None),
                Appointment.appoint_date >= start,
                Appointment.appoint_date <= end,
                Appointment.staff_id.is_not(None),
            )
            .group_by(Appointment.staff_id, User.real_name)
        )
    ).all()
    return [
        {"staff_id": sid, "staff_name": name or f"店员#{sid}", "count": int(c)}
        for sid, name, c in rows
    ]
