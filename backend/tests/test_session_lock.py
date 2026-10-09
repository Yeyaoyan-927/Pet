"""会话级并发锁用例（V8）。

锁的价值在「同一会话的并发消息必须串行」，因此这里直接对锁本身做并发验证：
① 同一会话第二个请求会等待并最终超时；② 不同会话互不影响；③ 释放后注册表能回收。
"""

from __future__ import annotations

import asyncio

import pytest

from app.config import settings
from app.services import session_lock


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    session_lock.reset()
    monkeypatch.setattr(settings, "CHAT_SESSION_LOCK_ENABLED", True)
    # 缩短等待时间，避免用例为了等超时耗时过长
    monkeypatch.setattr(settings, "CHAT_SESSION_LOCK_WAIT_SECONDS", 1)
    yield
    session_lock.reset()


async def test_same_session_serialized():
    """同一会话：持有者未释放时，第二个请求必须等不到锁。"""
    session_id = 90001
    assert await session_lock.acquire(session_id) is True

    async def second() -> bool:
        return await session_lock.acquire(session_id)

    assert await second() is False, "同一会话并发必须被挡住，不能两条消息同时跑"

    session_lock.release(session_id)
    assert await session_lock.acquire(session_id) is True, "释放后应当可以立即再次获取"
    session_lock.release(session_id)
    assert session_lock.snapshot()["sessions"] == 0, "全部释放后注册表应回收，避免长期运行内存增长"


async def test_different_sessions_independent():
    """不同会话互不阻塞：一个用户卡住不该拖慢其他用户。"""
    assert await session_lock.acquire(90002) is True
    assert await session_lock.acquire(90003) is True
    snap = session_lock.snapshot()
    assert snap["locked"] == 2
    session_lock.release(90002)
    session_lock.release(90003)
    assert session_lock.snapshot()["sessions"] == 0


async def test_waiting_request_gets_lock_after_release():
    """等待中的请求在锁释放后应当能拿到锁（等得到，不是直接失败）。"""
    session_id = 90004
    assert await session_lock.acquire(session_id) is True

    async def later() -> bool:
        await asyncio.sleep(0.4)
        return await session_lock.acquire(session_id)

    task = asyncio.create_task(later())
    await asyncio.sleep(0.6)
    session_lock.release(session_id)
    assert await task is True, "等待方应在持有方释放后拿到锁"
    session_lock.release(session_id)


async def test_disabled_lock_is_transparent(monkeypatch):
    """关闭开关后行为应完全透明（用于排查锁导致的卡顿）。"""
    monkeypatch.setattr(settings, "CHAT_SESSION_LOCK_ENABLED", False)
    assert await session_lock.acquire(90005) is True
    assert await session_lock.acquire(90005) is True
    session_lock.release(90005)  # 空操作，不应抛错
