"""用户管理接口（店长专属）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import ROLE_LABEL, UserRole
from app.database import get_db
from app.deps.auth import get_manager_user
from app.models import User
from app.schemas.common import ok
from app.services import auth_service
from app.services.audit_service import write_log
from app.utils.exceptions import NotFoundError

router = APIRouter(prefix="/users", tags=["用户管理"])


class InternalUserIn(BaseModel):
    username: str = Field(min_length=4, max_length=50)
    password: str = Field(min_length=6, max_length=32)
    real_name: str = Field(min_length=1, max_length=50)
    role: str = Field(description="staff / manager")
    phone: str | None = Field(default=None, max_length=11)


@router.get("", summary="用户列表（店长可见原始手机号）")
async def list_users(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    role: str | None = None,
    keyword: str | None = None,
    manager: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    """用户列表（店长可见原始手机号）。"""
    cond = [User.deleted_at.is_(None)]
    if role:
        cond.append(User.role == role)
    if keyword:
        cond.append(User.real_name.like(f"%{keyword}%"))
    total = await db.scalar(select(func.count()).select_from(User).where(*cond)) or 0
    rows = (
        await db.execute(
            select(User).where(*cond).order_by(User.id.desc())
            .offset((page - 1) * size).limit(size)
        )
    ).scalars().all()
    # 店长专属视角：返回 phone 原始号码用于门店联系；其余场景一律脱敏
    return ok({"items": [auth_service.user_to_out(u, include_phone=True) for u in rows],
               "total": int(total), "page": page, "size": size, "roles": ROLE_LABEL})


@router.post("", summary="创建店员 / 店长账号")
async def create_user(
    payload: InternalUserIn,
    request: Request,
    manager: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    """创建店员 / 店长账号。"""
    user = await auth_service.create_internal_user(
        db, username=payload.username, password=payload.password,
        real_name=payload.real_name, role=payload.role, phone=payload.phone,
    )
    await write_log(db, module="user", action="create_internal", user_id=manager.id, biz_id=user.id,
                    after={"username": user.username, "role": user.role}, request=request)
    await db.commit()
    return ok(auth_service.user_to_out(user), "账号已创建")


@router.post("/{user_id}/status", summary="启用 / 禁用账号")
async def toggle_status(
    user_id: int,
    request: Request,
    manager: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    """启用 / 禁用账号。"""
    target = await db.get(User, user_id)
    # 与 Agent 工具 toggle_user_status 共用同一 service 方法，保证双入口行为一致
    target = await auth_service.toggle_user_status(db, target, manager, request)
    return ok({"id": target.id, "status": target.status}, "状态已更新")
