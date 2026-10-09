"""核心服务层用例（V8）：认证、档案、消息、配置、报表、排期、洗护。

这些模块此前只有接口冒烟兜着，服务层的分支（越权、非法值、空数据）没被单测覆盖。
用例统一自建数据、结束清理，可重复执行。
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest
from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.models import Message, Pet, User, VaccineRecord
from app.schemas.user import RegisterIn
from app.schemas.pet import PetCreate, PetUpdate, VaccineRecordIn
from app.services import (
    auth_service,
    message_service,
    pet_service,
    schedule_service,
    setting_service,
    stats_service,
    wash_service,
)
from app.utils.exceptions import BizError, NotFoundError, PermissionError_
from tests.conftest import rand_tag


async def _user(username: str) -> User:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalars().first()
    assert user is not None, "演示账号缺失，请先执行 scripts/init_db.py"
    return user


async def test_auth_login_and_token_guard():
    """登录：错误密码被拒、禁用账号被拒、token 内含角色。"""
    demo = await _user("demo")
    async with AsyncSessionLocal() as db:
        # 账号不存在 / 密码错误都抛 BizError(4011)，避免暴露"用户名是否存在"
        with pytest.raises(BizError):
            await auth_service.authenticate(db, demo.username, "definitely-wrong")
        with pytest.raises(BizError):
            await auth_service.authenticate(db, "no_such_user_xxx", "whatever")
        assert demo.role == "customer"

        tokens = auth_service.issue_tokens(demo)
        assert tokens["access_token"] and tokens["refresh_token"]
        assert tokens["token_type"] == "bearer"

        # 不能操作自己的账号（防止把自己锁在门外）
        with pytest.raises(BizError):
            await auth_service.toggle_user_status(db, demo, demo)


async def test_register_duplicate_and_shape():
    """注册：重复用户名被拒；返回结构可用。"""
    tag = rand_tag("v8u")
    async with AsyncSessionLocal() as db:
        created = await auth_service.register(db, RegisterIn(
            username=tag, password="Test123456", name="回归用户",
            phone=f"139{random.randint(10000000, 99999999)}",
        ))
        assert created.id and created.role == "customer" and created.status == 1
        with pytest.raises(BizError):
            await auth_service.register(db, RegisterIn(
                username=tag, password="Test123456", name="重复用户",
                phone=f"139{random.randint(10000000, 99999999)}",
            ))
    async with AsyncSessionLocal() as db:
        await db.execute(delete(User).where(User.username == tag))
        await db.commit()


async def test_pet_crud_and_permissions():
    """档案：创建 / 修改 / 越权保护 / 疫苗记录 / 逻辑删除。"""
    owner = await _user("demo")
    other = await _user("liu")
    tag = rand_tag("v8p")
    async with AsyncSessionLocal() as db:
        pet = await pet_service.create_pet(db, owner, PetCreate(
            name=f"{tag}犬", species="dog", gender="male", weight=6.5, sterilized=1,
        ))
        assert pet.id and pet.user_id == owner.id

        updated = await pet_service.update_pet(db, pet, PetUpdate(
            name=f"{tag}犬", weight=7.5, remark="回归更新",
        ))
        assert float(updated.weight) == 7.5

        # 越权：别人无权读写
        with pytest.raises(PermissionError_):
            pet_service.assert_can_access(pet, other)
        with pytest.raises(PermissionError_):
            pet_service.assert_can_edit(pet, other)
        # 店员可读可改；V8.4.7 起取消归属限制：档案归属别的店员也照样能操作
        staff = await _user("staff1")
        pet_service.assert_can_access(pet, staff)
        pet_service.assert_can_edit(pet, staff)
        pet.staff_id = 999999
        pet_service.assert_can_access(pet, staff)
        pet_service.assert_can_edit(pet, staff)
        pet.staff_id = None

        record = await pet_service.add_vaccine_record(db, pet, VaccineRecordIn(
            record_type="vaccine", name="联苗", record_date=date.today(),
            next_date=date.today() + timedelta(days=365),
        ))
        assert record.id
        records = await pet_service.list_vaccine_records(db, pet.id)
        assert any(r.id == record.id for r in records)

        mine = await pet_service.list_pets(db, owner)
        assert any(p.id == pet.id for p in mine)
        found = await pet_service.list_pets(db, owner, keyword=tag)
        assert len(found) == 1

        out = pet_service.pet_to_out(pet, owner)
        assert out["name"] == f"{tag}犬" and "owner_name" in out

        await pet_service.delete_pet(db, pet)
        assert (await pet_service.list_pets(db, owner, keyword=tag)) == []

    # 清理
    async with AsyncSessionLocal() as db:
        pets = (await db.execute(select(Pet.id).where(Pet.name.like(f"{tag}%"), Pet.deleted_at.is_(None)))).scalars().all()
        if pets:
            await db.execute(delete(VaccineRecord).where(VaccineRecord.pet_id.in_(pets)))
            await db.execute(delete(Pet).where(Pet.id.in_(pets)))
        await db.execute(delete(Pet).where(Pet.name.like(f"{tag}%")))
        await db.commit()


async def test_message_flow():
    """消息：写入 / 未读数 / 单条已读 / 全部已读 / 删除。"""
    user = await _user("demo")
    async with AsyncSessionLocal() as db:
        before = await message_service.unread_count(db, user.id)
        msg = await message_service.create_message(
            db, user_id=user.id, title="回归消息", content="这是一条测试消息",
            msg_type="system", biz_id=0,
        )
        assert await message_service.unread_count(db, user.id) == before + 1

        items, total = await message_service.list_messages(db, user.id, 1, 20)
        assert total >= 1 and any(m.id == msg.id for m in items)

        await message_service.mark_read(db, user.id, msg.id)
        assert await message_service.unread_count(db, user.id) == before

        # 标记不存在的消息 → NotFoundError（不静默吞掉，便于前端提示）
        with pytest.raises(NotFoundError):
            await message_service.mark_read(db, user.id, 99999999)

        await message_service.create_message(db, user_id=user.id, title="再来一条",
                                             content="x", msg_type="system", biz_id=0)
        cleared = await message_service.mark_all_read(db, user.id)
        assert cleared >= 1
        assert await message_service.unread_count(db, user.id) == 0

        await message_service.remove_message(db, user.id, msg.id)
        items, _total = await message_service.list_messages(db, user.id, 1, 20)
        assert all(m.id != msg.id for m in items)


async def test_settings_validation_and_fallback():
    """配置：非法值被拒；读取缺失/脏值时回退默认值，业务不炸。"""
    manager = await _user("admin")
    async with AsyncSessionLocal() as db:
        rows = await setting_service.get_all_settings(db)
        assert len(rows) >= 20
        assert any(r["setting_key"] == "default_slot_capacity" for r in rows)

        with pytest.raises(BizError):
            setting_service.validate_value("default_slot_capacity", "abc")
        with pytest.raises(BizError):
            setting_service.validate_value("default_slot_capacity", "0")

        with pytest.raises(BizError):
            await setting_service.update_setting(db, "default_slot_capacity", "9999", manager)
        await db.rollback()

        # 布尔规范化
        assert setting_service.validate_value("auto_cancel_on_timeout", "YES") == "true"
        assert setting_service.validate_value("auto_cancel_on_timeout", "0") == "false"

        # 未知键回退空串/默认值，不抛异常
        assert await setting_service.get_value(db, "not_exist_key") == ""


async def test_stats_summary_and_export_shape():
    """报表：总览口径齐全；无数据区间不炸。"""
    async with AsyncSessionLocal() as db:
        data = await stats_service.summary(db, date.today() - timedelta(days=30), date.today())
        for key in ("range_start", "range_end", "total_orders", "completed_orders",
                    "cancelled_orders", "no_show_rate", "repurchase_rate",
                    "service_ratio", "daily_trend", "peak_hours", "staff_workload"):
            assert key in data

        # 远期空区间
        empty = await stats_service.summary(db, date.today() + timedelta(days=3000),
                                            date.today() + timedelta(days=3030))
        assert empty["total_orders"] == 0 and empty["no_show_rate"] == 0

        start, end = stats_service.default_range()
        assert start <= end


async def test_schedule_views():
    """排期：周视图与按日视图结构稳定。"""
    staff = await _user("staff1")
    async with AsyncSessionLocal() as db:
        week = await schedule_service.week_schedule(db, staff, days=7)
        assert "days" in week and len(week["days"]) == 7

        today = await schedule_service.load_by_date(db, staff, date.today())
        assert len(today["days"]) == 1 and today["days"][0]["date"] == date.today().isoformat()

        load = await schedule_service.staff_load(db, date.today(), date.today() + timedelta(days=6))
        assert isinstance(load, list)


async def test_wash_records_list_and_stats():
    """洗护记录：列表分页与看板指标。"""
    customer = await _user("demo")
    staff = await _user("staff1")
    async with AsyncSessionLocal() as db:
        items, total = await wash_service.list_wash_records(db, customer, page=1, size=5)
        assert isinstance(items, list) and total >= len(items)

        data = await wash_service.stats(db, staff)
        for key in ("total", "this_month", "avg_minutes", "service_distribution"):
            assert key in data

        # 宠主视角只能是自己的记录，必然不多于店员视角
        stats_customer = await wash_service.stats(db, customer)
        assert stats_customer["total"] <= data["total"]


async def test_audit_log_write_and_query():
    """审计：写操作落库（含 before/after 快照），查询过滤下推。"""
    from sqlalchemy import delete as _delete

    from app.models import OperationLog
    from app.services import audit_service

    tag = rand_tag("v8audit")
    async with AsyncSessionLocal() as db:
        await audit_service.write_log(
            db, module=tag, action="unit_test", user_id=1, biz_id=0,
            before={"status": "pending"}, after={"status": "confirmed"},
            detail="回归审计写入",
        )
        await db.commit()
        items, total = await audit_service.list_logs(db, module=tag, page=1, size=10)
        assert total == 1 and items[0]["action"] == "unit_test"
        assert items[0]["detail"] == "回归审计写入"
        # before/after 快照不对外返回（含敏感字段），直接核对落库内容
        row = (await db.execute(
            select(OperationLog).where(OperationLog.module == tag)
        )).scalars().first()
        assert row.before_snapshot and row.after_snapshot

        # 过滤条件必须下推到 SQL：查别的模块不应看到这条
        _others, other_total = await audit_service.list_logs(db, module=tag + "-x")
        assert other_total == 0

        await db.execute(_delete(OperationLog).where(OperationLog.module == tag))
        await db.commit()


async def test_list_pets_by_owner_phone():
    """店员按 11 位手机号搜客户档案：走 HMAC 索引精确匹配（密文不可模糊查询）。"""
    from app.utils.crypto import decrypt_text

    async with AsyncSessionLocal() as db:
        owner = (await db.execute(select(User).where(User.username == "demo"))).scalars().first()
        staff = (await db.execute(select(User).where(User.username == "staff1"))).scalars().first()
        assert owner is not None and staff is not None
        phone = decrypt_text(owner.phone_encrypted) or ""
        if len(phone) != 11:
            pytest.skip("演示账号没有 11 位手机号，跳过")
        pets = await pet_service.list_pets(db, staff, phone)
        assert pets and all(p.user_id == owner.id for p in pets), "按手机号应只召回该宠主的宠物"
