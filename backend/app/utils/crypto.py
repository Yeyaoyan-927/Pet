"""手机号等敏感字段的加密 / 脱敏工具。

策略：AES(Fernet) 可逆加密存储 + HMAC-SHA256 索引用于精确查重，明文绝不出库、绝不打日志。
"""
from __future__ import annotations

import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_fernet = Fernet(settings.fernet_key)


def encrypt_text(plain: str | None) -> str | None:
    if not plain:
        return None
    return _fernet.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_text(cipher: str | None) -> str | None:
    if not cipher:
        return None
    try:
        return _fernet.decrypt(cipher.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def phone_hmac(plain: str | None) -> str | None:
    """不可逆索引，用于按手机号查用户（无法从 hash 反推明文）。"""
    if not plain:
        return None
    return hmac.new(settings.phone_hmac_secret, plain.encode("utf-8"), hashlib.sha256).hexdigest()


def mask_phone(plain: str | None) -> str | None:
    """页面展示脱敏：138****8888。"""
    if not plain:
        return None
    if len(plain) < 7:
        return "*" * len(plain)
    return f"{plain[:3]}****{plain[-4:]}"
