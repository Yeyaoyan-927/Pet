"""站内消息表：支持已读标记与逻辑删除。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Message(Base, TimestampMixin):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="接收用户")
    title: Mapped[str] = mapped_column(String(120), nullable=False, comment="标题")
    content: Mapped[str | None] = mapped_column(Text, comment="内容")
    msg_type: Mapped[str] = mapped_column(String(32), nullable=False, default="system", comment="消息类型")
    biz_id: Mapped[int | None] = mapped_column(BigInteger, comment="关联业务 ID")
    is_read: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, comment="1 已读")
    read_at: Mapped[datetime | None] = mapped_column(DateTime, comment="已读时间")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, comment="逻辑删除时间")
