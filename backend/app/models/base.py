"""ORM 基类。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    # 注意：必须同时设置 Python 侧 default 与 DB 侧 server_default。
    # 只给 server_default 会导致 flush 后该属性处于"未加载"状态，
    # 在 async 场景下于 await 上下文之外访问会触发惰性加载 → MissingGreenlet。
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, server_default=func.now(), nullable=False, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now,
        server_default=func.now(), nullable=False, comment="更新时间"
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, comment="逻辑删除时间")
