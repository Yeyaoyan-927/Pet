"""pytest 全局装置与公共辅助。

两条硬约束（都是踩过坑总结出来的）：
1. **所有用例共用同一个事件循环**（pytest.ini 设为 session 级）：
   aiomysql 连接池绑定事件循环，跨循环复用会报 `Event loop is closed`（docs/01 E-04）。
2. **测试数据必须可清理、可重复执行**：
   造的宠物 / 预约 / 消息统一打随机 tag，用例结束就地删除，绝不污染演示数据。
"""
from __future__ import annotations

import random
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Pet, User


@pytest.fixture
async def db():
    """独立会话（只读或短事务用；并发用例请自行开 session，见 test_slot_concurrency）。"""
    async with AsyncSessionLocal() as session:
        yield session


def rand_tag(prefix: str = "v6") -> str:
    """生成随机标记，用于标记本用例造的数据，便于精确清理。"""
    return f"{prefix}{random.randint(100000, 999999)}"


def rand_future_date(min_days: int = 500, max_days: int = 900) -> date:
    """远期随机日期：避免与其他用例/历史数据抢同一时段，保证连跑两次也通过。"""
    return date.today() + __import__("datetime").timedelta(days=random.randint(min_days, max_days))


async def get_user_id(username: str) -> int:
    async with AsyncSessionLocal() as session:
        user_id = (
            await session.execute(select(User.id).where(User.username == username))
        ).scalars().first()
    assert user_id, f"演示账号 {username} 不存在，请先执行 scripts/init_db.py"
    return int(user_id)


async def create_test_pets(owner_id: int, tag: str, count: int) -> list[int]:
    """批量造测试宠物（归属指定宠主），返回宠物 ID 列表。"""
    async with AsyncSessionLocal() as session:
        pets = [
            Pet(user_id=owner_id, name=f"{tag}犬{i}", species="dog", gender="male", sterilized=1)
            for i in range(count)
        ]
        session.add_all(pets)
        await session.commit()
        return [p.id for p in pets]


async def cleanup(db: AsyncSession, *, pet_ids: list[int], keys_like: str | None = None) -> None:
    """删除用例造的宠物、预约与消息（按 pet_id / 幂等键前缀）。"""
    from sqlalchemy import delete

    from app.models import Appointment, Message

    if pet_ids:
        await db.execute(delete(Message).where(Message.biz_id.in_(pet_ids)))
        await db.execute(delete(Appointment).where(Appointment.pet_id.in_(pet_ids)))
        await db.execute(delete(Pet).where(Pet.id.in_(pet_ids)))
    if keys_like:
        await db.execute(delete(Appointment).where(Appointment.idempotent_key.like(keys_like)))
    await db.commit()
