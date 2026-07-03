"""门店业务配置表：所有门店级业务参数，禁止硬编码。"""
from __future__ import annotations

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class StoreSetting(Base, TimestampMixin):
    __tablename__ = "store_setting"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    setting_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="配置键")
    setting_value: Mapped[str] = mapped_column(String(255), nullable=False, comment="配置值（字符串存储）")
    value_type: Mapped[str] = mapped_column(String(16), nullable=False, default="string",
                                            comment="int / bool / string")
    default_value: Mapped[str] = mapped_column(String(255), nullable=False, comment="默认值，非法时回退")
    setting_desc: Mapped[str | None] = mapped_column(String(255), comment="中文说明")
