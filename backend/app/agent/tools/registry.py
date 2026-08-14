"""Agent 工具集（8 个）。

铁律：所有工具**只调用业务服务层 / 只读查询**，绝不拼 SQL、绝不绕过权限与状态机。
写操作由 Graph Workflow 的「确认闸门」控制，LLM 只能决定「调用哪个工具」。
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    APPOINTMENT_STATUS_LABEL,
    BOARDING_STATUS_LABEL,
    DROPOFF_METHOD_LABEL,
    FEEDING_PLAN_LABEL,
    PICKUP_BACK_METHOD_LABEL,
    REASON_REQUIRED_STATUS,
    RISK_LEVEL_LABEL,
    SERVICE_TYPE_LABEL,
    AppointmentStatus,
    ServiceType,
    UserRole,
)
from app.models import Appointment, BoardingRoom, CartItem, Pet, Product, ProductSku, User
from app.agent.tools.profiles import ROLE_TOOL_PROFILE
from app.schemas.appointment import AppointmentCreate, RescheduleIn, StaffAppointmentCreate
from app.schemas.boarding import BoardingOrderCreate, CarePlanIn
from app.schemas.goods import CartAddIn, GoodsOrderCreateIn
from app.schemas.pet import PetCreate
from app.services import appointment_service, boarding_service, goods_service, pet_service, risk_service, setting_service
from app.utils.crypto import decrypt_text, mask_phone, phone_hmac
from app.utils.datetime_util import gen_random_str
from app.utils.exceptions import BizError, NotFoundError, PermissionError_
from app.utils.logger import logger


class ToolContext:
    """工具执行上下文：只暴露会话、用户与请求对象，不暴露原始 SQL 能力。"""

    __slots__ = ("db", "user", "request", "idempotent_key")

    def __init__(self, db: AsyncSession, user: User, request=None, idempotent_key: str | None = None):
        self.db = db
        self.user = user
        self.request = request
        self.idempotent_key = idempotent_key


TOOLS: dict[str, dict[str, Any]] = {}
WRITE_TOOLS: set[str] = set()


def tool(
    name: str,
    description: str,
    write: bool = False,
    roles: tuple[str, ...] | None = None,
):
    """登记一个 Agent 工具。

    roles: 允许调用该工具的角色白名单；None 表示三角色皆可。
           注意「角色允许」不等于「可调用」—— 还必须在 ROLE_TOOL_PROFILE 画像内。
    """
    def wrapper(fn: Callable) -> Callable:
        # 记录处理函数声明的参数名（排除 ctx），用于剔除无关槽位：
        # LLM 可能给出该工具根本不接受的参数（例如问「今天要处理什么」时带上日期），
        # 直接透传会 TypeError，因此调用前必须按签名过滤。
        import inspect

        params = tuple(p for p in inspect.signature(fn).parameters if p != "ctx")
        TOOLS[name] = {
            "name": name,
            "description": description,
            "write": write,
            "roles": tuple(roles) if roles else None,
            "params": params,
            "handler": fn,
        }
        if write:
            WRITE_TOOLS.add(name)
        return fn

    return wrapper


# ---------------------------------------------------------------- 只读工具
@tool("query_slots", "查询指定日期的可预约时段与剩余容量")
async def query_slots(ctx: ToolContext, appoint_date: str | None = None) -> dict:
    """查询指定日期的可预约时段与剩余容量。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    target = parse_date(appoint_date) or date.today()
    capacity = await setting_service.get_int(ctx.db, "default_slot_capacity")
    rows = (
        await ctx.db.execute(
            select(Appointment.slot_time, func.count())
            .where(
                Appointment.appoint_date == target,
                Appointment.status.in_(
                    ["pending", "confirmed", "arrived", "in_service", "completed"]
                ),
            )
            .group_by(Appointment.slot_time)
        )
    ).all()
    used = {slot: int(c) for slot, c in rows}
    slots = []
    for slot in settings.slot_list():
        taken = used.get(slot, 0)
        slots.append({
            "slot_time": slot,
            "remain": max(capacity - taken, 0),
            "capacity": capacity,
            "available": taken < capacity,
        })
    return {
        "appoint_date": target.isoformat(),
        "capacity": capacity,
        "slots": slots,
        "available_count": sum(1 for s in slots if s["available"]),
    }


@tool("query_pet_profile", "查询当前用户的宠物档案（含过敏史、皮肤病史、应激等级、攻击倾向）")
async def query_pet_profile(ctx: ToolContext, pet_name: str | None = None) -> dict:
    """查询当前用户的宠物档案（含过敏史、皮肤病史、应激等级、攻击倾向）。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    cond = [Pet.deleted_at.is_(None)]
    if ctx.user.role == UserRole.CUSTOMER.value:
        cond.append(Pet.user_id == ctx.user.id)
    if pet_name:
        cond.append(Pet.name.like(f"%{pet_name}%"))
    pets = (await ctx.db.execute(select(Pet).where(*cond))).scalars().all()
    from app.services.pet_service import pet_to_out

    return {"count": len(pets), "pets": [pet_to_out(p) for p in pets]}


@tool("query_my_appointments", "查询当前用户的预约列表")
async def query_my_appointments(ctx: ToolContext, status: str | None = None) -> dict:
    """查询当前用户的预约列表。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    items, total = await appointment_service.list_appointments(
        ctx.db, ctx.user, page=1, size=5, status=status or None
    )
    return {"total": total, "items": items}


@tool("query_risk_report", "查询某笔预约的洗护风险报告与处置建议")
async def query_risk_report(ctx: ToolContext, order_no: str | None = None) -> dict:
    """查询某笔预约的洗护风险报告与处置建议。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    cond = [Appointment.deleted_at.is_(None)]
    if ctx.user.role == UserRole.CUSTOMER.value:
        cond.append(Appointment.user_id == ctx.user.id)
    if order_no:
        cond.append(Appointment.order_no == order_no)
    appt = (
        await ctx.db.execute(select(Appointment).where(*cond).order_by(Appointment.id.desc()))
    ).scalars().first()
    if appt is None:
        raise NotFoundError("没有找到对应的预约")
    report = await risk_service.get_by_appointment(ctx.db, appt.id)
    if report is None:
        raise NotFoundError("该预约暂无风险报告")
    data = risk_service.report_to_out(report)
    data["order_no"] = appt.order_no
    return data


@tool("search_knowledge", "检索门店洗护安全规范（过敏 / 皮肤病 / 应激 / 用药 / 老年宠物）")
async def search_knowledge(
    ctx: ToolContext, query: str | None = None, pet_name: str | None = None
) -> dict:
    """检索洗护安全知识库，回答「怎么洗 / 要注意什么」这类规范问题。

    只读工具：仅检索，可直接执行；不改变任何业务状态。

    与风险报告里的 RAG 是同一条知识底座、同一套打分（`knowledge_service._score_entries`），
    区别是这里没有规则命中项，靠「条目词表反向匹配用户问题」召回；给了宠物名时叠加档案关键词。
    """
    from app.services import knowledge_service

    q = (query or "").strip()
    pet = None
    if pet_name:
        # 查规范不该因为「宠物名没对上」而失败：找不到档案就退化为通用规范检索
        try:
            pet = await _pick_pet(ctx, pet_name)
        except BizError:
            pet = None
    if not q and pet is None:
        raise BizError("想查哪方面的规范？比如「皮肤病的狗怎么洗」「疫苗后多久能洗澡」🐾")

    # 检索是「可降级能力」：向量库、embedding、依赖任何一环炸了，都不能让整条消息失败
    # （用户会看到「系统开小差」，误以为 RAG 没实现）。异常一律退回标签匹配，再不行给空列表 + 明确提示。
    try:
        items = await knowledge_service.search_by_query(ctx.db, q, pet, limit=3)
    except Exception as exc:
        logger.warning("knowledge_search_failed", extra={"extra_fields": {
            "query": (q or "")[:60], "error": str(exc)[:200]}})
        items = []
        try:
            items = await knowledge_service.search_by_text(ctx.db, q, pet, limit=3)
        except Exception:
            items = []
    if not q and pet is not None:
        # 只给了宠物、没给问题：按档案命中的风险项取规范，等价于风险报告里的那几条依据
        rule = risk_service.evaluate_by_rule(pet)
        items = await knowledge_service.search(ctx.db, pet, rule["risk_items"], limit=3)
    return {
        "query": q or None,
        "pet_name": pet.name if pet else None,
        "total": len(items),
        "items": [
            {"title": i["title"], "section": i.get("section") or "",
             "content": i["content"], "source": i["source"],
             "category": i["category"], "matched": i["matched"]}
            for i in items
        ],
    }


@tool("query_report_summary", "查询门店经营统计（订单量、爽约率、复购率等）",
      roles=(UserRole.STAFF.value, UserRole.MANAGER.value))
async def query_report_summary(ctx: ToolContext, days: int | None = None) -> dict:
    """查询门店经营统计（订单量、爽约率、复购率等）。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    from app.services import stats_service

    span = int(days or 30)
    end = date.today()
    start = end - timedelta(days=span - 1)
    data = await stats_service.summary(ctx.db, start, end)
    return {
        "range": f"{data['range_start']} ~ {data['range_end']}",
        "total_orders": data["total_orders"],
        "completed_orders": data["completed_orders"],
        "no_show_rate": data["no_show_rate"],
        "repurchase_rate": data["repurchase_rate"],
        "churn_count": len(data["churn_pets"]),
        "service_ratio": data["service_ratio"],
    }


# ---------------------------------------------------------------- 受控写工具
@tool("create_appointment", "为宠主创建洗护预约（需用户二次确认后执行）", write=True)
async def create_appointment(
    ctx: ToolContext,
    pet_name: str,
    appoint_date: str,
    slot_time: str,
    service_type: str | None = None,
) -> dict:
    """为宠主创建洗护预约（需用户二次确认后执行）。

    写工具：LLM 只能「请求执行」，真正落库要经过二次确认闸门。
    """
    cond = [Pet.deleted_at.is_(None)]
    if ctx.user.role == UserRole.CUSTOMER.value:
        cond.append(Pet.user_id == ctx.user.id)
    cond.append(Pet.name.like(f"%{pet_name}%"))
    pet = (await ctx.db.execute(select(Pet).where(*cond))).scalars().first()
    if pet is None:
        raise NotFoundError(f"没有找到名为「{pet_name}」的宠物档案，请先在宠物档案中创建")

    target = parse_date(appoint_date)
    if target is None:
        raise BizError("日期格式无法识别，请使用 2026-10-20 或「明天」这类说法")

    key = ctx.idempotent_key or f"agent-{gen_random_str(16)}"
    payload = AppointmentCreate(
        pet_id=pet.id,
        service_type=service_type or ServiceType.BASIC_BATH.value,
        appoint_date=target,
        slot_time=slot_time,
        remark="由 AI 助手代为提交",
        idempotent_key=key,
    )
    appointment = await appointment_service.create_by_customer(ctx.db, ctx.user, payload, ctx.request)
    return {
        "order_no": appointment.order_no,
        "appoint_date": appointment.appoint_date.isoformat(),
        "slot_time": appointment.slot_time,
        "status": appointment.status,
        "status_label": APPOINTMENT_STATUS_LABEL.get(appointment.status, appointment.status),
        "pet_name": pet.name,
        "risk_level": appointment.risk_level,
        "risk_level_label": RISK_LEVEL_LABEL.get(appointment.risk_level or "", "待判别"),
    }


@tool("cancel_appointment", "取消指定预约（需用户二次确认 + 填写原因）", write=True)
async def cancel_appointment(ctx: ToolContext, order_no: str, reason: str | None = None) -> dict:
    """取消指定预约（需用户二次确认 + 填写原因）。

    写工具：LLM 只能「请求执行」，真正落库要经过二次确认闸门。
    """
    appointment = await appointment_service.get_appointment_for_user(
        ctx.db, await _resolve_appointment_id(ctx, order_no), ctx.user
    )
    before = appointment.status
    appointment = await appointment_service.change_status(
        ctx.db, appointment, AppointmentStatus.CANCELLED.value, ctx.user,
        reason or "用户通过 AI 助手取消", ctx.request,
    )
    return {
        "order_no": appointment.order_no,
        "from_status": APPOINTMENT_STATUS_LABEL.get(before, before),
        "to_status": APPOINTMENT_STATUS_LABEL.get(appointment.status, appointment.status),
        "reason": appointment.cancel_reason,
    }


@tool("reschedule_appointment", "为客户预约改期（仅店员，需二次确认）", write=True,
      roles=(UserRole.STAFF.value, UserRole.MANAGER.value))
async def reschedule_appointment(
    ctx: ToolContext, order_no: str, appoint_date: str, slot_time: str, reason: str | None = None
) -> dict:
    """为客户预约改期（仅店员，需二次确认）。

    写工具：LLM 只能「请求执行」，真正落库要经过二次确认闸门。
    """
    appointment = await appointment_service.get_appointment_for_user(
        ctx.db, await _resolve_appointment_id(ctx, order_no), ctx.user
    )
    target = parse_date(appoint_date)
    if target is None:
        raise BizError("日期格式无法识别")
    payload = RescheduleIn(appoint_date=target, slot_time=slot_time, reason=reason or "AI 助手改期",
                           idempotent_key=ctx.idempotent_key)
    appointment = await appointment_service.reschedule(ctx.db, appointment, payload, ctx.user, ctx.request)
    return {
        "order_no": appointment.order_no,
        "appoint_date": appointment.appoint_date.isoformat(),
        "slot_time": appointment.slot_time,
        "reschedule_times": appointment.reschedule_times,
    }



# ================================================================
# 店员端工具（运营助理）
# ================================================================
STAFF_ROLES = (UserRole.STAFF.value, UserRole.MANAGER.value)

# 状态口语 → 状态机枚举，方便店员用日常说法推进订单
STATUS_ALIAS: dict[str, str] = {
    "确认": AppointmentStatus.CONFIRMED.value,
    "已确认": AppointmentStatus.CONFIRMED.value,
    "到店": AppointmentStatus.ARRIVED.value,
    "已到店": AppointmentStatus.ARRIVED.value,
    "开始": AppointmentStatus.IN_SERVICE.value,
    "开始洗护": AppointmentStatus.IN_SERVICE.value,
    "洗护中": AppointmentStatus.IN_SERVICE.value,
    "完成": AppointmentStatus.COMPLETED.value,
    "已完成": AppointmentStatus.COMPLETED.value,
    "洗完": AppointmentStatus.COMPLETED.value,
    "取消": AppointmentStatus.CANCELLED.value,
    "爽约": AppointmentStatus.NO_SHOW.value,
    "到店放弃": AppointmentStatus.ARRIVED_GIVE_UP.value,
    "洗护中断": AppointmentStatus.WASH_INTERRUPT.value,
}


@tool("query_day_schedule", "查询指定日期（默认今天）的门店排期：各时段容量、占用与预约明细", roles=STAFF_ROLES)
async def query_day_schedule(ctx: ToolContext, appoint_date: str | None = None) -> dict:
    """查询指定日期（默认今天）的门店排期：各时段容量、占用与预约明细。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    from app.services import schedule_service

    target = parse_date(appoint_date) or date.today()
    data = await schedule_service.load_by_date(ctx.db, ctx.user, target)
    day = data["days"][0]
    return {
        "appoint_date": day["date"],
        "weekday": day["weekday"],
        "total": day["total"],
        "capacity": data["capacity"],
        "slots": [
            {
                "slot_time": s["slot_time"],
                "used": s["used"],
                "capacity": s["capacity"],
                "remain": s["remain"],
                "full": s["full"],
                "appointments": [
                    {
                        "order_no": a["order_no"],
                        "pet_name": a["pet_name"],
                        "owner_name": a["owner_name"],
                        "service_type_label": a["service_type_label"],
                        "status_label": a["status_label"],
                        "risk_level": a["risk_level"],
                    }
                    for a in s["appointments"]
                ],
            }
            for s in day["slots"]
        ],
    }


@tool("query_todo", "查看当前待办（待确认预约 / 待复核风险 / 今日安排）与交班简报", roles=STAFF_ROLES)
async def query_todo(ctx: ToolContext) -> dict:
    """查看当前待办（待确认预约 / 待复核风险 / 今日安排）与交班简报。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    from app.services import wash_service

    today = date.today()
    mine = ctx.user.role == UserRole.STAFF.value

    pending, pending_total = await appointment_service.list_appointments(
        ctx.db, ctx.user, page=1, size=5, status="pending", mine=mine
    )
    today_items, today_total = await appointment_service.list_appointments(
        ctx.db, ctx.user, page=1, size=10, appoint_date=today, mine=mine
    )
    risks, risk_total = await risk_service.list_reports(ctx.db, page=1, size=5, only_unconfirmed=True)
    wash = await wash_service.stats(ctx.db, ctx.user)

    def brief(a: dict) -> dict:
        return {
            "order_no": a["order_no"],
            "pet_name": a["pet_name"],
            "owner_name": a["owner_name"],
            "slot_time": a["slot_time"],
            "service_type_label": a["service_type_label"],
            "status_label": a["status_label"],
            "risk_level": a["risk_level"],
        }

    return {
        "scope": "我的" if mine else "门店",
        "date": today.isoformat(),
        "pending_confirm_total": pending_total,
        "pending_confirm": [brief(a) for a in pending],
        "today_total": today_total,
        "today_items": [brief(a) for a in today_items],
        "risk_unconfirmed_total": risk_total,
        "risk_unconfirmed": [
            {"order_no": r.get("order_no"), "pet_name": r.get("pet_name"),
             "risk_level": r.get("risk_level"), "risk_level_label": r.get("risk_level_label"),
             "hits": len(r.get("risk_items") or [])}
            for r in risks
        ],
        "shift_brief": {
            "wash_total": wash.get("total"),
            "this_month": wash.get("this_month"),
            "avg_minutes": wash.get("avg_minutes"),
        },
    }


@tool("query_customer_pets", "按宠物名 / 宠主姓名 / 手机号查询客户档案（含风险标记）", roles=STAFF_ROLES)
async def query_customer_pets(ctx: ToolContext, keyword: str | None = None) -> dict:
    """按宠物名 / 宠主姓名 / 手机号查询客户档案（含风险标记）。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    from app.services import pet_service
    from app.services.pet_service import pet_to_out

    pets = await pet_service.list_pets(ctx.db, ctx.user, keyword)
    pets = pets[:10]
    owners = await pet_service.owners_map(ctx.db, pets)
    items = []
    for pet in pets:
        owner = owners.get(pet.user_id)
        data = pet_to_out(pet, owner)
        data["owner_phone"] = phone_for(owner, ctx.user) if owner else None
        items.append(data)
    return {"count": len(items), "pets": items, "keyword": keyword or ""}


@tool("query_wash_history", "查询某只宠物的历史洗护记录（上次皮肤毛发状况、使用产品、店员备注）",
      roles=STAFF_ROLES)
async def query_wash_history(ctx: ToolContext, pet_name: str | None = None) -> dict:
    """查询某只宠物的历史洗护记录（上次皮肤毛发状况、使用产品、店员备注）。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    from app.services import pet_service, wash_service

    if not pet_name:
        return {"found": False, "message": "请告诉我宠物名字，例如「豆豆」"}

    pets = await pet_service.list_pets(ctx.db, ctx.user, pet_name)
    if not pets:
        raise NotFoundError(f"没有找到名为「{pet_name}」的宠物档案")
    pet = pets[0]

    records, total = await wash_service.list_wash_records(
        ctx.db, ctx.user, page=1, size=5, pet_id=pet.id
    )
    if not records:
        return {"found": True, "pet_name": pet.name, "total": 0, "records": [],
                "message": f"{pet.name} 还没有洗护记录"}

    last = records[0]
    return {
        "found": True,
        "pet_name": pet.name,
        "total": total,
        "last_visit": last.get("appoint_date"),
        "last": {
            "service_type_label": last.get("service_type_label"),
            "wash_range": [str(last.get("wash_start") or ""), str(last.get("wash_end") or "")],
            "skin_condition": last.get("skin_condition"),
            "hair_condition": last.get("hair_condition"),
            "products": last.get("products"),
            "staff_note": last.get("staff_note"),
        },
        "records": [
            {
                "appoint_date": r.get("appoint_date"),
                "service_type_label": r.get("service_type_label"),
                "skin_condition": r.get("skin_condition"),
                "hair_condition": r.get("hair_condition"),
                "products": r.get("products"),
                "staff_note": r.get("staff_note"),
            }
            for r in records
        ],
    }


@tool("advance_appointment", "推进预约状态（确认 / 到店 / 开始洗护 / 完成等，需二次确认）",
      write=True, roles=STAFF_ROLES)
async def advance_appointment(ctx: ToolContext, order_no: str, target_status: str,
                              reason: str | None = None) -> dict:
    """推进预约状态（确认 / 到店 / 开始洗护 / 完成等，需二次确认）。

    写工具：LLM 只能「请求执行」，真正落库要经过二次确认闸门。
    """
    raw = (target_status or "").strip()
    target = STATUS_ALIAS.get(raw, raw)
    if target not in set(AppointmentStatus):
        raise BizError(
            "状态无法识别，可用：确认 / 到店 / 开始洗护 / 完成 / 取消 / 爽约 / 到店放弃 / 洗护中断"
        )
    if target in REASON_REQUIRED_STATUS and not (reason or "").strip():
        raise BizError(f"变更为「{APPOINTMENT_STATUS_LABEL.get(target, target)}」必须填写原因")

    appointment = await appointment_service.get_appointment_for_user(
        ctx.db, await _resolve_appointment_id(ctx, order_no), ctx.user
    )
    before = appointment.status
    appointment = await appointment_service.change_status(
        ctx.db, appointment, target, ctx.user, reason, ctx.request
    )
    return {
        "order_no": appointment.order_no,
        "from_status": APPOINTMENT_STATUS_LABEL.get(before, before),
        "to_status": APPOINTMENT_STATUS_LABEL.get(appointment.status, appointment.status),
        "reason": appointment.cancel_reason or appointment.terminate_reason,
    }


@tool("confirm_risk", "复核确认某笔预约的洗护风险报告（需二次确认）", write=True, roles=STAFF_ROLES)
async def confirm_risk(ctx: ToolContext, order_no: str, handle_measure: str | None = None) -> dict:
    """复核确认某笔预约的洗护风险报告（需二次确认）。

    写工具：LLM 只能「请求执行」，真正落库要经过二次确认闸门。
    """
    appointment = await appointment_service.get_appointment_for_user(
        ctx.db, await _resolve_appointment_id(ctx, order_no), ctx.user
    )
    report = await risk_service.get_by_appointment(ctx.db, appointment.id)
    if report is None:
        raise NotFoundError("该预约还没有风险报告，可先用 query_risk_report 生成/查看")
    if report.confirmed:
        return {"order_no": appointment.order_no, "already_confirmed": True,
                "message": "该风险报告已复核过，无需重复确认"}
    report = await risk_service.confirm_report(ctx.db, report, ctx.user.id, handle_measure)
    await ctx.db.commit()
    return {
        "order_no": appointment.order_no,
        "already_confirmed": False,
        "risk_level_label": RISK_LEVEL_LABEL.get(report.risk_level, report.risk_level),
        "handle_measure": report.handle_measure,
    }


@tool("create_appointment_for_customer", "代客预约：按宠主手机号下单，宠物无档案时自动临时建档（需二次确认）",
      write=True, roles=STAFF_ROLES)
async def create_appointment_for_customer(
    ctx: ToolContext,
    phone: str,
    pet_name: str,
    appoint_date: str,
    slot_time: str,
    service_type: str | None = None,
) -> dict:
    """代客预约：按宠主手机号下单，宠物无档案时自动临时建档（需二次确认）。

    写工具：LLM 只能「请求执行」，真正落库要经过二次确认闸门。
    """
    raw_phone = (phone or "").strip()
    if not (raw_phone.isdigit() and len(raw_phone) == 11):
        raise BizError("宠主手机号必须为 11 位数字")

    target = parse_date(appoint_date)
    if target is None:
        raise BizError("日期无法识别，请使用 2026-11-20 或「明天」这类说法")

    # 已有档案则复用，避免重复建档
    pet_id: int | None = None
    owner_id = await ctx.db.scalar(
        select(User.id).where(User.phone_hash == phone_hmac(raw_phone))
    )
    if owner_id:
        existing = (
            await ctx.db.execute(
                select(Pet).where(Pet.user_id == owner_id, Pet.deleted_at.is_(None),
                                  Pet.name == pet_name)
            )
        ).scalars().first()
        if existing:
            pet_id = existing.id

    payload = StaffAppointmentCreate(
        pet_id=pet_id,
        phone=raw_phone,
        pet_name=pet_name,
        service_type=service_type or ServiceType.BASIC_BATH.value,
        appoint_date=target,
        slot_time=slot_time,
        remark="由店员通过 AI 助手代客提交",
        idempotent_key=ctx.idempotent_key or f"agent-{gen_random_str(16)}",
    )
    appointment = await appointment_service.create_by_staff(ctx.db, ctx.user, payload, ctx.request)
    return {
        "order_no": appointment.order_no,
        "appoint_date": appointment.appoint_date.isoformat(),
        "slot_time": appointment.slot_time,
        "pet_name": pet_name,
        "reused_existing_pet": pet_id is not None,
        "status_label": APPOINTMENT_STATUS_LABEL.get(appointment.status, appointment.status),
        "risk_level_label": RISK_LEVEL_LABEL.get(appointment.risk_level or "", "待判别"),
    }


# ================================================================
# 店长端工具（经营助理）
# ================================================================
MANAGER_ROLES = (UserRole.MANAGER.value,)


@tool("query_capacity_analysis", "分析区间内各时段的容量饱和度，找出还能加单的时段", roles=STAFF_ROLES)
async def query_capacity_analysis(ctx: ToolContext, start_date: str | None = None,
                                  days: int | None = None) -> dict:
    """分析区间内各时段的容量饱和度，找出还能加单的时段。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    from app.services import schedule_service

    start = parse_date(start_date) or date.today()
    span = max(1, min(int(days or 7), 14))
    data = await schedule_service.week_schedule(ctx.db, ctx.user, start=start, days=span)

    busy: list[dict] = []
    idle: list[dict] = []
    for day in data["days"]:
        for slot in day["slots"]:
            row = {
                "date": day["date"],
                "weekday": day["weekday"],
                "slot_time": slot["slot_time"],
                "used": slot["used"],
                "capacity": slot["capacity"],
                "remain": slot["remain"],
            }
            (busy if slot["used"] > 0 else idle).append(row)

    busy.sort(key=lambda r: (-r["used"], r["date"], r["slot_time"]))
    total_capacity = sum(s["capacity"] for d in data["days"] for s in d["slots"])
    used = sum(s["used"] for d in data["days"] for s in d["slots"])
    return {
        "range": f"{data['start']} ~ {data['end']}",
        "slot_capacity": data["capacity"],
        "total_used": used,
        "total_capacity": total_capacity,
        "utilization_rate": round(used / total_capacity * 100, 1) if total_capacity else 0,
        "busiest": busy[:5],
        "most_available": sorted(idle, key=lambda r: (r["date"], r["slot_time"]))[:8],
        "fully_booked_count": sum(1 for d in data["days"] for s in d["slots"] if s["full"]),
    }


@tool("query_churn_list", "查询流失预警名单：超过门店配置天数没有完成洗护的宠物", roles=MANAGER_ROLES)
async def query_churn_list(ctx: ToolContext, limit: int | None = None) -> dict:
    """查询流失预警名单：超过门店配置天数没有完成洗护的宠物。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    from app.services import stats_service

    start, end = stats_service.default_range()
    data = await stats_service.summary(ctx.db, start, end)
    pets = data.get("churn_pets") or []
    top = pets[: max(1, min(int(limit or 10), 50))]
    return {
        "churn_days": data.get("churn_days"),
        "total": len(pets),
        "items": [
            {"pet_name": p.get("pet_name"), "owner_name": p.get("owner_name"),
             "last_wash_date": p.get("last_wash_date"), "idle_days": p.get("idle_days")}
            for p in top
        ],
    }


@tool("query_staff_performance", "对比区间内店员的工作量（已完成单数）", roles=MANAGER_ROLES)
async def query_staff_performance(ctx: ToolContext, days: int | None = None) -> dict:
    """对比区间内店员的工作量（已完成单数）。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    from app.services import schedule_service, stats_service

    span = max(1, min(int(days or 30), 365))
    start, end = stats_service.default_range()
    data = await stats_service.summary(ctx.db, start, end)
    load = await schedule_service.staff_load(ctx.db, start, end)
    return {
        "range": f"{data['range_start']} ~ {data['range_end']}",
        "requested_days": span,
        "completed_by_staff": data.get("staff_workload") or [],
        "bookings_by_staff": load,
    }


@tool("query_store_settings", "查询门店当前业务配置（容量、SLA 时限、流失天数、会话留存等）",
      roles=STAFF_ROLES)
async def query_store_settings(ctx: ToolContext) -> dict:
    """查询门店当前业务配置（容量、SLA 时限、流失天数、会话留存等）。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    from app.services import setting_service

    rows = await setting_service.get_all_settings(ctx.db)
    return {
        "count": len(rows),
        "settings": [
            {
                "key": r.get("setting_key"),
                "desc": r.get("setting_desc"),
                "value": r.get("setting_value"),
                "default": r.get("default_value"),
                "type": r.get("value_type"),
                "range": [r.get("min_value"), r.get("max_value")],
            }
            for r in rows
        ],
    }


@tool("query_audit_trail", "查询审计日志（仅店长）：谁在什么时候改了什么", roles=MANAGER_ROLES)
async def query_audit_trail(ctx: ToolContext, module: str | None = None, limit: int | None = None) -> dict:
    """查询审计日志（仅店长）：谁在什么时候改了什么。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    from app.services import audit_service

    size = max(1, min(int(limit or 10), 50))
    items, total = await audit_service.list_logs(ctx.db, module=module, page=1, size=size)
    return {
        "module": module or "全部",
        "total": total,
        "items": [
            {
                "module": i["module"],
                "action": i["action"],
                "operator": f"店员#{i['staff_id']}" if i["staff_id"] else (
                    f"用户#{i['user_id']}" if i["user_id"] else "系统"),
                "biz_id": i["biz_id"],
                "ip": i["ip"],
                "status": "成功" if i["status"] == 1 else "失败",
                "detail": i["detail"],
                "created_at": str(i["created_at"] or "")[:19],
            }
            for i in items
        ],
    }


@tool("update_store_setting", "修改门店配置（仅店长，范围校验 + 二次确认）", write=True, roles=MANAGER_ROLES)
async def update_store_setting(ctx: ToolContext, setting_key: str, setting_value: str) -> dict:
    """修改门店配置（仅店长，范围校验 + 二次确认）。

    写工具：LLM 只能「请求执行」，真正落库要经过二次确认闸门。
    """
    from app.services import setting_service

    rows = await setting_service.get_all_settings(ctx.db)
    current = next((r for r in rows if r["setting_key"] == setting_key), None)
    if current is None:
        raise BizError(f"没有找到配置项 {setting_key}，可用 query_store_settings 查看全部配置")

    old_value = current["setting_value"]
    # 类型与范围校验由 setting_service 统一负责，非法值直接抛错
    new_value = setting_service.validate_value(setting_key, str(setting_value))
    await setting_service.update_setting(ctx.db, setting_key, new_value, ctx.user)
    await ctx.db.commit()
    return {
        "setting_key": setting_key,
        "desc": current.get("setting_desc"),
        "old_value": old_value,
        "new_value": new_value,
        "changed": old_value != new_value,
    }


@tool("toggle_user_status", "启用或禁用员工账号（仅店长，需二次确认）", write=True, roles=MANAGER_ROLES)
async def toggle_user_status(ctx: ToolContext, username: str) -> dict:
    """启用或禁用员工账号（仅店长，需二次确认）。

    写工具：LLM 只能「请求执行」，真正落库要经过二次确认闸门。
    """
    from app.services import auth_service

    target = (
        await ctx.db.execute(select(User).where(User.username == username, User.deleted_at.is_(None)))
    ).scalars().first()
    if target is None:
        raise NotFoundError(f"没有找到账号「{username}」")

    before = target.status
    target = await auth_service.toggle_user_status(ctx.db, target, ctx.user, ctx.request)
    return {
        "username": target.username,
        "real_name": target.real_name,
        "role": target.role,
        "from_status": "启用" if before == 1 else "禁用",
        "to_status": "启用" if target.status == 1 else "禁用",
    }


@tool("run_sla_scan", "手动触发店员确认 SLA 巡检（超时升级 / 按配置自动取消，需二次确认）",
      write=True, roles=MANAGER_ROLES)
async def run_sla_scan(ctx: ToolContext) -> dict:
    """手动触发店员确认 SLA 巡检（超时升级 / 按配置自动取消，需二次确认）。

    写工具：LLM 只能「请求执行」，真正落库要经过二次确认闸门。
    """
    result = await appointment_service.sla_scan(ctx.db, ctx.request)
    return result if isinstance(result, dict) else {"result": str(result)}


# ---------------------------------------------------------------- 内建辅助
async def _resolve_appointment_id(ctx: ToolContext, order_no: str) -> int:
    if not order_no:
        raise BizError("缺少预约单号")
    appt = (
        await ctx.db.execute(
            select(Appointment).where(
                Appointment.order_no == order_no, Appointment.deleted_at.is_(None)
            )
        )
    ).scalars().first()
    if appt is None:
        raise NotFoundError(f"没有找到单号 {order_no} 的预约")
    return appt.id


def parse_date(text: str | None) -> date | None:
    """支持 2026-10-20 / 10-20 / 今天 / 明天 / 后天 / 大后天 等中文相对日期。"""
    if not text:
        return None
    raw = str(text).strip()
    today = date.today()
    relative = {
        "今天": 0, "今日": 0, "明天": 1, "明日": 1, "后天": 2, "大后天": 3,
        "today": 0, "tomorrow": 1,
    }
    for key, offset in relative.items():
        if key in raw:
            return today + timedelta(days=offset)
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", raw)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})", raw)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        candidate = date(today.year, month, day)
        return candidate if candidate >= today else date(today.year + 1, month, day)
    return None


# ---------------------------------------------------------------- 归一化（口语 → 枚举）
# 为什么要单独抽出来：LLM 与规则法都会给出「母 / 雌 / 妹妹 / 女孩」这类口语性别，
# 工具层若用「不认识就回落 male」的写法，用户说的「母」会被静默写成「公」（V8.2 实测踩到）。
_GENDER_FEMALE = ("female", "母", "雌", "女", "妹妹", "女孩", "女儿")
_GENDER_MALE = ("male", "公", "雄", "男", "弟弟", "男孩", "儿子")
_SPECIES_ALIAS = {
    "dog": "dog", "犬": "dog", "狗": "dog", "狗狗": "dog", "小狗": "dog", "犬类": "dog",
    "cat": "cat", "猫": "cat", "猫咪": "cat", "小猫": "cat", "猫类": "cat",
    "other": "other", "其它": "other", "其他": "other",
}


def normalize_gender(raw: str | None) -> str | None:
    """把口语性别归一化为 male / female；无法判断返回 None（交给调用方追问，不猜）。"""
    text = str(raw or "").strip().lower()
    if not text:
        return None
    if text in ("male", "female"):
        return text
    # 先判 female：字符串 "female" 本身包含 "male"，顺序反了会被误判
    if any(word in text for word in _GENDER_FEMALE):
        return "female"
    if any(word in text for word in _GENDER_MALE):
        return "male"
    return None


def normalize_species(raw: str | None) -> str | None:
    """把口语物种归一化为 dog / cat / other；无法判断返回 None。"""
    text = str(raw or "").strip().lower()
    if not text:
        return None
    if text in _SPECIES_ALIAS:
        return _SPECIES_ALIAS[text]
    if "猫" in text:
        return "cat"
    if "狗" in text or "犬" in text:
        return "dog"
    if "other" in text or "其他" in text or "其它" in text:
        return "other"
    return None


# 商品名前后的动词 / 语气词：用户说「帮我买成猫全价主粮（三文鱼）」时，
# 这些词不能带进 LIKE 条件，否则一条也搜不到（V8.2 实测）。
_GOODS_LEAD_NOISE = (
    "帮我买", "帮我加购", "麻烦帮我", "我想要", "我想买", "我要买", "我要",
    "给我拿", "给我来", "帮我", "麻烦", "请问", "我想", "请", "买", "加购",
    "添加", "下单买", "下单", "来一份", "来个", "来一袋", "来一包", "来一盒", "要",
)


def clean_product_name(raw: str | None) -> str:
    """清洗商品名：去掉动词前缀、数量后缀与首尾标点，供关键词检索与模糊匹配使用。"""
    name = str(raw or "").strip().strip("，。！？!?、；;：: 　\"'“”")
    for _ in range(4):
        for word in _GOODS_LEAD_NOISE:  # 元组已按「长词优先」排列，避免先剥「买」留下「帮我」
            if name.startswith(word):
                name = name[len(word):].lstrip()
                break
        else:
            break
    name = re.sub(r"[0-9一二两三四五六七八九十]+\s*(件|个|袋|包|盒|瓶|支|罐|份)$", "", name).strip()
    return name


def _goods_key_variants(name: str) -> list[str]:
    """生成由严到宽的检索关键词：原名 → 去括号 → 括号内口味 → 括号外主体。"""
    keys = [name]
    bare = re.sub(r"[（(][^）)]*[）)]", "", name).strip()
    if bare and bare != name:
        keys.append(bare)
    inner = re.findall(r"[（(]([^）)]{1,12})[）)]", name)
    keys.extend([i.strip() for i in inner if i.strip()])
    return [k for k in keys if k]


def tool_manifest(role: str | None = None) -> list[dict]:
    """给 LLM 的工具清单。传入 role 时只返回该角色画像内的工具，收敛上下文长度。"""
    names = ROLE_TOOL_PROFILE.get(role) if role else None
    return [
        {"name": t["name"], "description": t["description"], "write": t["write"]}
        for t in TOOLS.values()
        if names is None or t["name"] in names
    ]


def can_invoke(name: str, user: User) -> bool:
    """双重判定：① 角色白名单允许 ② 该工具在当前角色的画像内。

    这样即使 LLM 幻觉出一个「角色允许但不在画像里」的工具，也会被拒绝执行。
    """
    meta = TOOLS.get(name)
    if meta is None:
        return False
    allowed = meta.get("roles")
    if allowed is not None and user.role not in allowed:
        return False
    return name in ROLE_TOOL_PROFILE.get(user.role, ())


def phone_for(user: User, viewer: User) -> str | None:
    """手机号可见性：仅店长可见原始号码，其余一律脱敏。"""
    raw = decrypt_text(user.phone_encrypted)
    if viewer.role == UserRole.MANAGER.value:
        return raw
    return mask_phone(raw)


# ---------------------------------------------------------------- 宠物之家 / 档案（V8.2）

async def _pick_pet(ctx: ToolContext, pet_name: str | None) -> Pet:
    """按名字取当前账号可见的宠物；宠主只能取自己的，没给名字取第一只。"""
    cond = [Pet.deleted_at.is_(None)]
    if ctx.user.role == UserRole.CUSTOMER.value:
        cond.append(Pet.user_id == ctx.user.id)
    if pet_name:
        cond.append(Pet.name.like(f"%{pet_name}%"))
    pet = (await ctx.db.execute(select(Pet).where(*cond).order_by(Pet.id))).scalars().first()
    if pet is None:
        raise NotFoundError(f"没有找到「{pet_name or '宠物'}」的档案，先说一句「帮我建个档案」吧 🐾")
    return pet


@tool("query_boarding_options", "查询寄养资格（疫苗）、房型与价格", roles=("customer", "staff", "manager"))
async def query_boarding_options(
    ctx: ToolContext,
    pet_name: str | None = None,
    check_in: str | None = None,
    check_out: str | None = None,
) -> dict:
    """查询寄养资格（疫苗）、房型与价格。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    ci = parse_date(check_in) or (date.today() + timedelta(days=1))
    co = parse_date(check_out) or (ci + timedelta(days=3))
    pet = await _pick_pet(ctx, pet_name) if pet_name or ctx.user.role == UserRole.CUSTOMER.value else None

    elig = await boarding_service.eligibility(ctx.db, pet, ci) if pet else None
    rooms = await boarding_service.list_rooms(ctx.db, pet=pet, check_in=ci, check_out=co)
    return {
        "check_in": ci.isoformat(),
        "check_out": co.isoformat(),
        "nights": (co - ci).days,
        "eligibility": elig,
        "rooms": [
            {
                "room_no": r["room_no"],
                "name": r["name"],
                "status": r["status"],
                "status_label": r["status_label"],
                "available": r["available"],
                "note": r.get("unavailable_note"),
                "est_daily": (r.get("est_daily_cents") or 0) / 100,
            }
            for r in rooms
        ],
    }


async def search_products(
    db: AsyncSession, raw_keyword: str | None, pet_id: int | None = None,
    category: str | None = None, limit: int = 8,
) -> tuple[list[dict], str]:
    """按名字检索商品，由严到宽四级回退。

    为什么要自己写而不是直接用 SQL LIKE：用户说的商品名常常多字、少括号、全半角混用
    （「成猫全价主粮三文鱼」 vs 库里「成猫全价主粮（三文鱼）」），
    单靠 `LIKE %关键词%` 一条也搜不到（V8.2 实测：Agent 说「找不到该商品」）。
    商品数量在门店量级（几十条），在内存里做多级匹配比堆 SQL 更稳、也更好测。

    返回 `(命中商品列表, 实际使用的关键词)`，供工具层与确认前预检共用。
    """
    from difflib import SequenceMatcher

    pool = await goods_service.list_products(db, category=category, pet_id=pet_id)
    if not pool:
        return [], ""
    query = clean_product_name(raw_keyword)
    if not query:
        # 没有关键词时按「品类轮询」取样：默认排序是 sort_no，前 N 条会全是洗护类，
        # 用户问「有什么用品推荐」会看到一屏浴液和洗护套装（实测）。轮询后每类先出一件。
        by_cat: dict[str, list[dict]] = {}
        for item in pool:
            by_cat.setdefault(item.get("category") or "other", []).append(item)
        picked: list[dict] = []
        while len(picked) < limit and any(by_cat.values()):
            for cat in list(by_cat):
                if by_cat[cat]:
                    picked.append(by_cat[cat].pop(0))
                    if len(picked) >= limit:
                        break
        return picked, ""

    def norm(text: str) -> str:
        return re.sub(r"[（()）\s·、,，.。\-_/]", "", text or "")

    q = norm(query)
    # ① 完全同名
    for item in pool:
        if item["name"] == query:
            return [item], query
    # ② 双向包含（关键词是商品名的一部分，或反过来）
    hits = [i for i in pool if q and (q in norm(i["name"]) or norm(i["name"]) in q)]
    if hits:
        hits.sort(key=lambda i: -SequenceMatcher(None, q, norm(i["name"])).ratio())
        return hits[:limit], query
    # ③ 去括号主体 / 括号内口味再匹配
    for key in _goods_key_variants(query):
        k = norm(key)
        if not k:
            continue
        hits = [i for i in pool if k in norm(i["name"]) or norm(i["name"]) in k]
        if hits:
            return hits[:limit], key
    # ④ 字符相似度兜底（容忍漏字、错字、括号全半角差异）
    scored = sorted(
        ((SequenceMatcher(None, q, norm(i["name"])).ratio(), i) for i in pool),
        key=lambda pair: -pair[0],
    )
    if scored and scored[0][0] >= 0.45:
        return [i for ratio, i in scored if ratio >= 0.45][:3], query
    return [], query


@tool("query_goods", "查询用品：价格、库存与过敏/禁忌标记", roles=("customer",))
async def query_goods(
    ctx: ToolContext, keyword: str | None = None, pet_name: str | None = None, category: str | None = None
) -> dict:
    """查询用品：价格、库存与过敏/禁忌标记。

    只读工具：仅查询，可直接执行；不改变任何业务状态。
    """
    pet = await _pick_pet(ctx, pet_name) if pet_name else None
    items, used_keyword = await search_products(
        ctx.db, keyword, pet_id=pet.id if pet else None, category=category
    )
    return {
        "total": len(items),
        "keyword": used_keyword or None,
        "pet_name": pet.name if pet else None,
        "items": [
            {
                "name": i["name"],
                "brand": i.get("brand"),
                "category_label": i.get("category_label"),
                "price": i.get("min_price"),
                "total_stock": i.get("total_stock"),
                "unsafe": i.get("unsafe"),
                "conflicts": i.get("conflicts") or [],
                "skus": [{"spec": s["spec_name"], "price": s["price"], "stock": s["stock"]} for s in i.get("skus", [])],
            }
            for i in items[:8]
        ],
    }


@tool("create_pet_profile", "为宠主新建宠物档案（只要名字就能建，其余后补）", write=True, roles=("customer",))
async def create_pet_profile(
    ctx: ToolContext,
    name: str,
    species: str | None = None,
    weight: float | None = None,
    breed: str | None = None,
    gender: str | None = None,
    birthday: str | None = None,
    allergy: str | None = None,
) -> dict:
    """为宠主新建宠物档案（只要名字就能建，其余后补）。

    写工具：LLM 只能「请求执行」，真正落库要经过二次确认闸门。
    """
    pet_name = (name or "").strip()
    if not pet_name:
        raise BizError("宠物名字不能为空，先告诉我它叫什么吧 🐾")

    sp = normalize_species(species) or "dog"
    # 性别：用户说了就必须听懂；听不懂就报错让用户补，**绝不静默回落成 male**
    gd: str | None = None
    if gender is not None and str(gender).strip():
        gd = normalize_gender(str(gender))
        if gd is None:
            raise BizError(f"没看懂性别「{gender}」，说「公」或「母」就行 🐾")
    else:
        gd = "male"  # 未提供时沿用表单默认值（PetEdit 新建亦默认公）

    payload = PetCreate(
        name=pet_name,
        species=sp,
        breed=(breed or None),
        gender=gd,
        birthday=parse_date(birthday) if birthday else None,
        weight=weight,
        allergy=allergy,
    )
    pet = await pet_service.create_pet(ctx.db, ctx.user, payload)
    await ctx.db.commit()
    return {
        "id": pet.id,
        "name": pet.name,
        "species": pet.species,
        "breed": pet.breed,
        "gender": pet.gender,
        "birthday": pet.birthday.isoformat() if pet.birthday else None,
        "weight": float(pet.weight or 0),
        "allergy": pet.allergy,
    }


@tool("create_boarding_order", "为宠主提交寄养申请（疫苗必须有效，需二次确认）", write=True, roles=("customer",))
async def create_boarding_order(
    ctx: ToolContext,
    pet_name: str,
    check_in: str,
    check_out: str,
    room_no: str | None = None,
    room_type: str | None = None,
    feeding_plan: str | None = None,
    dropoff_method: str | None = None,
    pickup_back_method: str | None = None,
    remark: str | None = None,
) -> dict:
    """为宠主提交寄养申请（疫苗必须有效，需二次确认）。

    写工具：LLM 只能「请求执行」，真正落库要经过二次确认闸门。
    `room_type` 支持口语（「标准房」「VIP 套房」），只给房型时自动挑该房型最便宜的可订房。
    """
    pet = await _pick_pet(ctx, pet_name)
    ci, co = parse_date(check_in), parse_date(check_out)
    if ci is None or co is None:
        raise BizError("日期没听清，请说成 2027-03-10 这样，或者「明天」")
    if co <= ci:
        raise BizError("离店日期要晚于入住日期哦")

    rooms = await boarding_service.list_rooms(ctx.db, pet=pet, check_in=ci, check_out=co)
    room, room_error = boarding_service.resolve_room(rooms, room_no=room_no, room_type=room_type)
    if room is None:
        raise BizError(room_error)

    payload = BoardingOrderCreate(
        pet_id=pet.id,
        room_id=room["id"],
        check_in_date=ci,
        check_out_date=co,
        feeding_plan=feeding_plan or "self",
        dropoff_method=dropoff_method or "self",
        pickup_back_method=pickup_back_method or "self",
        remark=remark,
        terms_confirmed=True,
        idempotent_key=ctx.idempotent_key or f"agent-board-{gen_random_str(16)}",
    )
    order = await boarding_service.create_order(ctx.db, ctx.user, payload, ctx.request)
    return {
        "order_no": order.order_no,
        "pet_name": pet.name,
        "room_no": room["room_no"],
        "room_name": room["name"],
        "check_in_date": order.check_in_date.isoformat(),
        "check_out_date": order.check_out_date.isoformat(),
        "nights": order.nights,
        "total_amount": order.total_cents / 100,
        "status": order.status,
        "status_label": BOARDING_STATUS_LABEL.get(order.status, order.status),
        "vaccine_note": order.vaccine_note,
        "feeding_label": FEEDING_PLAN_LABEL.get(order.feeding_plan, order.feeding_plan),
        "dropoff_label": DROPOFF_METHOD_LABEL.get(order.dropoff_method, order.dropoff_method),
        "pickup_back_label": PICKUP_BACK_METHOD_LABEL.get(order.pickup_back_method, order.pickup_back_method),
    }


@tool("add_goods_to_cart", "把用品加入购物车（按商品名匹配，过敏会提示）", write=True, roles=("customer",))
async def add_goods_to_cart(
    ctx: ToolContext,
    product_name: str,
    quantity: int | None = None,
    spec_name: str | None = None,
    pet_name: str | None = None,
) -> dict:
    """把用品加入购物车（按商品名匹配，过敏会提示）。

    写工具：LLM 只能「请求执行」，真正落库要经过二次确认闸门。
    """
    pet = await _pick_pet(ctx, pet_name) if pet_name else None
    items, used_keyword = await search_products(
        ctx.db, product_name, pet_id=pet.id if pet else None, limit=5
    )
    if not items:
        listing = await goods_service.list_products(ctx.db)
        names = "、".join(i["name"] for i in listing[:6]) or "（门店暂未上架用品）"
        raise NotFoundError(
            f"没找到和「{product_name}」相关的用品。\n门店在售：{names}\n"
            "可以说「有哪些用品」看全部，或直接说上面某个名字 🐾"
        )

    # 优先精确同名，其次取相似度最高的第一条
    product = next((i for i in items if i["name"] == clean_product_name(product_name)), items[0])
    skus = [s for s in product.get("skus", []) if s.get("stock", 0) > 0]
    if not skus:
        raise BizError(f"「{product['name']}」当前没有库存，换一个试试？")
    if spec_name:
        sku = next((s for s in skus if spec_name in str(s["spec_name"])), skus[0])
    else:
        sku = skus[0]

    qty = max(int(quantity or 1), 1)
    added = await goods_service.add_to_cart(
        ctx.db, ctx.user,
        CartAddIn(sku_id=sku["id"], quantity=qty, pet_id=pet.id if pet else None),
    )
    await ctx.db.commit()
    cart = await goods_service.list_cart(ctx.db, ctx.user)
    return {
        "product_name": product["name"],
        "requested_name": product_name,
        "matched_keyword": used_keyword or None,
        "spec_name": sku["spec_name"],
        "quantity": qty,
        "price": sku["price"],
        "warnings": added.get("warnings") or [],
        "cart_count": cart["count"],
        "cart_total": cart["total"],
    }


@tool("submit_goods_order", "把购物车提交为用品订单（自提或配送，需二次确认）", write=True, roles=("customer",))
async def submit_goods_order(
    ctx: ToolContext,
    pickup_method: str | None = None,
    address: str | None = None,
    remark: str | None = None,
) -> dict:
    """把购物车提交为用品订单（自提或配送，需二次确认）。

    写工具：LLM 只能「请求执行」，真正落库要经过二次确认闸门。
    """
    cart = await goods_service.list_cart(ctx.db, ctx.user)
    if not cart["count"]:
        raise BizError("购物车还是空的，先说说要买什么吧 🛒")

    method = pickup_method or "self"
    if method not in ("self", "delivery"):
        method = "self"
    if method == "delivery" and not address:
        raise BizError("配送需要地址，请告诉我送到哪里")

    order = await goods_service.create_order(
        ctx.db, ctx.user,
        GoodsOrderCreateIn(
            pickup_method=method,
            address=address,
            remark=remark,
            idempotent_key=ctx.idempotent_key or f"agent-goods-{gen_random_str(16)}",
        ),
        ctx.request,
    )
    return {
        "order_no": order.order_no,
        "item_count": order.item_count,
        "total_amount": order.total_cents / 100,
        "delivery_fee": order.delivery_fee_cents / 100,
        "pickup_method": order.pickup_method,
        "pickup_code": order.pickup_code,
        "status": order.status,
    }


__all__ = [
    "TOOLS", "WRITE_TOOLS", "ToolContext", "tool", "tool_manifest", "can_invoke",
    "phone_for", "parse_date", "ROLE_TOOL_PROFILE", "_pick_pet",
]
