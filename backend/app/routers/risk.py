"""风险报告接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps.auth import get_current_user, get_staff_user
from app.models import User
from app.schemas.common import ok
from app.services import risk_service
from app.services.audit_service import write_log
from app.utils.exceptions import NotFoundError, PermissionError_

router = APIRouter(prefix="/risks", tags=["风险判别"])


class RiskConfirmIn(BaseModel):
    handle_measure: str | None = Field(default=None, max_length=500, description="店员处置措施")
    manual_level: str | None = Field(default=None, description="店员人工修正的风险等级 high/low/none")


@router.get("", summary="风险报告列表")
async def list_reports(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    only_unconfirmed: bool = False,
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """风险报告列表。"""
    items, total = await risk_service.list_reports(db, page=page, size=size,
                                                  only_unconfirmed=only_unconfirmed)
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.get("/appointment/{appointment_id}", summary="按预约查询风险报告")
async def get_by_appointment(
    appointment_id: int,
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """按预约查询风险报告。"""
    report = await risk_service.get_by_appointment(db, appointment_id)
    if report is None:
        raise NotFoundError("该预约暂无风险报告")
    return ok(risk_service.report_to_out(report))


@router.post("/appointment/{appointment_id}/rerun", summary="手动重跑风险判别")
async def rerun(
    appointment_id: int,
    request: Request,
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """手动重跑风险判别。"""
    from app.models import Appointment, Pet

    appointment = await db.get(Appointment, appointment_id)
    if appointment is None:
        raise NotFoundError("预约不存在")
    pet = await db.get(Pet, appointment.pet_id)
    if pet is None:
        raise NotFoundError("宠物档案不存在")
    report = await risk_service.assess_risk(db, appointment, pet)
    await write_log(db, module="risk", action="rerun", staff_id=user.id, biz_id=appointment_id,
                    after={"risk_level": report.risk_level}, request=request)
    await db.commit()
    return ok(risk_service.report_to_out(report), "风险判别已重跑")


@router.post("/appointment/{appointment_id}/confirm", summary="店员人工复核确认（AI 仅辅助，店员最终决策）")
async def confirm(
    appointment_id: int,
    payload: RiskConfirmIn,
    request: Request,
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """店员人工复核确认（AI 仅辅助，店员最终决策）。"""
    report = await risk_service.get_by_appointment(db, appointment_id)
    if report is None:
        raise NotFoundError("该预约暂无风险报告")
    if report.invalidated == 1:
        raise PermissionError_("该风险报告已失效（预约已取消）")

    before = {"risk_level": report.risk_level, "confirmed": report.confirmed}
    if payload.manual_level and payload.manual_level != report.risk_level:
        if payload.manual_level not in {"high", "low", "none"}:
            raise PermissionError_("manual_level 仅支持 high / low / none")
        report.risk_level = payload.manual_level
        report.engine_type = "manual"

    await risk_service.confirm_report(db, report, user.id, payload.handle_measure)
    await write_log(db, module="risk", action="confirm", staff_id=user.id, biz_id=appointment_id,
                    before=before, after={"risk_level": report.risk_level, "confirmed": 1,
                                          "handle_measure": payload.handle_measure},
                    request=request)
    await db.commit()
    return ok(risk_service.report_to_out(report), "风险报告已复核确认")
