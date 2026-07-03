"""洗护记录 + 洗护照片（V1 照片仅落库路径，文件上传接口预留）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WashRecord(Base, TimestampMixin):
    __tablename__ = "wash_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    appointment_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, comment="预约 ID")
    pet_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="宠物 ID")
    staff_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="执行店员")
    service_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="服务类型")
    wash_start: Mapped[datetime | None] = mapped_column(DateTime, comment="开始时间")
    wash_end: Mapped[datetime | None] = mapped_column(DateTime, comment="结束时间")
    skin_condition: Mapped[str | None] = mapped_column(Text, comment="洗护后皮肤状况")
    hair_condition: Mapped[str | None] = mapped_column(Text, comment="毛发状况")
    products: Mapped[str | None] = mapped_column(String(255), comment="使用产品")
    staff_note: Mapped[str | None] = mapped_column(Text, comment="店员记录")
    photo_paths: Mapped[str | None] = mapped_column(Text, comment="照片相对路径，JSON 数组字符串")
