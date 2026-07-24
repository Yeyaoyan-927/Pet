"""Agent / LLM 运维接口。

V1 提供 LLM 接入层可用性探测；V4 已交付 ReAct 对话入口（SSE，见 routers/chat.py）。
所有接口均不返回 API Key 明文。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.agent.llm.client import bailian_client, probe_free_models
from app.deps.auth import get_staff_user, get_manager_user
from app.models import User
from app.schemas.common import ok

router = APIRouter(prefix="/agent", tags=["Agent / LLM"])


@router.get("/llm/status", summary="LLM 接入状态（含可选端到端探测）")
async def llm_status(
    probe: bool = Query(False, description="是否真实调用一次主模型做端到端探测"),
    _: User = Depends(get_staff_user),
):
    """LLM 接入状态（含可选端到端探测）。"""
    return ok(await bailian_client.health(probe=probe))


@router.get("/llm/probe-models", summary="逐个探测免费模型链可用性（仅店长）")
async def llm_probe_models(_: User = Depends(get_manager_user)):
    """逐个探测免费模型链可用性（仅店长）。"""
    results = await probe_free_models()
    return ok({
        "chain": bailian_client.model_chain,
        "results": results,
        "ok_count": sum(1 for r in results if r.get("ok")),
    }, "探测完成")


@router.get("/architecture", summary="Agent 架构约定（前端展示用）")
async def architecture(_: User = Depends(get_staff_user)):
    """Agent 架构约定（前端展示用）。"""
    return ok({
        "pattern": "中心单 Agent + ReAct",
        "workflow": "业务闭环使用状态机 / Graph Workflow",
        "forbidden": ["CrewAI", "AutoGen", "多 Agent 协作"],
        "write_policy": "LLM 绝不直接写库；写操作一律通过工具调用业务服务层，经权限/状态机/事务/审计",
        "llm_provider": "阿里云百炼（DashScope）免费额度模型，OpenAI 兼容模式",
        "max_steps": 6,
        "note": "V4 已落地 ReAct 循环与 8 个工具集；V5 计划扩展到店员端与店长端工具画像",
    })
