"""站内消息服务。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import MESSAGE_TYPE_LABEL
from app.models import Message
from app.utils.exceptions import NotFoundError


async def create_message(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    content: str | None = None,
    msg_type: str = "system",
    biz_id: int | None = None,
) -> Message:
    """写入站内信（业务侧统一入口；标题/正文由调用方组织）。"""
    msg = Message(user_id=user_id, title=title, content=content, msg_type=msg_type, biz_id=biz_id)
    db.add(msg)
    await db.flush()
    return msg


def to_out(msg: Message) -> dict:
    """消息序列化：补消息类型中文名。"""
    return {
        "id": msg.id,
        "title": msg.title,
        "content": msg.content,
        "msg_type": msg.msg_type,
        "msg_type_label": MESSAGE_TYPE_LABEL.get(msg.msg_type, msg.msg_type),
        "biz_id": msg.biz_id,
        "is_read": msg.is_read,
        "read_at": msg.read_at,
        "created_at": msg.created_at,
    }


async def list_messages(db: AsyncSession, user_id: int, page: int, size: int,
                        only_unread: bool = False) -> tuple[list[Message], int]:
    """分页消息列表，返回 (列表, 总数)；可选只看未读。"""
    cond = [Message.user_id == user_id, Message.deleted_at.is_(None)]
    if only_unread:
        cond.append(Message.is_read == 0)
    total = await db.scalar(select(func.count()).select_from(Message).where(*cond)) or 0
    rows = (
        await db.execute(
            select(Message).where(*cond).order_by(Message.id.desc())
            .offset((page - 1) * size).limit(size)
        )
    ).scalars().all()
    return list(rows), int(total)


async def unread_count(db: AsyncSession, user_id: int) -> int:
    """未读消息数（顶栏与菜单角标用）。"""
    return int(
        await db.scalar(
            select(func.count()).select_from(Message)
            .where(Message.user_id == user_id, Message.is_read == 0, Message.deleted_at.is_(None))
        ) or 0
    )


async def mark_read(db: AsyncSession, user_id: int, message_id: int) -> None:
    """单条已读；不存在则 404，避免前端静默失败。"""
    msg = await db.get(Message, message_id)
    if msg is None or msg.user_id != user_id or msg.deleted_at is not None:
        raise NotFoundError("消息不存在")
    if msg.is_read == 0:
        msg.is_read = 1
        msg.read_at = datetime.now()
        await db.flush()


async def mark_all_read(db: AsyncSession, user_id: int) -> int:
    """全部已读，返回影响条数。"""
    result = await db.execute(
        update(Message)
        .where(Message.user_id == user_id, Message.is_read == 0, Message.deleted_at.is_(None))
        .values(is_read=1, read_at=datetime.now())
    )
    await db.flush()
    return int(result.rowcount or 0)


async def remove_message(db: AsyncSession, user_id: int, message_id: int) -> None:
    """删除消息（逻辑删除）。"""
    msg = await db.get(Message, message_id)
    if msg is None or msg.user_id != user_id:
        raise NotFoundError("消息不存在")
    msg.deleted_at = datetime.now()
    await db.flush()
