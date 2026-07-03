"""门店配置 Schema。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SettingItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    setting_key: str
    setting_value: str
    value_type: str
    default_value: str
    setting_desc: str | None = None
    min_value: int | None = None
    max_value: int | None = None


class SettingUpdateIn(BaseModel):
    setting_key: str = Field(min_length=1, max_length=64)
    setting_value: str = Field(min_length=0, max_length=255)
