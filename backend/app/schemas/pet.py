"""宠物档案 Schema。"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PetBase(BaseModel):
    name: str = Field(min_length=1, max_length=50, description="宠物名")
    species: str = Field(default="dog", description="dog / cat")
    breed: str | None = Field(default=None, max_length=50)
    gender: str = Field(default="male", description="male / female")
    birthday: date | None = None
    weight: float | None = Field(default=None, ge=0, le=200)
    sterilized: int = Field(default=0, ge=0, le=1)
    allergy: str | None = None
    skin_disease: str | None = None
    stress_level: int = Field(default=0, ge=0, le=3, description="应激等级 0-3")
    aggressive: int = Field(default=0, ge=0, le=1)
    emergency_contact: str | None = Field(default=None, max_length=50)
    emergency_phone: str | None = Field(default=None, max_length=20)
    remark: str | None = None

    @field_validator("species")
    @classmethod
    def check_species(cls, v: str) -> str:
        if v not in {"dog", "cat", "other"}:
            raise ValueError("species 仅支持 dog / cat / other")
        return v

    @field_validator("gender")
    @classmethod
    def check_gender(cls, v: str) -> str:
        if v not in {"male", "female"}:
            raise ValueError("gender 仅支持 male / female")
        return v


class PetCreate(PetBase):
    pass


class PetUpdate(PetBase):
    pass


class PetOut(PetBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    staff_id: int | None = None
    owner_name: str | None = None
    owner_phone: str | None = None
    age_month: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class VaccineRecordIn(BaseModel):
    record_type: str = Field(description="vaccine / deworm_inner / deworm_outer")
    name: str | None = Field(default=None, max_length=100)
    record_date: date
    next_date: date | None = None
    remark: str | None = Field(default=None, max_length=255)

    @field_validator("record_type")
    @classmethod
    def check_type(cls, v: str) -> str:
        if v not in {"vaccine", "deworm_inner", "deworm_outer"}:
            raise ValueError("record_type 仅支持 vaccine / deworm_inner / deworm_outer")
        return v


class VaccineRecordOut(VaccineRecordIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_id: int
    created_at: datetime | None = None
