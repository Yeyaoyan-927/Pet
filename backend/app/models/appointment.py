"""预约订单表（核心业务实体）。"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Appointment(Base, TimestampMixin):
    __tablename__ = "appointment"
    __table_args__ = (
        Index("idx_appt_date_slot_status", "appoint_date", "slot_time", "status"),
        Index("idx_appt_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, comment="预约单号")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="宠主 ID")
    pet_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="宠物 ID")
    service_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="洗护服务类型")
    appoint_date: Mapped[date] = mapped_column(Date, nullable=False, comment="预约日期")
    slot_time: Mapped[str] = mapped_column(String(10), nullable=False, comment="预约时段 HH:00")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True,
                                        comment="预约状态")
    staff_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="归属店员")
    operator_staff_id: Mapped[int | None] = mapped_column(BigInteger, comment="代客预约操作店员")
    created_by: Mapped[str] = mapped_column(String(16), nullable=False, default="form",
                                            comment="入口：form 表单 / agent 对话 / staff 代客")
    temp_phone_encrypted: Mapped[str | None] = mapped_column(String(255), comment="代客预约临时用户手机号密文")
    idempotent_key: Mapped[str | None] = mapped_column(String(64), unique=True,
                                                       comment="双入口统一幂等键")
    remark: Mapped[str | None] = mapped_column(Text, comment="宠主备注")
    cancel_reason: Mapped[str | None] = mapped_column(String(255), comment="取消原因")
    terminate_reason: Mapped[str | None] = mapped_column(String(255), comment="异常终止原因")
    reschedule_times: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0,
                                                  comment="已改期次数")
    risk_level: Mapped[str | None] = mapped_column(String(16), comment="风险等级快照")
    confirm_at: Mapped[datetime | None] = mapped_column(DateTime, comment="店员确认时间")
    arrive_at: Mapped[datetime | None] = mapped_column(DateTime, comment="到店时间")
    start_at: Mapped[datetime | None] = mapped_column(DateTime, comment="开始洗护时间")
    finish_at: Mapped[datetime | None] = mapped_column(DateTime, comment="洗护完成时间")
    cancel_at: Mapped[datetime | None] = mapped_column(DateTime, comment="取消时间")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, comment="逻辑删除时间")
