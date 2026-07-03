"""定时任务执行记录表。

一表两用：
1. **持久化执行状态** —— 进程重启后据此判断「距上次执行是否已超过间隔」，避免立刻重跑；
2. **多实例互斥** —— 执行前对本表对应行加 `FOR UPDATE NOWAIT`，拿不到锁说明别的实例在跑，
   立即跳过（不等待、不重复执行），这样无需 Redis 也能安全多开。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class TaskRun(Base, TimestampMixin):
    __tablename__ = "task_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, comment="任务名（与 JOBS 注册表一致）")
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime, comment="上次开始时间")
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime, comment="上次结束时间")
    last_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", comment="success / failed / skipped / pending"
    )
    last_summary: Mapped[str | None] = mapped_column(String(255), comment="上次执行结果摘要")
    last_trigger: Mapped[str] = mapped_column(
        String(16), nullable=False, default="schedule", comment="schedule 调度触发 / manual 手动触发"
    )
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="累计执行次数")
