"""密码哈希与 JWT 签发 / 校验。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.config import settings

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"

# 进程内 token 黑名单（V1）。V4 升级为 Redis 黑名单。
_REVOKED: set[str] = set()


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8")[:72], bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


def _create_token(subject: int | str, role: str, token_type: str, expires: timedelta) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: int, role: str) -> str:
    return _create_token(user_id, role, TOKEN_TYPE_ACCESS,
                         timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(user_id: int, role: str) -> str:
    return _create_token(user_id, role, TOKEN_TYPE_REFRESH,
                         timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str) -> dict[str, Any]:
    """解析失败抛 jwt.PyJWTError，由调用方转成业务异常。"""
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    if token in _REVOKED:
        raise jwt.InvalidTokenError("token 已失效")
    return payload


def revoke_token(token: str) -> None:
    _REVOKED.add(token)


def revoke_all_for_user(user_id: int) -> None:
    """改密 / 注销后强制失效。V1 通过版本号前缀实现批量失效。"""
    _REVOKED.add(f"__user__{user_id}__{int(datetime.now(UTC).timestamp())}")


def is_user_revoked(user_id: int, iat: int) -> bool:
    prefix = f"__user__{user_id}__"
    return any(k.startswith(prefix) and int(k.rsplit("__", 1)[-1]) > iat for k in _REVOKED)
