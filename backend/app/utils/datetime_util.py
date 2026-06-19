"""日期时间与工具函数。"""
from __future__ import annotations

import random
import string
from datetime import date, datetime

from app.config import settings


def now() -> datetime:
    return datetime.now()


def gen_order_no(prefix: str = "PG") -> str:
    """预约单号：PG + yyyyMMddHHmmss + 4 位随机数。"""
    return f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(1000, 9999)}"


def gen_random_str(length: int = 16) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def calc_age_month(birthday: date | None) -> int | None:
    if not birthday:
        return None
    today = date.today()
    months = (today.year - birthday.year) * 12 + (today.month - birthday.month)
    if today.day < birthday.day:
        months -= 1
    return max(months, 0)


def validate_slot(slot_time: str) -> bool:
    return slot_time in settings.slot_list()


def date_range_label(d: date) -> str:
    return d.strftime("%m-%d")
