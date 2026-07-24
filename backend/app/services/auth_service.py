"""鉴权 / 用户服务。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import UserRole
from app.models import User
from app.schemas.user import RegisterIn
from app.services.audit_service import write_log
from app.utils.crypto import decrypt_text, encrypt_text, mask_phone, phone_hmac
from app.utils.datetime_util import gen_random_str, now
from app.utils.exceptions import BizError, ConflictError
from app.utils.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    revoke_token,
)

TEMP_PASSWORD_CHARS = 12


def user_to_out(user: User, *, include_phone: bool = False) -> dict:
    """手机号可见性：默认只返回脱敏值；仅店长场景（include_phone=True）返回原始号码。"""
    raw = decrypt_text(user.phone_encrypted)
    data = {
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "phone_masked": mask_phone(raw),
        "role": user.role,
        "status": user.status,
        "is_temp": user.is_temp,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
    }
    if include_phone:
        data["phone"] = raw
    return data


async def get_by_username(db: AsyncSession, username: str) -> User | None:
    """按用户名查未删除账号（登录与判重都用它）。"""
    return (
        await db.execute(
            select(User).where(User.username == username, User.deleted_at.is_(None))
        )
    ).scalars().first()


async def get_by_phone(db: AsyncSession, phone: str) -> User | None:
    """按手机号 HMAC 索引查账号（注册判重、代客下单找老客）。"""
    return (
        await db.execute(
            select(User).where(User.phone_hash == phone_hmac(phone), User.deleted_at.is_(None))
        )
    ).scalars().first()


async def register(db: AsyncSession, payload: RegisterIn, request: Request | None = None) -> User:
    """宠主自助注册：用户名/手机号双判重 → 加密手机号 + 建索引 → 密码哈希 → 审计。"""
    if await get_by_username(db, payload.username):
        raise ConflictError("账号已存在")
    if payload.phone and await get_by_phone(db, payload.phone):
        raise ConflictError("该手机号已注册")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        real_name=payload.real_name or payload.username,
        phone_encrypted=encrypt_text(payload.phone),
        phone_hash=phone_hmac(payload.phone),
        role=UserRole.CUSTOMER.value,
    )
    db.add(user)
    await db.flush()
    await write_log(db, module="auth", action="register", user_id=user.id, request=request,
                    after={"username": user.username, "role": user.role})
    await db.commit()
    await db.refresh(user)
    return user


async def create_internal_user(
    db: AsyncSession, *, username: str, password: str, real_name: str, role: str, phone: str | None = None
) -> User:
    """店长创建店员/店长账号：随机初始密码，返回一次明文供线下告知。"""
    if role not in {UserRole.STAFF.value, UserRole.MANAGER.value}:
        raise BizError("内部账号角色仅支持 staff / manager")
    if await get_by_username(db, username):
        raise ConflictError("账号已存在")
    user = User(
        username=username,
        password_hash=hash_password(password),
        real_name=real_name,
        phone_encrypted=encrypt_text(phone),
        phone_hash=phone_hmac(phone),
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


async def authenticate(db: AsyncSession, username: str, password: str) -> User:
    """校验账密与账号状态。错误统一抛 BizError(4011)，不区分「用户名不存在」与「密码错」。"""
    from app.utils.security import verify_password

    user = await get_by_username(db, username)
    if user is None or not verify_password(password, user.password_hash):
        raise BizError("账号或密码错误", code=4011, http_status=401)
    if user.status != 1:
        raise BizError("账号已被禁用，请联系店长", code=4012, http_status=403)
    user.last_login_at = now()
    await db.flush()
    return user


def issue_tokens(user: User) -> dict:
    """签发 access + refresh 令牌（含角色与用户 ID）。"""
    from app.config import settings

    return {
        "access_token": create_access_token(user.id, user.role),
        "refresh_token": create_refresh_token(user.id, user.role),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": user_to_out(user),
    }


def random_password() -> str:
    """生成初始密码：去掉易混淆字符，保证能口头传达。"""
    return gen_random_str(TEMP_PASSWORD_CHARS)


__all__ = [
    "user_to_out",
    "get_by_username",
    "get_by_phone",
    "register",
    "create_internal_user",
    "authenticate",
    "issue_tokens",
    "revoke_token",
    "random_password",
]


async def toggle_user_status(db: AsyncSession, target: User, operator: User, request=None) -> User:
    """启用 / 禁用账号。店长账号不可被禁用（防自锁）。"""
    from app.constants import UserRole
    from app.services.audit_service import write_log
    from app.utils.exceptions import BizError, NotFoundError

    if target is None or target.deleted_at is not None:
        raise NotFoundError("账号不存在")
    if target.role == UserRole.MANAGER.value:
        raise BizError("店长账号不可禁用")
    if target.id == operator.id:
        raise BizError("不能操作自己的账号")
    target.status = 0 if target.status == 1 else 1
    await db.flush()
    await write_log(db, module="user", action="toggle_status", user_id=operator.id,
                    biz_id=target.id, after={"status": target.status}, request=request)
    await db.commit()
    return target
