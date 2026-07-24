"""宠物档案服务。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import UserRole
from app.models import Pet, User, VaccineRecord
from app.schemas.pet import PetCreate, PetUpdate, VaccineRecordIn
from app.utils.crypto import decrypt_text, encrypt_text, phone_hmac
from app.utils.exceptions import NotFoundError, PermissionError_
from app.utils.datetime_util import calc_age_month


async def get_pet_or_404(db: AsyncSession, pet_id: int) -> Pet:
    """按 ID 取档案，不存在抛 NotFoundError。"""
    pet = await db.get(Pet, pet_id)
    if pet is None or pet.deleted_at is not None:
        raise NotFoundError("宠物档案不存在")
    return pet


def assert_can_access(pet: Pet, user) -> None:
    """宠主仅能访问自己的宠物；**店员 / 店长可访问全部客户档案**（V8.4.7 取消归属限制）。

    `pet.staff_id` 只保留「建档 / 认领店员」的溯源含义，不再参与权限判定 ——
    门店现场是轮流排班，谁在前台谁就可能需要查/改某只宠物，按归属拦截只会让店员互相等。
    """
    if user.role == UserRole.CUSTOMER.value and pet.user_id != user.id:
        raise PermissionError_("无权访问他人的宠物档案")


def assert_can_edit(pet: Pet, user) -> None:
    """编辑权限：宠主只能改自己的；店员 / 店长可改全部客户档案（含档案与疫苗记录）。"""
    if user.role == UserRole.CUSTOMER.value and pet.user_id != user.id:
        raise PermissionError_("无权修改他人的宠物档案")


async def create_pet(db: AsyncSession, user, payload: PetCreate) -> Pet:
    """新建档案：同一宠主下按名称判重，避免重复建档。"""
    pet = Pet(
        user_id=user.id,
        staff_id=user.id if user.role == UserRole.STAFF.value else None,
        emergency_phone=encrypt_text(payload.emergency_phone),
        **payload.model_dump(exclude={"emergency_phone"}),
    )
    db.add(pet)
    await db.flush()
    return pet


async def update_pet(db: AsyncSession, pet: Pet, payload: PetUpdate) -> Pet:
    """更新档案字段（体重、过敏史等直接影响风险判别与用品推荐）。"""
    data = payload.model_dump(exclude={"emergency_phone"})
    for key, value in data.items():
        setattr(pet, key, value)
    pet.emergency_phone = encrypt_text(payload.emergency_phone)
    await db.flush()
    return pet


async def delete_pet(db: AsyncSession, pet: Pet) -> None:
    """删除档案：逻辑删除，历史预约/洗护记录仍可追溯。"""
    pet.deleted_at = datetime.now()
    await db.flush()


async def list_pets(db: AsyncSession, user, keyword: str | None = None) -> list[Pet]:
    """宠物档案列表。

    筛选**全部下推到 SQL**（不在应用层全表捞出后过滤）：
    - 宠主：仅自己名下
    - 店员 / 店长：可按「宠物名」「宠主姓名」模糊匹配；若关键词是 11 位手机号，
      走 HMAC 索引精确匹配宠主（手机号密文不可模糊查询）。
    """
    cond = [Pet.deleted_at.is_(None)]
    if user.role == UserRole.CUSTOMER.value:
        cond.append(Pet.user_id == user.id)

    stmt = select(Pet).where(*cond)

    kw = (keyword or "").strip()
    if kw:
        if user.role != UserRole.CUSTOMER.value and kw.isdigit() and len(kw) == 11:
            owner_id = await db.scalar(select(User.id).where(User.phone_hash == phone_hmac(kw)))
            if owner_id is None:
                return []
            stmt = stmt.where(Pet.user_id == owner_id)
        else:
            owner_ids = select(User.id).where(User.real_name.like(f"%{kw}%"))
            stmt = stmt.where(or_(Pet.name.like(f"%{kw}%"), Pet.user_id.in_(owner_ids)))

    stmt = stmt.order_by(Pet.id.desc())
    return list((await db.execute(stmt)).scalars().all())


async def owners_map(db: AsyncSession, pets: list[Pet]) -> dict[int, User]:
    """批量取宠主（一次查询，避免 N+1）。"""
    ids = {p.user_id for p in pets if p.user_id}
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u for u in rows}


async def list_vaccine_records(db: AsyncSession, pet_id: int) -> list[VaccineRecord]:
    """疫苗与驱虫记录（按日期倒序），寄养硬门槛就是查这里。"""
    return list(
        (
            await db.execute(
                select(VaccineRecord).where(VaccineRecord.pet_id == pet_id).order_by(VaccineRecord.record_date.desc())
            )
        ).scalars().all()
    )


async def add_vaccine_record(db: AsyncSession, pet: Pet, payload: VaccineRecordIn) -> VaccineRecord:
    """登记一条疫苗/驱虫记录，下次到期日用于临期提醒。"""
    record = VaccineRecord(pet_id=pet.id, **payload.model_dump())
    db.add(record)
    await db.flush()
    return record


def pet_to_out(pet: Pet, owner=None) -> dict:
    """档案序列化：宠物信息 + 宠主信息（手机号脱敏）。"""
    return {
        "id": pet.id,
        "user_id": pet.user_id,
        "staff_id": pet.staff_id,
        "name": pet.name,
        "species": pet.species,
        "breed": pet.breed,
        "gender": pet.gender,
        "birthday": pet.birthday,
        "weight": float(pet.weight) if pet.weight is not None else None,
        "sterilized": pet.sterilized,
        "allergy": pet.allergy,
        "skin_disease": pet.skin_disease,
        "stress_level": pet.stress_level,
        "aggressive": pet.aggressive,
        "emergency_contact": pet.emergency_contact,
        "emergency_phone": decrypt_text(pet.emergency_phone),
        "remark": pet.remark,
        "age_month": calc_age_month(pet.birthday),
        "owner_name": getattr(owner, "real_name", None),
        "owner_phone": None,
        "created_at": pet.created_at,
        "updated_at": pet.updated_at,
    }
