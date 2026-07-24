"""站内消息接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps.auth import get_current_user
from app.models import User
from app.schemas.common import ok
from app.services import message_service

router = APIRouter(prefix="/messages", tags=["站内消息"])


@router.get("", summary="消息列表")
async def list_messages(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    only_unread: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """消息列表。"""
    rows, total = await message_service.list_messages(db, user.id, page, size, only_unread)
    return ok({"items": [message_service.to_out(m) for m in rows], "total": total,
               "page": page, "size": size})


@router.get("/unread-count", summary="未读数量")
async def unread(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """未读数量。"""
    return ok({"unread": await message_service.unread_count(db, user.id)})


@router.post("/read-all", summary="全部标记已读")
async def read_all(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """全部标记已读。"""
    count = await message_service.mark_all_read(db, user.id)
    await db.commit()
    return ok({"updated": count}, "已全部标记为已读")


@router.post("/{message_id}/read", summary="标记单条已读")
async def read_one(
    message_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """标记单条已读。"""
    await message_service.mark_read(db, user.id, message_id)
    await db.commit()
    return ok(None, "已读")


@router.delete("/{message_id}", summary="删除消息（逻辑删除）")
async def delete_message(
    message_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除消息（逻辑删除）。"""
    await message_service.remove_message(db, user.id, message_id)
    await db.commit()
    return ok(None, "消息已删除")
