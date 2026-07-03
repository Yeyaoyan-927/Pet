"""预约相关 Schema。"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.constants import SERVICE_TYPE_LABEL, ServiceType


class AppointmentCreate(BaseModel):
    pet_id: int = Field(gt=0, description="宠物 ID")
    service_type: str = Field(description="basic_bath / medicated_bath / grooming")
    appoint_date: date = Field(description="预约日期")
    slot_time: str = Field(description="时段，形如 10:00")
    remark: str | None = Field(default=None, max_length=255)
    idempotent_key: str | None = Field(default=None, max_length=64, description="前端生成的幂等键")

    @field_validator("service_type")
    @classmethod
    def check_service(cls, v: str) -> str:
        if v not in set(ServiceType):
            raise ValueError(f"service_type 仅支持 {list(SERVICE_TYPE_LABEL)}")
        return v

    @field_validator("slot_time")
    @classmethod
    def check_slot(cls, v: str) -> str:
        if len(v) != 5 or v[2] != ":" or not v[:2].isdigit():
            raise ValueError("slot_time 格式应为 HH:00")
        return v


class StaffAppointmentCreate(AppointmentCreate):
    """店员代客预约：手机号不存在时创建临时用户。

    覆盖 `pet_id` 为可选：代客场景下宠物可能还没有档案，此时用 `pet_name` 临时建档。
    因此约束改为「pet_id 与 pet_name 至少提供一个」，而不是继承必填的 pet_id。
    """

    pet_id: int | None = Field(default=None, ge=0, description="已有档案的宠物 ID，可留空")
    phone: str = Field(description="宠主手机号")
    pet_name: str | None = Field(default=None, max_length=50, description="宠物名，临时创建档案时使用")

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        if not v.isdigit() or len(v) != 11:
            raise ValueError("手机号必须为 11 位数字")
        return v

    @model_validator(mode="after")
    def check_pet(self) -> "StaffAppointmentCreate":
        if not self.pet_id and not (self.pet_name or "").strip():
            raise ValueError("请至少指定已有宠物档案（pet_id）或填写宠物名（pet_name）")
        return self


class RescheduleIn(BaseModel):
    appoint_date: date
    slot_time: str
    reason: str | None = Field(default=None, max_length=255)
    idempotent_key: str | None = Field(default=None, max_length=64)


class AppointmentStatusChange(BaseModel):
    status: str = Field(description="目标状态")
    reason: str | None = Field(default=None, max_length=255, description="终止 / 取消原因")
    remark: str | None = Field(default=None, max_length=255)


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    user_id: int
    pet_id: int
    pet_name: str | None = None
    pet_breed: str | None = None
    owner_name: str | None = None
    owner_phone: str | None = None
    service_type: str
    service_type_label: str | None = None
    appoint_date: date
    slot_time: str
    status: str
    status_label: str | None = None
    staff_id: int | None = None
    staff_name: str | None = None
    risk_level: str | None = None
    remark: str | None = None
    cancel_reason: str | None = None
    terminate_reason: str | None = None
    reschedule_times: int = 0
    confirm_at: datetime | None = None
    arrive_at: datetime | None = None
    finish_at: datetime | None = None
    created_at: datetime | None = None


class WashRecordIn(BaseModel):
    skin_condition: str | None = Field(default=None, max_length=500)
    hair_condition: str | None = Field(default=None, max_length=500)
    products: str | None = Field(default=None, max_length=255)
    staff_note: str | None = Field(default=None, max_length=500)


class WashRecordOut(WashRecordIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appointment_id: int
    pet_id: int
    staff_id: int | None = None
    service_type: str
    wash_start: datetime | None = None
    wash_end: datetime | None = None
    created_at: datetime | None = None
