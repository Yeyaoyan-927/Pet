"""LLM 客户端（阿里云百炼 / DashScope，OpenAI 兼容模式）。

设计要点
--------
1. **模型来源**：百炼控制台「费用与配额 - 免费额度」页面上的免费额度模型。
   免费清单会随活动变动，因此通过 `.env` 配置**免费模型链**，不把型号硬编码进业务代码。
2. **零额外依赖**：直接使用 httpx 调用 OpenAI 兼容的 `/chat/completions`，
   不引入 openai SDK，减少依赖面。
3. **强制降级**：未配置 API Key、超时、报错、返回非法结构 → 一律返回
   `LLMResult(ok=False)`，由调用方回退到规则引擎，业务永不阻塞。
4. **安全铁律**：本模块只产出**文本与结构化建议**，不触碰数据库、不拼 SQL。
   任何写操作必须回到业务服务层执行。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings
from app.utils.logger import logger

JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


@dataclass
class LLMResult:
    ok: bool
    model: str = ""
    content: str = ""
    error: str | None = None
    latency_ms: int = 0
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def data(self) -> dict | None:
        """把 content 解析为 JSON；解析失败返回 None（调用方据此回退）。"""
        return extract_json(self.content)


def extract_json(text: str | None) -> dict | None:
    """从 LLM 输出中稳健提取 JSON 对象。

    兼容三种常见形态：纯 JSON、```json 围栏、前后夹带自然语言。
    解析失败返回 None，绝不抛异常。
    """
    if not text:
        return None
    candidate = text.strip()
    fence = JSON_FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        pass
    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(candidate[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            return None
    return None


class BailianClient:
    """百炼免费额度模型客户端：免费模型链 + 自动回退。"""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    # ---------- 基础属性 ----------
    @property
    def enabled(self) -> bool:
        """是否具备调用条件（开关打开且配置了 Key）。


        """
        return settings.llm_available

    @property
    def model_chain(self) -> list[str]:
        """当前生效的模型链：主模型在前，备选依次回退。


        """
        return settings.llm_model_chain

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}",
            "Content-Type": "application/json",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=settings.LLM_BASE_URL,
                timeout=httpx.Timeout(settings.LLM_TIMEOUT_SECONDS),
            )
        return self._client

    async def close(self) -> None:
        """关闭底层 httpx 连接池（应用退出时调用）。


        """
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    # ---------- 单模型调用 ----------
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResult:
        """调用一次模型：按 LLM_MAX_RETRIES 重试，鉴权类错误（401/403/404）不再换模型。


            失败不抛异常，返回 ok=False 的 LLMResult，由调用方决定降级策略。
        """
        if not self.enabled:
            return LLMResult(ok=False, error="LLM 未启用或未配置 DASHSCOPE_API_KEY")

        target = model or settings.LLM_MODEL
        payload: dict[str, Any] = {
            "model": target,
            "messages": messages,
            "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
            "max_tokens": settings.LLM_MAX_TOKENS if max_tokens is None else max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        client = await self._get_client()
        started = time.perf_counter()
        last_error: str | None = None

        for attempt in range(settings.LLM_MAX_RETRIES + 1):
            try:
                resp = await client.post("/chat/completions", json=payload, headers=self._headers())
                latency = int((time.perf_counter() - started) * 1000)
                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    logger.warning(
                        "llm_call_failed",
                        extra={"extra_fields": {"model": target, "attempt": attempt,
                                                "status": resp.status_code}},
                    )
                    if resp.status_code in (401, 403, 404):
                        break
                    continue
                body = resp.json()
                choice = (body.get("choices") or [{}])[0]
                content = (choice.get("message") or {}).get("content") or ""
                return LLMResult(
                    ok=True, model=target, content=content, latency_ms=latency,
                    usage=body.get("usage") or {},
                )
            except (httpx.HTTPError, ValueError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "llm_call_error",
                    extra={"extra_fields": {"model": target, "attempt": attempt, "error": str(exc)[:160]}},
                )

        return LLMResult(ok=False, model=target, error=last_error or "未知错误")

    # ---------- 免费模型链 + 回退 ----------
    async def chat_with_fallback(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        """按免费模型链依次尝试；全部失败则返回最后一次错误，由调用方回退规则引擎。"""
        chain = [model] if model else self.model_chain
        last = LLMResult(ok=False, error="模型链为空")
        for candidate in chain:
            result = await self.chat(
                messages, model=candidate, json_mode=json_mode,
                temperature=temperature, max_tokens=max_tokens,
            )
            if result.ok:
                return result
            last = result
            # 鉴权类错误无需继续换模型
            if result.error and ("HTTP 401" in result.error or "HTTP 403" in result.error):
                break
        return last

    # ---------- 健康探测 ----------
    async def health(self, *, probe: bool = False) -> dict[str, Any]:
        """返回可用性状态。probe=True 时真实调用一次主模型做端到端探测。

        安全：任何情况下都不返回 API Key 明文。
        """
        status: dict[str, Any] = {
            "provider": settings.LLM_PROVIDER,
            "enabled": settings.LLM_ENABLED,
            "api_key_configured": bool(settings.DASHSCOPE_API_KEY.strip()),
            "available": settings.llm_available,
            "base_url": settings.LLM_BASE_URL,
            "primary_model": settings.LLM_MODEL,
            "model_chain": self.model_chain,
            "note": "模型来自阿里云百炼「费用与配额 - 免费额度」页面；清单会随活动调整，请通过 .env 覆盖",
        }
        if not probe:
            return status
        if not settings.llm_available:
            status["probe"] = {"ok": False, "error": "未配置 DASHSCOPE_API_KEY，已降级为规则引擎"}
            return status

        result = await self.chat_with_fallback(
            [{"role": "user", "content": "ping，请只回复 pong"}],
            max_tokens=16, temperature=0,
        )
        status["probe"] = {
            "ok": result.ok,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "usage": result.usage,
            "reply": (result.content or "")[:40],
            "error": result.error,
        }
        return status


bailian_client = BailianClient()


async def probe_free_models() -> list[dict[str, Any]]:
    """逐个探测免费模型链，返回每个模型的可用性（供 scripts/check_llm.py 使用）。"""
    if not settings.llm_available:
        return [{"model": m, "ok": False, "error": "未配置 DASHSCOPE_API_KEY"} for m in settings.llm_model_chain]

    async def one(model: str) -> dict[str, Any]:
        """探测单个模型可用性（check_llm 与 probe 接口用）。


        """
        res = await bailian_client.chat(
            [{"role": "user", "content": "ping"}], model=model, max_tokens=8, temperature=0
        )
        return {
            "model": model, "ok": res.ok, "latency_ms": res.latency_ms,
            "usage": res.usage, "error": res.error,
        }

    return list(await asyncio.gather(*(one(m) for m in settings.llm_model_chain)))
