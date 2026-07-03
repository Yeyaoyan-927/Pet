"""风险报告快照表。V1 由规则引擎生成，V3 接入 LLM-RAG 增强。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class RiskReport(Base, TimestampMixin):
    __tablename__ = "risk_report"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    appointment_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="预约 ID")
    pet_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="宠物 ID")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="none",
                                            comment="high / low / none")
    engine_type: Mapped[str] = mapped_column(String(16), nullable=False, default="rule",
                                             comment="rule / llm")
    risk_items: Mapped[str | None] = mapped_column(Text, comment="命中风险项，JSON 数组")
    ai_summary: Mapped[str | None] = mapped_column(Text, comment="风险摘要")
    knowledge_refs: Mapped[str | None] = mapped_column(Text, comment="引用知识片段，JSON 数组")
    suggestion: Mapped[str | None] = mapped_column(Text, comment="处置建议")
    confirmed: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, comment="店员是否已复核")
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger, comment="复核店员 ID")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, comment="复核时间")
    handle_measure: Mapped[str | None] = mapped_column(Text, comment="店员处置措施")
    invalidated: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0,
                                             comment="1 表示因预约超时取消而失效")
