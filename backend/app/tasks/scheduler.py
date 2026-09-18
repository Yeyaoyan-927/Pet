"""进程内置定时任务调度器。

为什么不用 arq + Redis：
- 本项目的定时任务只有 5 个、频次低（15 分钟 ~ 1 天），arq 带来的 Redis 依赖对开发与交付是净负担；
- 但**能力不能不补**：SLA 超时自动取消、临期提醒、会话清理都是规划书 P0 的能力项。

因此这里只承担「按时触发」这一件事，任务逻辑全部在 `app/tasks/jobs.py`：
`run_job()` 自带行锁互斥与执行记录，换 arq 时把 `JOBS` 注册成 worker 任务即可，业务代码零改动。

单实例保证：靠 `task_run` 行锁实现（见 jobs.run_job），不依赖调度器自身状态。
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from app.config import settings
from app.database import AsyncSessionLocal
from app.tasks.jobs import JOBS, run_job
from app.utils.logger import logger

# 调度心跳：每 30 秒检查一次是否有任务到点
TICK_SECONDS = 30
# 启动后延迟首轮触发，避开启动事务与连接池预热
STARTUP_DELAY_SECONDS = 30


class TaskScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_run: dict[str, datetime] = {}
        self.started_at: datetime | None = None
        self.tick_count = 0

    @property
    def running(self) -> bool:
        """调度器是否在运行（运维接口与测试用）。


        """
        return self._task is not None and not self._task.done()

    async def _tick(self) -> None:
        """一轮检查：到点的任务顺序执行（顺序而非并发，避免同时写库互相加锁）。"""
        from app.tasks.jobs import interval_minutes

        for name in JOBS:
            interval = interval_minutes(name)
            last = self._last_run.get(name)
            if last is not None and (datetime.now() - last).total_seconds() < interval * 60:
                continue
            self._last_run[name] = datetime.now()
            async with AsyncSessionLocal() as db:
                result = await run_job(db, name, trigger="schedule")
            logger.info(
                "task_tick",
                extra={"extra_fields": {"task": name, "status": result.get("status"),
                                        "summary": result.get("summary", "")[:120]}},
            )

    async def _loop(self) -> None:
        self.started_at = datetime.now()
        await asyncio.sleep(STARTUP_DELAY_SECONDS)
        while not self._stop.is_set():
            self.tick_count += 1
            try:
                await self._tick()
            except Exception as exc:  # 调度器自身永不退出
                logger.error("task_scheduler_error: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=TICK_SECONDS)
            except asyncio.TimeoutError:
                pass

    def start(self) -> None:
        """启动内置调度器：为每个任务建一个周期协程，首次触发延迟一个间隔，避免启动瞬间全量开跑。


        """
        if not settings.TASK_SCHEDULER_ENABLED:
            logger.info("task_scheduler_disabled")
            return
        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())
        logger.info("task_scheduler_started",
                    extra={"extra_fields": {"jobs": list(JOBS.keys())}})

    async def stop(self) -> None:
        """停止调度器并等待协程退出（应用关闭时调用）。


        """
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
        logger.info("task_scheduler_stopped")


scheduler = TaskScheduler()
