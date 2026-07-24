"""洗护风险判别服务。

链路：**规则引擎初筛（保证业务正确性）→ LLM-RAG 增强（提升效率）→ 异常回退规则结果**。
LLM 只做措辞与建议，不新增无依据的高风险项，也不执行任何写操作。
"""
from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import EngineType, RiskLevel
from app.models import Appointment, Pet, RiskReport
from app.services import knowledge_service
from app.utils.datetime_util import calc_age_month
from app.utils.logger import logger

DISCLAIMER = (
    "本报告由系统风险判别引擎（规则初筛 + AI 辅助）自动生成，"
    "仅作洗护安全辅助提示，不构成任何医疗诊断，请店员现场复核后执行。"
)

# 规则表：命中即计入风险项。level 决定整体风险等级下限。
_RULES: list[tuple[str, str, str, str]] = [
    # (key, level, 命中条件说明, 处置建议)
    ("aggressive", RiskLevel.HIGH.value, "宠物有攻击倾向标记", "建议双人操作，佩戴伊丽莎白圈并加装防咬嘴套"),
    ("stress_high", RiskLevel.HIGH.value, "应激等级为重（3 级）", "建议缩短洗护时长，使用免水洗或分次完成"),
    ("skin_disease", RiskLevel.HIGH.value, "档案存在皮肤病史", "建议与宠主确认病灶，使用独立工具并消毒，排查传染性皮肤病"),
    ("allergy", RiskLevel.HIGH.value, "档案存在过敏史", "建议核对洗护产品成分，避开已知过敏原"),
    ("senior_pet", RiskLevel.LOW.value, "宠物年龄超过 8 岁（约 96 月龄）", "建议降低水温与吹风温度，控制操作时长"),
    ("low_weight", RiskLevel.LOW.value, "体重低于 1kg 或超过 60kg", "建议使用适配大小的浴缸与保定带，全程看护"),
    ("stress_mid", RiskLevel.LOW.value, "应激等级为中（2 级）", "建议安排安静时段，减少吹风噪音刺激"),
    ("not_sterilized", RiskLevel.LOW.value, "未绝育", "建议与宠主确认发情期，避开特殊生理期安排"),
]

LEVEL_ORDER = {RiskLevel.NONE.value: 0, RiskLevel.LOW.value: 1, RiskLevel.HIGH.value: 2}


def evaluate_by_rule(pet: Pet) -> dict:
    """规则引擎初筛，返回风险项 + 等级 + 建议。"""
    matched: list[dict] = []

    def hit(key: str, level: str, desc: str, advice: str) -> None:
        """规则命中判定：给定等级与关键词列表，返回是否应在建议里提这一条。


        """
        matched.append({"key": key, "level": level, "desc": desc, "advice": advice})

    rule_map = {r[0]: r for r in _RULES}

    if pet.aggressive == 1:
        hit(*rule_map["aggressive"])
    if pet.stress_level >= 3:
        hit(*rule_map["stress_high"])
    elif pet.stress_level == 2:
        hit(*rule_map["stress_mid"])
    if (pet.skin_disease or "").strip():
        hit(*rule_map["skin_disease"])
    if (pet.allergy or "").strip():
        hit(*rule_map["allergy"])
    if pet.birthday is not None:
        months = calc_age_month(pet.birthday) or 0
        if months >= 96:
            hit(*rule_map["senior_pet"])
    if pet.weight is not None and (float(pet.weight) < 1 or float(pet.weight) > 60):
        hit(*rule_map["low_weight"])
    if pet.sterilized == 0:
        hit(*rule_map["not_sterilized"])

    level = RiskLevel.NONE.value
    for item in matched:
        if LEVEL_ORDER[item["level"]] > LEVEL_ORDER[level]:
            level = item["level"]

    high_items = [i["desc"] for i in matched if i["level"] == RiskLevel.HIGH.value]
    low_items = [i["desc"] for i in matched if i["level"] == RiskLevel.LOW.value]
    if matched:
        summary = (
            f"共命中 {len(matched)} 项风险："
            + "；".join([f"【高风险】{d}" for d in high_items] + [f"【低风险】{d}" for d in low_items])
        )
    else:
        summary = "未命中任何风险规则，可正常安排洗护。"

    suggestion = "；".join(dict.fromkeys(i["advice"] for i in matched)) or "按标准流程执行洗护即可。"
    return {
        "risk_level": level,
        "risk_items": matched,
        "summary": summary,
        "suggestion": suggestion,
        "engine_type": EngineType.RULE.value,
    }


async def _enhance_with_llm(
    pet: Pet, appointment: Appointment, rule_result: dict, knowledge: list[dict] | None = None
) -> dict | None:
    """调用百炼免费额度模型增强风险摘要。

    失败（未配 Key / 超时 / 报错 / 输出非法）一律返回 None，由调用方回退规则结果，
    保证「AI 不可用时业务照常运行」。LLM 只能措辞与排序，不得新增无依据的风险项。
    """
    from app.agent.llm.client import bailian_client
    from app.agent.llm.prompts import build_risk_messages
    from app.config import settings

    if not settings.llm_available:
        return None

    messages = build_risk_messages(
        pet_name=pet.name,
        species=pet.species,
        breed=pet.breed or "",
        age_month=str(calc_age_month(pet.birthday) or ""),
        weight=str(pet.weight or ""),
        allergy=pet.allergy or "",
        skin_disease=pet.skin_disease or "",
        stress_level=str(pet.stress_level),
        aggressive=str(pet.aggressive),
        service_type=appointment.service_type,
        rule_level=rule_result["risk_level"],
        rule_items="；".join(i["desc"] for i in rule_result["risk_items"]) or "无",
        rule_advice=rule_result["suggestion"],
        knowledge="\n".join(f"- {k['title']}：{k['content']}" for k in (knowledge or [])),
    )
    # 同 Agent：任何异常都回退规则结果，风险报告不能因为 AI 抖动而生成失败
    try:
        result = await bailian_client.chat_with_fallback(messages, json_mode=True, temperature=0.2)
    except Exception as exc:  # pragma: no cover - 兜底分支，混沌测试覆盖
        logger.warning("llm_risk_enhance_exception: %s", exc)
        return None
    if not result.ok:
        logger.warning("llm_risk_enhance_failed", extra={"extra_fields": {"error": result.error}})
        return None

    data = result.data
    if not data:
        logger.warning("llm_risk_enhance_bad_json")
        return None

    summary = str(data.get("summary") or "").strip()
    suggestion = str(data.get("suggestion") or "").strip()
    if not summary:
        return None

    # 关键约束：LLM 不得上调风险等级或新增无依据的高风险项
    llm_level = str(data.get("risk_level") or "").strip().lower()
    level = rule_result["risk_level"]
    if llm_level in LEVEL_ORDER and LEVEL_ORDER[llm_level] <= LEVEL_ORDER[level]:
        level = max([level, llm_level], key=lambda x: LEVEL_ORDER[x])

    cautions = data.get("cautions")
    if isinstance(cautions, list) and cautions:
        suggestion = suggestion + "｜注意事项：" + "；".join(str(c) for c in cautions[:4])

    return {
        "risk_level": level,
        "summary": summary,
        "suggestion": suggestion,
        "engine_type": EngineType.LLM.value,
        "model": result.model,
        "latency_ms": result.latency_ms,
    }


async def assess_risk(
    db: AsyncSession, appointment: Appointment, pet: Pet, *, use_llm: bool | None = None
) -> RiskReport:
    """生成风险报告快照并落库。

    链路：规则引擎初筛（保证业务正确性）→ LLM-RAG 增强（提升效率）→ 异常自动回退规则结果。
    同时把风险等级回写到预约单，便于列表展示。
    """
    result = evaluate_by_rule(pet)
    llm_meta: dict | None = None

    # RAG 检索：按规则命中项 + 档案关键词取洗护安全规范，作为建议依据（零依赖、可解释）
    knowledge = await knowledge_service.search(db, pet, result["risk_items"])

    should_use_llm = settings.llm_available if use_llm is None else (use_llm and settings.llm_available)
    if should_use_llm:
        llm_meta = await _enhance_with_llm(pet, appointment, result, knowledge)
        if llm_meta:
            result["risk_level"] = llm_meta["risk_level"]
            result["summary"] = llm_meta["summary"]
            result["suggestion"] = llm_meta["suggestion"]
            result["engine_type"] = llm_meta["engine_type"]

    report = RiskReport(
        appointment_id=appointment.id,
        pet_id=pet.id,
        risk_level=result["risk_level"],
        engine_type=result["engine_type"],
        risk_items=json.dumps(result["risk_items"], ensure_ascii=False),
        ai_summary=f"{result['summary']}\n\n【免责声明】{DISCLAIMER}",
        suggestion=result["suggestion"],
        knowledge_refs=json.dumps(knowledge, ensure_ascii=False),
    )
    db.add(report)
    appointment.risk_level = result["risk_level"]
    await db.flush()
    if llm_meta:
        logger.info(
            "llm_risk_enhanced",
            extra={"extra_fields": {"appointment_id": appointment.id, "model": llm_meta["model"],
                                    "latency_ms": llm_meta["latency_ms"]}},
        )
    return report


def parse_risk_items(report: RiskReport | None) -> list[dict]:
    """解析风险项 JSON，坏数据返回空数组而不是抛错（旧数据不能把接口打挂）。"""
    if report is None or not report.risk_items:
        return []
    try:
        return json.loads(report.risk_items)
    except (ValueError, TypeError):
        return []


def parse_knowledge_refs(report: RiskReport) -> list[dict]:
    """解析知识依据（RAG 检索结果），坏数据不让接口炸。"""
    try:
        data = json.loads(report.knowledge_refs or "[]")
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []


def report_to_out(report: RiskReport, pet: Pet | None = None, appointment: Appointment | None = None) -> dict:
    """报告序列化：风险等级/命中项/建议/知识依据 + 引擎类型。"""
    from app.constants import RISK_LEVEL_LABEL

    return {
        "id": report.id,
        "appointment_id": report.appointment_id,
        "pet_id": report.pet_id,
        "pet_name": pet.name if pet else None,
        "order_no": appointment.order_no if appointment else None,
        "appoint_date": appointment.appoint_date if appointment else None,
        "slot_time": appointment.slot_time if appointment else None,
        "risk_level": report.risk_level,
        "risk_level_label": RISK_LEVEL_LABEL.get(report.risk_level, report.risk_level),
        "engine_type": report.engine_type,
        "risk_items": parse_risk_items(report),
        "knowledge_refs": parse_knowledge_refs(report),
        "ai_summary": report.ai_summary,
        "suggestion": report.suggestion,
        "confirmed": report.confirmed,
        "confirmed_by": report.confirmed_by,
        "confirmed_at": report.confirmed_at,
        "handle_measure": report.handle_measure,
        "invalidated": report.invalidated,
        "created_at": report.created_at,
    }


async def get_by_appointment(db: AsyncSession, appointment_id: int) -> RiskReport | None:
    """取某次预约**最新**一份风险报告（重跑会留历史快照，接口只要最新的）。"""
    from sqlalchemy import select

    return (
        await db.execute(
            select(RiskReport)
            .where(RiskReport.appointment_id == appointment_id)
            .order_by(RiskReport.id.desc())
        )
    ).scalars().first()


async def list_reports(
    db: AsyncSession, *, page: int = 1, size: int = 10, only_unconfirmed: bool = False
) -> tuple[list[dict], int]:
    """风险报告分页（风险复核页用），可按等级与状态筛选。"""
    from sqlalchemy import func, select

    cond = [RiskReport.invalidated == 0]
    if only_unconfirmed:
        cond.append(RiskReport.confirmed == 0)
    total = await db.scalar(select(func.count()).select_from(RiskReport).where(*cond)) or 0
    rows = (
        await db.execute(
            select(RiskReport, Pet, Appointment)
            .outerjoin(Pet, Pet.id == RiskReport.pet_id)
            .outerjoin(Appointment, Appointment.id == RiskReport.appointment_id)
            .where(*cond)
            .order_by(RiskReport.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).all()
    return [report_to_out(r, p, a) for r, p, a in rows], int(total)


async def confirm_report(
    db: AsyncSession, report: RiskReport, staff_id: int, handle_measure: str | None
) -> RiskReport:
    """店员复核确认：记录复核人、结论与时间。"""
    from datetime import datetime

    report.confirmed = 1
    report.confirmed_by = staff_id
    report.confirmed_at = datetime.now()
    report.handle_measure = handle_measure
    await db.flush()
    return report

