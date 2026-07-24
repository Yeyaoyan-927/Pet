"""洗护记录接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps.auth import get_current_user, get_staff_user
from app.models import User
from app.schemas.common import ok
from app.services import wash_service
from app.services.audit_service import write_log

router = APIRouter(prefix="/wash-records", tags=["洗护记录"])


class WashRecordUpdateIn(BaseModel):
    skin_condition: str | None = Field(default=None, max_length=500)
    hair_condition: str | None = Field(default=None, max_length=500)
    products: str | None = Field(default=None, max_length=255)
    staff_note: str | None = Field(default=None, max_length=500)


@router.get("", summary="洗护记录列表")
async def list_records(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    pet_id: int | None = None,
    staff_id: int | None = None,
    start: str | None = None,
    end: str | None = None,
    mine: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """洗护记录列表。"""
    items, total = await wash_service.list_wash_records(
        db, user, page=page, size=size, pet_id=pet_id, staff_id=staff_id,
        start=start, end=end, mine=mine,
    )
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.get("/stats", summary="洗护记录看板数据")
async def record_stats(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """洗护记录看板数据。"""
    return ok(await wash_service.stats(db, user))


@router.get("/{record_id}", summary="洗护记录详情")
async def record_detail(
    record_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """洗护记录详情。"""
    from app.constants import UserRole
    from app.models import Appointment
    from app.utils.exceptions import PermissionError_

    record = await wash_service.get_record_or_404(db, record_id)
    appointment = await db.get(Appointment, record.appointment_id)
    if user.role == UserRole.CUSTOMER.value and appointment and appointment.user_id != user.id:
        raise PermissionError_("无权查看他人的洗护记录")
    return ok(wash_service.to_out(record, appointment, None, None))


@router.put("/{record_id}", summary="补录 / 修改洗护记录（店员、店长）")
async def update_record(
    record_id: int,
    payload: WashRecordUpdateIn,
    request: Request,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """补录 / 修改洗护记录（店员、店长）。"""
    record = await wash_service.get_record_or_404(db, record_id)
    wash_service.assert_can_edit(record, staff)
    before = {
        "skin_condition": record.skin_condition,
        "hair_condition": record.hair_condition,
        "products": record.products,
        "staff_note": record.staff_note,
    }
    record = await wash_service.update_record(db, record, payload.model_dump(), staff)
    await write_log(db, module="wash", action="update", staff_id=staff.id, biz_id=record_id,
                    before=before, after=payload.model_dump(), request=request)
    await db.commit()
    return ok({"id": record.id}, "洗护记录已更新")
