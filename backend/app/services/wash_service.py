"""洗护记录服务：洗护结果归档、查询与补录。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment, Pet, User, WashRecord
from app.utils.exceptions import NotFoundError, PermissionError_

VACCINE_NONE = "-"


async def list_wash_records(
    db: AsyncSession,
    user,
    *,
    page: int = 1,
    size: int = 10,
    pet_id: int | None = None,
    staff_id: int | None = None,
    start: str | None = None,
    end: str | None = None,
    mine: bool = False,
) -> tuple[list[dict], int]:
    """洗护记录分页，返回 (列表, 总数)；宠主只能看自己的。"""
    from app.constants import UserRole

    cond = [Appointment.deleted_at.is_(None)]
    stmt = (
        select(WashRecord, Appointment, Pet, User)
        .join(Appointment, Appointment.id == WashRecord.appointment_id)
        .outerjoin(Pet, Pet.id == WashRecord.pet_id)
        .outerjoin(User, User.id == Appointment.user_id)
        .where(*cond)
    )
    if user.role == UserRole.CUSTOMER.value:
        stmt = stmt.where(Appointment.user_id == user.id)
    elif user.role == UserRole.STAFF.value and mine:
        stmt = stmt.where(WashRecord.staff_id == user.id)

    if pet_id:
        stmt = stmt.where(WashRecord.pet_id == pet_id)
    if staff_id:
        stmt = stmt.where(WashRecord.staff_id == staff_id)
    if start:
        stmt = stmt.where(Appointment.appoint_date >= start)
    if end:
        stmt = stmt.where(Appointment.appoint_date <= end)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(await db.scalar(count_stmt) or 0)

    rows = (
        await db.execute(
            stmt.order_by(WashRecord.id.desc()).offset((page - 1) * size).limit(size)
        )
    ).all()
    return [to_out(w, a, p, u) for w, a, p, u in rows], total


async def get_record_or_404(db: AsyncSession, record_id: int) -> WashRecord:
    """按 ID 取记录，不存在抛 NotFoundError。"""
    record = await db.get(WashRecord, record_id)
    if record is None:
        raise NotFoundError("洗护记录不存在")
    return record


def assert_can_edit(record: WashRecord, user) -> None:
    """编辑权限：宠主不可改，店员限本人经手的记录。"""
    from app.constants import UserRole

    if user.role == UserRole.CUSTOMER.value:
        raise PermissionError_("宠主不可编辑洗护记录")
    if user.role == UserRole.STAFF.value and record.staff_id not in (None, user.id):
        raise PermissionError_("该洗护记录归属其他店员")


async def update_record(db: AsyncSession, record: WashRecord, payload: dict, user) -> WashRecord:
    """补录洗护细节（服务项目、用时、备注、照片等）。"""
    for key in ("skin_condition", "hair_condition", "products", "staff_note"):
        if key in payload and payload[key] is not None:
            setattr(record, key, payload[key])
    await db.flush()
    return record


async def stats(db: AsyncSession, user) -> dict:
    """洗护记录看板数据：本月完成数、平均时长、服务分布。"""
    from app.constants import SERVICE_TYPE_LABEL, UserRole

    stmt = select(WashRecord, Appointment).join(Appointment, Appointment.id == WashRecord.appointment_id)
    if user.role == UserRole.CUSTOMER.value:
        stmt = stmt.where(Appointment.user_id == user.id)
    rows = (await db.execute(stmt)).all()

    total = len(rows)
    durations = [
        (w.wash_end - w.wash_start).total_seconds() / 60
        for w, _ in rows
        if w.wash_start and w.wash_end
    ]
    avg_minutes = round(sum(durations) / len(durations), 1) if durations else 0

    dist: dict[str, int] = {}
    for w, _ in rows:
        dist[SERVICE_TYPE_LABEL.get(w.service_type, w.service_type)] = (
            dist.get(SERVICE_TYPE_LABEL.get(w.service_type, w.service_type), 0) + 1
        )

    today = datetime.now().date()
    this_month = sum(1 for w, _ in rows if w.created_at and w.created_at.date().month == today.month)

    return {
        "total": total,
        "this_month": this_month,
        "avg_minutes": avg_minutes,
        "service_distribution": [{"label": k, "value": v} for k, v in dist.items()],
    }


def to_out(w: WashRecord, a: Appointment | None, p: Pet | None, owner: User | None) -> dict:
    """记录序列化：补预约、宠物、宠主与项目中文标签。"""
    from app.constants import SERVICE_TYPE_LABEL
    from app.utils.crypto import decrypt_text, mask_phone

    return {
        "id": w.id,
        "appointment_id": w.appointment_id,
        "order_no": a.order_no if a else None,
        "pet_id": w.pet_id,
        "pet_name": p.name if p else None,
        "pet_breed": p.breed if p else None,
        "pet_species": p.species if p else None,
        "owner_name": getattr(owner, "real_name", None),
        "owner_phone": mask_phone(decrypt_text(owner.phone_encrypted)) if owner else None,
        "staff_id": w.staff_id,
        "service_type": w.service_type,
        "service_type_label": SERVICE_TYPE_LABEL.get(w.service_type, w.service_type),
        "appoint_date": a.appoint_date if a else None,
        "slot_time": a.slot_time if a else None,
        "wash_start": w.wash_start,
        "wash_end": w.wash_end,
        "skin_condition": w.skin_condition,
        "hair_condition": w.hair_condition,
        "products": w.products,
        "staff_note": w.staff_note,
        "created_at": w.created_at,
    }
