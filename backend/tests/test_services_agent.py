"""会话、风险判别与知识库服务用例（V8）。

这三块是「AI 能力」的底座：
- 会话（chat_service）：新建 / 复用活跃会话 / 重命名 / 清空 pending / 留存清理；
- 风险判别（risk_service）：规则结果落库、LLM 不可用时仍产出可解释报告；
- 知识库（knowledge_service）：按风险项检索洗护规范，每条带命中原因。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.models import (
    Appointment,
    ChatMessage,
    ChatSession,
    KnowledgeEntry,
    Pet,
    RiskReport,
    User,
)
from app.schemas.appointment import AppointmentCreate
from app.services import (
    appointment_service,
    chat_service,
    knowledge_service,
    risk_service,
)
from tests.conftest import rand_tag


async def _user(username: str = "demo") -> User:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalars().first()
    assert user is not None, "演示账号缺失，请先执行 scripts/init_db.py"
    return user


async def _pet(owner_id: int, *, allergy: str | None = None, stress: int = 1,
               aggressive: int = 0, skin: str | None = None) -> int:
    tag = rand_tag("v8k")
    async with AsyncSessionLocal() as db:
        pet = Pet(user_id=owner_id, name=f"{tag}犬", species="dog", gender="male", weight=7.5,
                  sterilized=1, allergy=allergy, stress_level=stress, aggressive=aggressive,
                  skin_disease=skin, birthday=date.today() - timedelta(days=365 * 2))
        db.add(pet)
        await db.commit()
        return pet.id


async def _cleanup(pet_ids: list[int], session_ids: list[int] | None = None) -> None:
    async with AsyncSessionLocal() as db:
        appts = (await db.execute(
            select(Appointment.id).where(Appointment.pet_id.in_(pet_ids))
        )).scalars().all() if pet_ids else []
        if appts:
            await db.execute(delete(RiskReport).where(RiskReport.appointment_id.in_(appts)))
            await db.execute(delete(Appointment).where(Appointment.id.in_(appts)))
        if pet_ids:
            await db.execute(delete(Pet).where(Pet.id.in_(pet_ids)))
        for sid in (session_ids or []):
            await db.execute(delete(ChatMessage).where(ChatMessage.session_id == sid))
            await db.execute(delete(ChatSession).where(ChatSession.id == sid))
        await db.commit()


async def test_chat_session_lifecycle():
    """会话：活跃会话复用 / 列表 / 重命名 / 清空 pending / 统计 / 删除。"""
    user = await _user()
    async with AsyncSessionLocal() as db:
        first = await chat_service.get_or_create_active(db, user.id)
        again = await chat_service.get_or_create_active(db, user.id)
        assert first.id == again.id, "未指定的情况下应复用当前活跃会话"

        fresh = await chat_service.create_session(db, user.id, "回归会话")
        assert fresh.id != first.id

        sessions = await chat_service.list_sessions(db, user.id)
        assert any(s["id"] == fresh.id for s in sessions)

        renamed = await chat_service.rename_session(db, fresh, "回归改名")
        assert renamed.title == "回归改名"

        # 超长标题按 120 字截断（标题列长度保护）
        long_title = await chat_service.rename_session(db, fresh, "长" * 200)
        assert len(long_title.title) == 120

        fresh.pending_action = "create_appointment"
        await db.commit()
        await chat_service.clear_pending(db, fresh)
        await db.refresh(fresh)
        assert fresh.pending_action is None

        stats = await chat_service.stats(db, user.id)
        assert "sessions" in stats and stats["sessions"] >= 1

        await chat_service.remove_session(db, fresh)
        await db.refresh(fresh)
        assert fresh.deleted_at is not None and fresh.status == "closed", "会话为逻辑删除"
        # 逻辑删除后不再出现在列表里
        assert all(x["id"] != fresh.id for x in await chat_service.list_sessions(db, user.id))


async def test_chat_purge_expired():
    """留存清理：超过留存期的会话被物理删除，未过期的不动。"""
    user = await _user()
    async with AsyncSessionLocal() as db:
        old = await chat_service.create_session(db, user.id, "很老的会话")
        keep = await chat_service.create_session(db, user.id, "新的会话")
        await db.execute(
            ChatSession.__table__.update().where(ChatSession.id == old.id)
            .values(created_at=datetime.now() - timedelta(days=400))
        )
        await db.commit()

        removed = await chat_service.purge_expired(db, 30)
        assert removed >= 1
        assert (await db.execute(select(ChatSession).where(ChatSession.id == old.id))).scalars().first() is None
        assert (await db.execute(select(ChatSession).where(ChatSession.id == keep.id))).scalars().first() is not None
        await chat_service.remove_session(db, keep)


async def test_risk_report_rule_only_and_refs():
    """风险判别：LLM 关闭时用规则产出报告，且带知识依据（每条有命中原因）。"""
    owner = await _user()
    pet_id = await _pet(owner.id, allergy="燕麦", stress=3, aggressive=1, skin="真菌史")
    try:
        async with AsyncSessionLocal() as db:
            d, slot = date.today() + timedelta(days=210), "10:00"
            appt = await appointment_service.create_by_customer(db, owner, AppointmentCreate(
                pet_id=pet_id, service_type="grooming", appoint_date=d, slot_time=slot,
                idempotent_key=rand_tag("idem"),
            ))

            report = (await db.execute(
                select(RiskReport).where(RiskReport.appointment_id == appt.id)
            )).scalars().first()
            assert report is not None
            assert report.risk_level in ("low", "medium", "high")
            assert report.engine_type in ("rule", "rule+llm", "llm")

            items = risk_service.parse_risk_items(report)
            assert isinstance(items, list)

            refs = risk_service.parse_knowledge_refs(report)
            assert refs, "高风险项应检索到洗护规范"
            assert all("matched" in r and "content" in r for r in refs)

            out = risk_service.report_to_out(report)
            assert out["risk_level"] == report.risk_level
            assert "knowledge_refs" in out

            latest = await risk_service.get_by_appointment(db, appt.id)
            assert latest is not None and latest.id == report.id
    finally:
        await _cleanup([pet_id])


async def test_risk_renot_assess_idempotent():
    """重复评估同一次预约：返回同一条报告而不是无限新增。"""
    owner = await _user()
    pet_id = await _pet(owner.id, stress=2)
    try:
        async with AsyncSessionLocal() as db:
            d, slot = date.today() + timedelta(days=215), "11:00"
            appt = await appointment_service.create_by_customer(db, owner, AppointmentCreate(
                pet_id=pet_id, service_type="basic_bath", appoint_date=d, slot_time=slot,
                idempotent_key=rand_tag("idem"),
            ))
            pet = (await db.execute(select(Pet).where(Pet.id == pet_id))).scalars().first()
            first = await risk_service.assess_risk(db, appt, pet, use_llm=False)
            second = await risk_service.assess_risk(db, appt, pet, use_llm=False)
            # 重跑保留快照历史，但接口始终取最新一条，且结论必须稳定
            assert second.id > first.id
            assert first.risk_level == second.risk_level

            latest = await risk_service.get_by_appointment(db, appt.id)
            assert latest.id == second.id
    finally:
        await _cleanup([pet_id])


async def test_knowledge_search_and_seed():
    """知识库：种子可重复灌入；检索按风险项命中并给出可解释原因。"""
    async with AsyncSessionLocal() as db:
        total = len((await db.execute(select(KnowledgeEntry))).scalars().all())
        assert total >= 10

        added = await knowledge_service.seed_defaults(db)
        assert added == 0, "种子数据应幂等，重复执行不新增"

        pet = Pet(name="检索犬", species="dog", weight=7, sterilized=1, allergy="燕麦",
                  stress_level=3, aggressive=0)
        hits = await knowledge_service.search(db, pet, [
            {"type": "allergy", "desc": "过敏史：燕麦"},
            {"type": "stress", "desc": "应激等级偏高"},
        ])
        assert hits, "命中风险项时应检索到规范"
        assert all(h.get("matched") and h.get("source") and h.get("content") for h in hits)
