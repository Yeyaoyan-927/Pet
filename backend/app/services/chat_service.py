"""AI 对话会话服务。会话按门店配置 `session_retention_days` 留存，敏感内容入库前脱敏。"""
from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessage, ChatSession
from app.utils.exceptions import NotFoundError


async def create_session(db: AsyncSession, user_id: int, title: str | None = None) -> ChatSession:
    """新建会话（同时把同一用户的其它会话置为非活跃）。"""
    session = ChatSession(
        user_id=user_id,
        title=(title or "新的对话")[:120],
    )
    db.add(session)
    await db.flush()
    await db.commit()
    await db.refresh(session)
    return session


async def get_or_404(db: AsyncSession, session_id: int, user_id: int) -> ChatSession:
    """取会话并校验归属，越权与不存在都按 404 处理（不泄露存在性）。"""
    session = await db.get(ChatSession, session_id)
    if session is None or session.deleted_at is not None or session.user_id != user_id:
        raise NotFoundError("会话不存在")
    return session


async def get_or_create_active(db: AsyncSession, user_id: int) -> ChatSession:
    """取当前活跃会话，没有则新建——对话页刷新不该丢上下文。"""
    session = (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id, ChatSession.deleted_at.is_(None),
                   ChatSession.status == "active")
            .order_by(ChatSession.id.desc())
        )
    ).scalars().first()
    if session is None:
        session = await create_session(db, user_id)
    return session


async def list_sessions(db: AsyncSession, user_id: int, limit: int = 30) -> list[dict]:
    """会话列表（仅未删除，按最近更新排序）。"""
    rows = (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id, ChatSession.deleted_at.is_(None))
            .order_by(ChatSession.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    out = []
    for s in rows:
        last = (
            await db.execute(
                select(ChatMessage.content)
                .where(ChatMessage.session_id == s.id, ChatMessage.role.in_(["user", "assistant"]))
                .order_by(ChatMessage.id.desc())
                .limit(1)
            )
        ).scalars().first()
        out.append({
            "id": s.id,
            "title": s.title,
            "status": s.status,
            "turn_count": s.turn_count,
            "last_message_at": s.last_message_at,
            "preview": (last or "")[:60],
            "created_at": s.created_at,
        })
    return out


def _refs_of(message: ChatMessage) -> list[dict] | None:
    """从知识问答消息里还原「检索到的片段」，供历史回看时展开。

    片段随 `tool_result` 一起落库（无需新增列）；解析失败就当没有依据，
    不能让一条历史消息因为格式问题打不开。
    """
    if message.role != "assistant" or message.tool_name != "search_knowledge":
        return None
    if not message.tool_result:
        return None
    try:
        data = json.loads(message.tool_result)
    except (TypeError, ValueError):
        return None
    items = data.get("items") if isinstance(data, dict) else None
    if not items:
        return None
    refs: list[dict] = []
    for item in items[:5]:
        body = re.sub(r"^#+\s*", "", (item.get("content") or "")).strip()
        refs.append({
            "title": item.get("title") or "门店规范",
            "section": (item.get("section") or "").strip(),
            "source": item.get("source") or "门店规范",
            "content": body[:260],
            "matched": "、".join((item.get("matched") or [])[:2]),
        })
    return refs or None


async def list_messages(db: AsyncSession, session_id: int, limit: int = 100) -> list[dict]:
    """会话消息历史，返回 (消息列表, 总数)。"""
    rows = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id, ChatMessage.role.in_(["user", "assistant"]))
            .order_by(ChatMessage.id.asc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "intent": m.intent,
            "tool_name": m.tool_name,
            "refs": _refs_of(m),
            "created_at": m.created_at,
        }
        for m in rows
    ]


async def remove_session(db: AsyncSession, session: ChatSession) -> None:
    """删除会话：**逻辑删除**，保留数据以便留存期内可追溯。"""
    session.deleted_at = datetime.now()
    session.status = "closed"
    await db.flush()
    await db.commit()


async def rename_session(db: AsyncSession, session: ChatSession, title: str) -> ChatSession:
    """重命名会话，标题按 120 字截断防超长。"""
    session.title = title[:120]
    await db.flush()
    await db.commit()
    return session


async def clear_pending(db: AsyncSession, session: ChatSession) -> None:
    """清空「待确认」动作（用户取消写操作或切换话题时调用）。"""
    session.pending_action = None
    await db.flush()
    await db.commit()


async def purge_expired(db: AsyncSession, retention_days: int) -> int:
    """物理删除超期会话（V4 arq 定时调用；此处可手动触发）。"""
    from datetime import timedelta

    from app.models import ChatMessage as CM

    deadline = datetime.now() - timedelta(days=retention_days)
    sessions = (
        await db.execute(select(ChatSession).where(ChatSession.created_at <= deadline))
    ).scalars().all()
    if not sessions:
        return 0
    ids = [s.id for s in sessions]
    await db.execute(CM.__table__.delete().where(CM.session_id.in_(ids)))
    await db.execute(ChatSession.__table__.delete().where(ChatSession.id.in_(ids)))
    await db.commit()
    return len(ids)


async def stats(db: AsyncSession, user_id: int) -> dict:
    """会话统计：会话数 / 消息数 / 近 7 日活跃。"""
    total = await db.scalar(
        select(func.count()).select_from(ChatSession).where(
            ChatSession.user_id == user_id, ChatSession.deleted_at.is_(None)
        )
    )
    return {"sessions": int(total or 0)}
