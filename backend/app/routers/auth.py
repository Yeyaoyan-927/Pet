"""鉴权接口。"""
from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps.auth import bearer_scheme, get_current_user
from app.models import User
from app.schemas.common import ok
from app.schemas.user import ChangePasswordIn, LoginIn, RefreshIn, RegisterIn, UserUpdateIn
from app.services import auth_service
from app.services.audit_service import write_log
from app.utils.crypto import encrypt_text, phone_hmac
from app.utils.exceptions import AuthError, BizError
from app.utils.security import (
    TOKEN_TYPE_REFRESH,
    create_access_token,
    decode_token,
    hash_password,
    is_user_revoked,
    revoke_all_for_user,
    revoke_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["鉴权"])


@router.post("/register", summary="宠主注册")
async def register(payload: RegisterIn, request: Request, db: AsyncSession = Depends(get_db)):
    """宠主注册。"""
    user = await auth_service.register(db, payload, request)
    return ok(auth_service.issue_tokens(user), "注册成功")


@router.post("/login", summary="登录")
async def login(payload: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    """登录。"""
    user = await auth_service.authenticate(db, payload.username, payload.password)
    await write_log(db, module="auth", action="login", user_id=user.id, request=request)
    await db.commit()
    return ok(auth_service.issue_tokens(user), "登录成功")


@router.post("/refresh", summary="刷新 access token")
async def refresh(payload: RefreshIn, db: AsyncSession = Depends(get_db)):
    """刷新 access token。"""
    try:
        data = decode_token(payload.refresh_token)
    except jwt.PyJWTError as exc:
        raise AuthError("refresh token 无效或已过期") from exc
    if data.get("type") != TOKEN_TYPE_REFRESH:
        raise AuthError("令牌类型错误")
    user = await db.get(User, int(data["sub"]))
    if user is None or user.status != 1:
        raise AuthError("账号状态异常")
    return ok({"access_token": create_access_token(user.id, user.role), "token_type": "bearer"})


@router.post("/logout", summary="注销")
async def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """注销。"""
    if credentials is not None:
        revoke_token(credentials.credentials)
    await write_log(db, module="auth", action="logout", user_id=user.id, request=request)
    await db.commit()
    return ok(None, "已退出登录")


@router.get("/me", summary="当前登录用户")
async def me(user: User = Depends(get_current_user)):
    """当前登录用户。"""
    return ok(auth_service.user_to_out(user))


@router.put("/me", summary="更新个人资料")
async def update_me(
    payload: UserUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """更新个人资料。"""
    before = auth_service.user_to_out(user)
    if payload.real_name is not None:
        user.real_name = payload.real_name
    if payload.phone:
        if len(payload.phone) != 11 or not payload.phone.isdigit():
            raise BizError("手机号必须为 11 位数字")
        user.phone_encrypted = encrypt_text(payload.phone)
        user.phone_hash = phone_hmac(payload.phone)
    await db.flush()
    await write_log(db, module="auth", action="update_profile", user_id=user.id,
                    before=before, after=auth_service.user_to_out(user), request=request)
    await db.commit()
    return ok(auth_service.user_to_out(user), "资料已更新")


@router.post("/change-password", summary="修改密码（强制失效全部 token）")
async def change_password(
    payload: ChangePasswordIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """修改密码（强制失效全部 token）。"""
    if not verify_password(payload.old_password, user.password_hash):
        raise BizError("原密码不正确")
    user.password_hash = hash_password(payload.new_password)
    await db.flush()
    revoke_all_for_user(user.id)
    await write_log(db, module="auth", action="change_password", user_id=user.id, request=request)
    await db.commit()
    return ok(None, "密码已修改，请重新登录")


@router.post("/sessions/clean", summary="[运维] 手动触发会话过期清理（历史占位接口，实际清理见 /chat/purge）")
async def clean_sessions(user: User = Depends(get_current_user)):
    """[运维] 手动触发会话过期清理（历史占位接口，实际清理见 /chat/purge）。"""
    return ok({"cleaned": 0, "note": "会话存储已启用（chat_session）；实际清理请调用 GET /api/v1/chat/purge"}, "占位接口")


__all__ = ["is_user_revoked"]
