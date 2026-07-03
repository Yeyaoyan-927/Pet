"""宠物用品请求 / 响应模型（V7.2）。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.constants import PickupMethod

PRODUCT_CATEGORIES = {"basic_food", "snack", "toy", "clean", "clothes", "health", "daily"}


class CartAddIn(BaseModel):
    sku_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=99)
    pet_id: int | None = Field(default=None, description="关联宠物，用于过敏交叉校验")


class CartUpdateIn(BaseModel):
    quantity: int = Field(ge=0, le=99, description="0 表示删除")


class GoodsOrderCreateIn(BaseModel):
    """下单：不传 items 则用购物车全部条目。"""

    items: list[CartAddIn] | None = Field(default=None, description="直接下单的条目，缺省取购物车")
    pickup_method: str = Field(default=PickupMethod.SELF.value, description="self 自提 / delivery 配送")
    address: str | None = Field(default=None, max_length=255)
    remark: str | None = Field(default=None, max_length=255)
    pet_id: int | None = Field(default=None, description="关联宠物（用于过敏校验留痕）")
    idempotent_key: str | None = Field(default=None, max_length=64)

    @field_validator("pickup_method")
    @classmethod
    def check_method(cls, v: str) -> str:
        if v not in {m.value for m in PickupMethod}:
            raise ValueError("取货方式不合法")
        return v


class GoodsStatusIn(BaseModel):
    target_status: str = Field(min_length=2, max_length=24)
    reason: str | None = Field(default=None, max_length=255)
    pay_status: str | None = Field(default=None, description="线下收款标记：unpaid / paid_offline")


class PickupVerifyIn(BaseModel):
    pickup_code: str = Field(min_length=4, max_length=12, description="核销码（店员输入或扫码）")
    pay_status: str = Field(default="paid_offline", description="核销时默认标记线下已收款")


class ProductSkuIn(BaseModel):
    spec_name: str = Field(min_length=1, max_length=80)
    price_cents: int = Field(ge=0, le=10_000_000)
    weight_g: int | None = Field(default=None, ge=1, le=1_000_000)
    stock: int = Field(default=0, ge=0, le=100_000)
    warn_threshold: int = Field(default=5, ge=0, le=1000)
    barcode: str | None = Field(default=None, max_length=64)


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    brand: str | None = Field(default=None, max_length=60)
    category: str = Field(description="basic_food/snack/toy/clean/clothes/health/daily")
    species: str = Field(default="all", description="dog/cat/all")
    stage: str = Field(default="all", description="puppy/adult/senior/all")
    size: str = Field(default="all", description="small/medium/large/all")
    main_image: str | None = Field(default=None, max_length=255)
    detail: str | None = None
    selling_points: str | None = Field(default=None, max_length=255)
    promo_tags: str | None = Field(default=None, max_length=120)
    allergy_tags: str | None = Field(default=None, max_length=255, description="过敏原，逗号分隔")
    taboo_tags: str | None = Field(default=None, max_length=255, description="禁忌，逗号分隔")
    min_weight: int | None = Field(default=None, ge=0, le=200)
    max_weight: int | None = Field(default=None, ge=0, le=200)
    status: str = Field(default="on", description="on/off")
    sort_no: int = Field(default=0, ge=0, le=9999)
    skus: list[ProductSkuIn] = Field(default_factory=list, description="不传则保留原 SKU")

    @field_validator("category")
    @classmethod
    def check_category(cls, v: str) -> str:
        if v not in PRODUCT_CATEGORIES:
            raise ValueError(f"分类必须是 {'/'.join(sorted(PRODUCT_CATEGORIES))} 之一")
        return v

    @field_validator("species")
    @classmethod
    def check_species(cls, v: str) -> str:
        if v not in {"dog", "cat", "all"}:
            raise ValueError("适用物种必须是 dog / cat / all")
        return v


class StockUpdateIn(BaseModel):
    stock: int = Field(ge=0, le=100_000, description="盘点后的实际库存")
    remark: str | None = Field(default=None, max_length=255)
