"""用户表。手机号 AES 可逆加密存储，page 展示时脱敏。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="登录账号")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="bcrypt 哈希")
    real_name: Mapped[str | None] = mapped_column(String(50), comment="姓名 / 昵称")
    phone_encrypted: Mapped[str | None] = mapped_column(String(255), comment="手机号 AES 密文")
    phone_hash: Mapped[str | None] = mapped_column(String(64), index=True, comment="手机号 HMAC 索引，用于查重")
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="customer", index=True,
                                      comment="customer / staff / manager")
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="1 启用 / 0 禁用")
    is_temp: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0,
                                         comment="1 表示代客预约创建的临时用户")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, comment="最后登录时间")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, comment="逻辑删除时间")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} username={self.username} role={self.role}>"
