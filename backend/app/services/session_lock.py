"""会话级并发锁（V8）。

**为什么需要**：同一会话里两条消息并发进来时，两条 ReAct 循环会交替读写 `chat_session.pending`
与消息历史，可能各自跑一遍工具调用 —— 用户点了两次"确认下单"，就可能落两笔业务数据。

**实现取舍**：用进程内 `asyncio.Lock`，零新增中间件。
- 优点：无依赖、无额外 RTT，单进程部署下语义正确；
- 限制：**只对本进程生效**。多 worker / 多实例部署时需换成 Redis 分布式锁
  （或数据库 `GET_LOCK`），见 `docs/09-运维手册与上线检查清单.md` 的「已知限制」。
  当前部署形态是单进程（`uvicorn` 单 worker），因此这一层足够。

**等待而非直接拒绝**：用户连点时，后一条消息等前一条跑完再处理，比直接报错体验更好；
但必须设上限，否则前端会长时间转圈 —— 超时后返回一条友好提示，并提示"上一条还在处理"。
"""

from __future__ import annotations

import asyncio

from app.config import settings
from app.utils.logger import logger


class _Entry:
    """一个会话的锁 + 等待者计数（计数归零后回收，避免字典无限增长）。"""

    __slots__ = ("lock", "waiters")

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.waiters = 0


_registry: dict[int, _Entry] = {}


def _entry(session_id: int) -> _Entry:
    """取（或新建）某会话的锁条目，并登记一个等待者。


    """
    entry = _registry.get(session_id)
    if entry is None:
        entry = _Entry()
        _registry[session_id] = entry
    entry.waiters += 1
    return entry


def _drop_if_idle(session_id: int, entry: _Entry) -> None:
    """等待者归零且锁未被占用时回收条目，避免注册表随会话数无限增长。


    """
    entry.waiters -= 1
    if entry.waiters <= 0 and not entry.lock.locked():
        _registry.pop(session_id, None)


async def acquire(session_id: int) -> bool:
    """尝试占用会话锁。

    返回 `True` 表示已持有（调用方**必须**在 finally 里 `release`）；
    返回 `False` 表示等待超时（调用方应回一条"上一条还在处理"的提示，且**不要** release）。
    锁功能被关闭时同样返回 `True`，让调用方的释放逻辑保持统一（release 内部幂等）。
    """
    if not settings.CHAT_SESSION_LOCK_ENABLED:
        return True

    entry = _entry(session_id)
    try:
        await asyncio.wait_for(entry.lock.acquire(), timeout=settings.CHAT_SESSION_LOCK_WAIT_SECONDS)
    except asyncio.TimeoutError:
        _drop_if_idle(session_id, entry)
        logger.warning(
            "chat_session_busy",
            extra={"extra_fields": {"session_id": session_id}},
        )
        return False
    # 抢到锁后等待者计数由 release 负责回收
    entry.waiters -= 1
    return True


def release(session_id: int) -> None:
    """释放会话锁。未持有或功能关闭时是空操作，可安全重复调用。"""
    entry = _registry.get(session_id)
    if entry is None:
        return
    if entry.lock.locked():
        entry.lock.release()
    if entry.waiters <= 0 and not entry.lock.locked():
        _registry.pop(session_id, None)


def reset() -> None:
    """清空注册表（仅测试用，避免用例之间互相影响）。"""
    _registry.clear()


def snapshot() -> dict[str, int]:
    """当前锁状态（运维排查用）。"""
    return {
        "sessions": len(_registry),
        "locked": sum(1 for e in _registry.values() if e.lock.locked()),
        "waiting": sum(e.waiters for e in _registry.values()),
    }
