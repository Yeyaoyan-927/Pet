"""宠物档案 + 疫苗驱虫记录。"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Pet(Base, TimestampMixin):
    __tablename__ = "pet"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="归属宠主")
    staff_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="归属店员（本人服务客户）")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="宠物名")
    species: Mapped[str] = mapped_column(String(20), nullable=False, default="dog", comment="dog / cat")
    breed: Mapped[str | None] = mapped_column(String(50), comment="品种")
    gender: Mapped[str] = mapped_column(String(10), nullable=False, default="male", comment="male / female")
    birthday: Mapped[date | None] = mapped_column(Date, comment="生日")
    weight: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="体重 kg")
    sterilized: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, comment="是否绝育")
    allergy: Mapped[str | None] = mapped_column(Text, comment="过敏史")
    skin_disease: Mapped[str | None] = mapped_column(Text, comment="皮肤病史")
    stress_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0,
                                              comment="应激等级 0 无 / 1 轻 / 2 中 / 3 重")
    aggressive: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, comment="攻击倾向标记")
    emergency_contact: Mapped[str | None] = mapped_column(String(50), comment="应急联系人")
    emergency_phone: Mapped[str | None] = mapped_column(String(255), comment="应急联系电话（AES 密文）")
    remark: Mapped[str | None] = mapped_column(Text, comment="备注")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, comment="逻辑删除时间")


class VaccineRecord(Base, TimestampMixin):
    __tablename__ = "vaccine_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pet_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="宠物 ID")
    record_type: Mapped[str] = mapped_column(String(20), nullable=False,
                                             comment="vaccine 疫苗 / deworm_inner 体内驱虫 / deworm_outer 体外驱虫")
    name: Mapped[str | None] = mapped_column(String(100), comment="疫苗 / 药品名称")
    record_date: Mapped[date] = mapped_column(Date, nullable=False, comment="本次接种 / 驱虫日期")
    next_date: Mapped[date | None] = mapped_column(Date, comment="下次建议日期")
    remark: Mapped[str | None] = mapped_column(String(255), comment="备注")
