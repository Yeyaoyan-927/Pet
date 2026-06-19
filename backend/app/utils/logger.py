"""结构化日志：JSON 行输出，自动过滤手机号等敏感信息。"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime

PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
# 身份证必须符合中国身份证的结构（6 位地区 + 出生日期 + 3 位顺序 + 校验位），
# 否则会把 18 位的预约单号（14 位时间戳 + 4 位随机数）误打成星号。
ID_CARD_RE = re.compile(
    r"(?<!\d)(\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3})[\dXx](?!\d)"
)

SENSITIVE_KEYS = {"password", "phone", "phone_encrypted", "emergency_phone", "id_card", "token"}


def mask_sensitive(text: str) -> str:
    text = PHONE_RE.sub(r"\1****\2", text)
    text = ID_CARD_RE.sub(r"\1*", text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": mask_sensitive(record.getMessage()),
        }
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = "***" if key in SENSITIVE_KEYS else value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str = "pet_groom") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


logger = get_logger()
