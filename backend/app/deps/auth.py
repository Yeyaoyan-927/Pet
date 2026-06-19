"""RBAC 依赖：解析当前用户 + 角色守卫。"""
from __future__ import annotations

from collections.abc import Callable

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import UserRole
from app.database import get_db
from app.models import User
from app.utils.exceptions import AuthError, PermissionError_
from app.utils.security import TOKEN_TYPE_ACCESS, decode_token, is_user_revoked

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthError("未携带访问令牌")
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("登录已过期，请重新登录") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("访问令牌无效") from exc

    if payload.get("type") != TOKEN_TYPE_ACCESS:
        raise AuthError("令牌类型错误")
    if is_user_revoked(int(payload["sub"]), int(payload.get("iat", 0))):
        raise AuthError("登录状态已失效，请重新登录")

    user = await db.get(User, int(payload["sub"]))
    if user is None or user.deleted_at is not None:
        raise AuthError("账号不存在")
    if user.status != 1:
        raise AuthError("账号已被禁用")
    return user


def require_roles(*roles: str) -> Callable:
    """角色守卫，用法：Depends(require_roles(UserRole.MANAGER))。"""

    allowed = {r.value if isinstance(r, UserRole) else r for r in roles}

    async def _guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise PermissionError_(f"该操作仅限 {'/'.join(allowed)} 角色")
        return user

    return _guard


STAFF_ROLES = (UserRole.STAFF.value, UserRole.MANAGER.value)
MANAGER_ROLES = (UserRole.MANAGER.value,)


async def get_staff_user(user: User = Depends(require_roles(*STAFF_ROLES))) -> User:
    return user


async def get_manager_user(user: User = Depends(require_roles(*MANAGER_ROLES))) -> User:
    return user
