"""宠物寄养请求 / 响应模型（V7.1）。"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.constants import DropoffMethod, FeedingPlan, PickupBackMethod, ShippingMethod

CARE_ITEM_TYPES = {"medication", "feeding", "walk", "taboo"}
ROOM_TYPES = {"standard", "garden", "sunny", "vip"}
ROOM_STATUS = {"idle", "occupied", "cleaning", "maintenance"}


class CarePlanIn(BaseModel):
    """照护计划条目：用药 / 喂食 / 遛放 / 禁忌。"""

    item_type: str = Field(description="medication / feeding / walk / taboo")
    content: str = Field(min_length=1, max_length=255)
    frequency: str | None = Field(default=None, max_length=64)
    need_staff: bool = Field(default=False, description="是否需店员执行")

    @field_validator("item_type")
    @classmethod
    def check_type(cls, v: str) -> str:
        if v not in CARE_ITEM_TYPES:
            raise ValueError(f"照护类型必须是 {'/'.join(sorted(CARE_ITEM_TYPES))} 之一")
        return v


class BoardingOrderCreate(BaseModel):
    pet_id: int = Field(gt=0)
    room_id: int = Field(gt=0)
    check_in_date: date
    check_out_date: date
    feeding_plan: str = Field(default=FeedingPlan.SELF.value, description="self/standard/premium/prescription")
    food_note: str | None = Field(default=None, max_length=255, description="自备食物明细与喂食说明")
    dropoff_method: str = Field(default=DropoffMethod.SELF.value, description="送宠到店：self 自行送到 / pickup 上门接宠")
    pickup_back_method: str = Field(default=PickupBackMethod.SELF.value, description="离店接宠：self 自行接取 / return 送宠到家")
    shipping_address: str | None = Field(default=None, max_length=255)
    shipping_slot: str | None = Field(default=None, max_length=32)
    emergency_contact: str | None = Field(default=None, max_length=50)
    emergency_phone: str | None = Field(default=None, max_length=20)
    medical_authorized: bool = Field(default=False, description="授权就医")
    terms_confirmed: bool = Field(default=False, description="寄养条款与责任划分确认")
    care_items: list[CarePlanIn] = Field(default_factory=list, description="照护计划条目")
    remark: str | None = None
    idempotent_key: str | None = Field(default=None, max_length=64)

    @field_validator("feeding_plan")
    @classmethod
    def check_feeding(cls, v: str) -> str:
        if v not in {p.value for p in FeedingPlan}:
            raise ValueError("喂食方案不合法")
        return v

    @field_validator("dropoff_method")
    @classmethod
    def check_dropoff(cls, v: str) -> str:
        if v not in {m.value for m in DropoffMethod}:
            raise ValueError("送宠到店方式不合法")
        return v

    @field_validator("pickup_back_method")
    @classmethod
    def check_pickup_back(cls, v: str) -> str:
        if v not in {m.value for m in PickupBackMethod}:
            raise ValueError("离店接宠方式不合法")
        return v

    @field_validator("emergency_phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not v.isdigit() or len(v) != 11:
            raise ValueError("紧急联系电话必须为 11 位数字")
        return v


class BoardingQuoteIn(BaseModel):
    pet_id: int = Field(gt=0)
    room_id: int = Field(gt=0)
    check_in_date: date
    check_out_date: date
    feeding_plan: str = FeedingPlan.SELF.value
    dropoff_method: str = DropoffMethod.SELF.value
    pickup_back_method: str = PickupBackMethod.SELF.value


class CareLogIn(BaseModel):
    """每日照护日志。"""

    log_date: date | None = Field(default=None, description="默认今天")
    eating: str | None = Field(default=None, max_length=64)
    drinking: str | None = Field(default=None, max_length=32)
    stool: str | None = Field(default=None, max_length=64)
    spirit: str | None = Field(default=None, max_length=32)
    activity: str | None = Field(default=None, max_length=64)
    abnormal: bool = Field(default=False, description="存在异常（会立即推送宠主）")
    abnormal_note: str | None = Field(default=None, max_length=255)
    photos: list[str] = Field(default_factory=list, description="照片地址列表")
    sop_checked: list[str] = Field(default_factory=list, description="已完成的 SOP 检查项")


class BoardingStatusIn(BaseModel):
    target_status: str = Field(min_length=2, max_length=24)
    reason: str | None = Field(default=None, max_length=255)
    checkin_note: str | None = Field(default=None, max_length=255, description="入住健康初检记录")
    checkout_note: str | None = Field(default=None, max_length=255, description="退房物品清点与消杀记录")


class BoardingExtendIn(BaseModel):
    check_out_date: date


class BoardingRoomIn(BaseModel):
    # 带 id 表示编辑已有宠舍（房号同样唯一），不带才是新增
    id: int | None = Field(default=None, description="宠舍 ID（编辑时传）")
    room_no: str = Field(min_length=1, max_length=32)
    room_type: str = Field(description="standard/garden/sunny/vip")
    name: str = Field(min_length=1, max_length=50)
    species_limit: str = Field(default="all", description="dog/cat/all")
    weight_limit: int | None = Field(default=None, ge=1, le=99)
    ratio_percent: int = Field(default=100, ge=50, le=500, description="房型系数百分比")
    capacity: int = Field(default=1, ge=1, le=10)
    facilities: str | None = Field(default=None, max_length=255)
    remark: str | None = Field(default=None, max_length=255)

    @field_validator("room_type")
    @classmethod
    def check_room_type(cls, v: str) -> str:
        if v not in ROOM_TYPES:
            raise ValueError(f"房型必须是 {'/'.join(sorted(ROOM_TYPES))} 之一")
        return v

    @field_validator("species_limit")
    @classmethod
    def check_species(cls, v: str) -> str:
        if v not in {"dog", "cat", "all"}:
            raise ValueError("适配物种必须是 dog / cat / all")
        return v


class BoardingRoomStatusIn(BaseModel):
    status: str = Field(description="idle/occupied/cleaning/maintenance")

    @field_validator("status")
    @classmethod
    def check_status(cls, v: str) -> str:
        if v not in ROOM_STATUS:
            raise ValueError(f"房态必须是 {'/'.join(sorted(ROOM_STATUS))} 之一")
        return v


class EarlyPickupIn(BaseModel):
    """宠主申请提前接回。"""

    expect_pickup_date: date = Field(description="期望接回日期（要早于原定离店日）")
    reason: str | None = Field(default=None, max_length=255, description="申请原因")


class EarlyPickupReviewIn(BaseModel):
    """门店审核提前接回申请。"""

    approve: bool = Field(description="true 通过 / false 驳回")
    note: str | None = Field(default=None, max_length=255, description="审核意见（驳回建议填写）")
