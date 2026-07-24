"""宠物档案接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps.auth import get_current_user
from app.models import User
from app.schemas.common import ok
from app.schemas.pet import PetCreate, PetUpdate, VaccineRecordIn
from app.services import pet_service
from app.services.audit_service import write_log

router = APIRouter(prefix="/pets", tags=["宠物档案"])


@router.get("", summary="宠物档案列表")
async def list_pets(
    keyword: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """宠物档案列表。"""
    pets = await pet_service.list_pets(db, user, keyword)
    return ok([pet_service.pet_to_out(p) for p in pets])


@router.post("", summary="新增宠物档案")
async def create_pet(
    payload: PetCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """新增宠物档案。"""
    pet = await pet_service.create_pet(db, user, payload)
    await write_log(db, module="pet", action="create", user_id=user.id, biz_id=pet.id,
                    after=payload.model_dump(mode="json"), request=request)
    await db.commit()
    return ok(pet_service.pet_to_out(pet), "档案已创建")


@router.get("/{pet_id}", summary="宠物档案详情")
async def get_pet(
    pet_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """宠物档案详情。"""
    pet = await pet_service.get_pet_or_404(db, pet_id)
    pet_service.assert_can_access(pet, user)
    return ok(pet_service.pet_to_out(pet))


@router.put("/{pet_id}", summary="编辑宠物档案")
async def update_pet(
    pet_id: int,
    payload: PetUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """编辑宠物档案。"""
    pet = await pet_service.get_pet_or_404(db, pet_id)
    pet_service.assert_can_edit(pet, user)
    before = pet_service.pet_to_out(pet)
    pet = await pet_service.update_pet(db, pet, payload)
    await write_log(db, module="pet", action="update", user_id=user.id, biz_id=pet.id,
                    before=before, after=pet_service.pet_to_out(pet), request=request)
    await db.commit()
    return ok(pet_service.pet_to_out(pet), "档案已更新")


@router.delete("/{pet_id}", summary="作废宠物档案（逻辑删除）")
async def delete_pet(
    pet_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """作废宠物档案（逻辑删除）。"""
    pet = await pet_service.get_pet_or_404(db, pet_id)
    pet_service.assert_can_edit(pet, user)
    before = pet_service.pet_to_out(pet)
    await pet_service.delete_pet(db, pet)
    await write_log(db, module="pet", action="delete", user_id=user.id, biz_id=pet_id,
                    before=before, request=request)
    await db.commit()
    return ok(None, "档案已作废")


@router.get("/{pet_id}/vaccines", summary="疫苗驱虫记录")
async def list_vaccines(
    pet_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """疫苗驱虫记录。"""
    pet = await pet_service.get_pet_or_404(db, pet_id)
    pet_service.assert_can_access(pet, user)
    rows = await pet_service.list_vaccine_records(db, pet_id)
    return ok([
        {
            "id": r.id, "pet_id": r.pet_id, "record_type": r.record_type, "name": r.name,
            "record_date": r.record_date, "next_date": r.next_date, "remark": r.remark,
        }
        for r in rows
    ])


@router.post("/{pet_id}/vaccines", summary="新增疫苗驱虫记录")
async def add_vaccine(
    pet_id: int,
    payload: VaccineRecordIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """新增疫苗驱虫记录。"""
    pet = await pet_service.get_pet_or_404(db, pet_id)
    pet_service.assert_can_edit(pet, user)
    record = await pet_service.add_vaccine_record(db, pet, payload)
    await write_log(db, module="pet", action="add_vaccine", user_id=user.id, biz_id=pet_id,
                    after=payload.model_dump(mode="json"), request=request)
    await db.commit()
    return ok({"id": record.id}, "记录已添加")
