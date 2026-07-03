"""审计日志表：记录操作前后快照、IP、UA。"""
from __future__ import annotations

from sqlalchemy import BigInteger, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class OperationLog(Base, TimestampMixin):
    __tablename__ = "operation_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="操作账号 ID")
    staff_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="操作店员 ID")
    module: Mapped[str] = mapped_column(String(32), nullable=False, comment="业务模块")
    action: Mapped[str] = mapped_column(String(64), nullable=False, comment="操作动作")
    biz_id: Mapped[int | None] = mapped_column(BigInteger, comment="业务主键")
    before_snapshot: Mapped[str | None] = mapped_column(Text, comment="操作前 JSON 快照")
    after_snapshot: Mapped[str | None] = mapped_column(Text, comment="操作后 JSON 快照")
    ip: Mapped[str | None] = mapped_column(String(64), comment="客户端 IP")
    user_agent: Mapped[str | None] = mapped_column(String(255), comment="User-Agent")
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="1 成功 / 0 失败")
    detail: Mapped[str | None] = mapped_column(String(500), comment="补充说明")
