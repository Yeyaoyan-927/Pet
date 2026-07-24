"""AI 对话助手接口（多 Agent 协作 + ReAct，SSE 流式输出）。"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.react import AgentRunner
from app.agent.tools.registry import tool_manifest
from app.config import settings
from app.database import AsyncSessionLocal, get_db
from app.deps.auth import get_current_user
from app.models import User
from app.schemas.common import ok
from app.services import chat_service, session_lock
from app.utils.exceptions import AuthError
from app.utils.logger import logger

router = APIRouter(prefix="/chat", tags=["AI 对话助手"])


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=1000, description="用户消息")
    session_id: int | None = Field(default=None, description="会话 ID，为空则使用/新建当前活跃会话")


class SessionIn(BaseModel):
    title: str | None = Field(default=None, max_length=120)


@router.get("/sessions", summary="会话列表")
async def list_sessions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """会话列表。"""
    return ok(await chat_service.list_sessions(db, user.id))


@router.post("/sessions", summary="新建会话")
async def create_session(
    payload: SessionIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """新建会话。"""
    session = await chat_service.create_session(db, user.id, payload.title)
    return ok({"id": session.id, "title": session.title})


@router.get("/sessions/{session_id}/messages", summary="会话消息历史")
async def session_messages(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """会话消息历史。"""
    session = await chat_service.get_or_404(db, session_id, user.id)
    return ok({"session_id": session.id, "title": session.title,
               "messages": await chat_service.list_messages(db, session.id)})


@router.delete("/sessions/{session_id}", summary="删除会话（逻辑删除）")
async def delete_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除会话（逻辑删除）。"""
    session = await chat_service.get_or_404(db, session_id, user.id)
    await chat_service.remove_session(db, session)
    return ok(None, "会话已删除")


@router.get("/capabilities", summary="助手能力与工具清单（按当前角色返回）")
async def capabilities(user: User = Depends(get_current_user)):
    """助手能力与工具清单（按当前角色返回）。"""
    from app.agent.agents import agent_manifest
    from app.agent.tools.profiles import (
        ROLE_CAPABILITY_SUMMARY,
        ROLE_EXAMPLES,
        ROLE_PROFILE_NAME,
    )
    from app.agent.tools.registry import can_invoke

    # 双重过滤：先按角色取画像内的工具清单，再用 can_invoke 复核（防配置漂移）
    tools = [t for t in tool_manifest(user.role) if can_invoke(t["name"], user)]
    return ok({
        "llm_available": settings.llm_available,
        "model": settings.LLM_MODEL if settings.llm_available else None,
        "max_steps": settings.AGENT_MAX_STEPS,
        "architecture": (
            "多 Agent 协作：路由调度 + 领域子 Agent + 合规风控，共用一套 ReAct 执行内核；"
            "不引入 CrewAI / AutoGen，跨域协同由路由层显式编排"
        ),
        "role": user.role,
        "role_profile": ROLE_PROFILE_NAME.get(user.role, "助手"),
        "capability_summary": ROLE_CAPABILITY_SUMMARY.get(user.role, ""),
        # 当前端可激活的 Agent（路由与风控对所有端恒在，领域 Agent 按端裁剪）
        "agents": agent_manifest(user.role),
        "tools": tools,
        "examples": ROLE_EXAMPLES.get(user.role, []),
    })


@router.get("/tool-profile", summary="[运维] 查看三角色工具画像（仅店长）")
async def tool_profile(user: User = Depends(get_current_user)):
    """[运维] 查看三角色工具画像（仅店长）。"""
    from app.agent.tools.profiles import ROLE_PROFILE_NAME, ROLE_TOOL_PROFILE

    if user.role != "manager":
        from app.utils.exceptions import PermissionError_

        raise PermissionError_("仅店长可查看工具画像")
    return ok({
        "pool_size": len(tool_manifest()),
        "profiles": {
            role: {
                "name": ROLE_PROFILE_NAME.get(role, role),
                "count": len(names),
                "tools": list(names),
            }
            for role, names in ROLE_TOOL_PROFILE.items()
        },
    })


@router.post("/message", summary="发送消息（SSE 流式返回思考 / 工具调用 / 回答）")
async def send_message(
    payload: MessageIn,
    request: Request,
    user: User = Depends(get_current_user),
):
    """发送消息（SSE 流式返回思考 / 工具调用 / 回答）。"""
    async def event_stream() -> AsyncGenerator[bytes, None]:
        """独立会话生命周期：SSE 期间不能复用请求级 session（会被提前关闭）。"""
        locked_session_id: int | None = None
        async with AsyncSessionLocal() as db:
            try:
                if payload.session_id:
                    session = await chat_service.get_or_404(db, payload.session_id, user.id)
                else:
                    session = await chat_service.get_or_create_active(db, user.id)

                # 会话级并发锁：同一会话的并发消息必须串行，否则两条 ReAct 循环
                # 会各自跑一遍写工具（用户连点两次确认 → 可能落两笔业务数据）
                if not await session_lock.acquire(session.id):
                    yield f"data: {json.dumps({'type': 'error', 'message': '上一条消息还在处理中，请稍等片刻再发 🐾'}, ensure_ascii=False)}\n\n".encode()
                    return
                locked_session_id = session.id

                runner = AgentRunner(db, user, request)
                async for event in runner.stream(session, payload.content):
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n".encode()
            except AuthError as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': exc.message}, ensure_ascii=False)}\n\n".encode()
            except Exception as exc:  # pragma: no cover - 兜底，保证流能正常结束
                logger.error("chat stream failed: %s", exc)
                yield f"data: {json.dumps({'type': 'error', 'message': '助手暂时不可用，请稍后重试'}, ensure_ascii=False)}\n\n".encode()
            finally:
                if locked_session_id is not None:
                    session_lock.release(locked_session_id)
                yield b"data: {\"type\": \"end\"}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/purge", summary="[运维] 按留存策略清理超期会话（仅店长）")
async def purge(
    days: int | None = Query(None, description="留存天数，默认取门店配置 session_retention_days"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """[运维] 按留存策略清理超期会话（仅店长）。"""
    from app.constants import UserRole
    from app.services import setting_service
    from app.utils.exceptions import PermissionError_

    if user.role != UserRole.MANAGER.value:
        raise PermissionError_("仅店长可执行清理")
    retention = days or await setting_service.get_int(db, "session_retention_days")
    removed = await chat_service.purge_expired(db, retention)
    return ok({"removed": removed, "retention_days": retention}, "清理完成")
