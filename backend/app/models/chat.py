"""AI 对话会话与消息表（中心单 Agent + ReAct，V4 能力提前落地）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_session"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="会话归属用户")
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="新的对话", comment="会话标题")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active",
                                        comment="active / closed")
    pending_action: Mapped[str | None] = mapped_column(Text, comment="待二次确认的写操作，JSON 字符串")
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="对话轮次")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, comment="最后消息时间")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, comment="逻辑删除时间")


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_message"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="会话 ID")
    user_id: Mapped[int | None] = mapped_column(BigInteger, comment="消息归属用户")
    role: Mapped[str] = mapped_column(String(16), nullable=False,
                                      comment="user / assistant / tool / system")
    content: Mapped[str | None] = mapped_column(Text, comment="消息内容（已脱敏）")
    intent: Mapped[str | None] = mapped_column(String(32), comment="识别出的意图")
    tool_name: Mapped[str | None] = mapped_column(String(64), comment="工具名")
    tool_args: Mapped[str | None] = mapped_column(Text, comment="工具入参 JSON")
    tool_result: Mapped[str | None] = mapped_column(Text, comment="工具出参 JSON")
    step: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, comment="ReAct 轮次")
    model: Mapped[str | None] = mapped_column(String(64), comment="使用的模型名")
    latency_ms: Mapped[int | None] = mapped_column(Integer, comment="耗时（毫秒）")
