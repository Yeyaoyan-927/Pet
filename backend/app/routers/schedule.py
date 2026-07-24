"""门店排期接口。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps.auth import get_current_user
from app.models import User
from app.schemas.common import ok
from app.services import schedule_service

router = APIRouter(prefix="/schedule", tags=["门店排期"])


@router.get("", summary="排期视图（按日期 × 时段，含容量与预约明细）")
async def schedule(
    start: date | None = Query(None, description="起始日期，默认今天"),
    days: int = Query(7, ge=1, le=31, description="查询天数"),
    staff_id: int | None = Query(None, description="按店员过滤"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """排期视图（按日期 × 时段，含容量与预约明细）。"""
    return ok(await schedule_service.week_schedule(db, user, start=start, days=days, staff_id=staff_id))


@router.get("/staff-load", summary="店员负载统计")
async def staff_load(
    start: date = Query(...),
    end: date = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """店员负载统计。"""
    return ok(await schedule_service.staff_load(db, start, end))
