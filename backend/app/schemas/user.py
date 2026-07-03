"""用户与鉴权 Schema。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterIn(BaseModel):
    username: str = Field(min_length=4, max_length=50, description="登录账号")
    password: str = Field(min_length=6, max_length=32, description="密码")
    real_name: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=20, description="手机号，入库前 AES 加密")

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        if v and (not v.isdigit() or len(v) != 11):
            raise ValueError("手机号必须为 11 位数字")
        return v


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=32)


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserOut"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    real_name: str | None = None
    phone_masked: str | None = None
    role: str
    status: int
    created_at: datetime | None = None


class UserUpdateIn(BaseModel):
    real_name: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=20)


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=6, max_length=32)


TokenOut.model_rebuild()
