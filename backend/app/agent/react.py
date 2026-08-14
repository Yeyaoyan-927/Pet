"""多 Agent 协作 + ReAct 运行器 + Graph Workflow 闸门。

架构约定（硬约束）：
- **多 Agent 分工，一套执行内核**：路由调度 Agent 判定意图并分派，领域子 Agent
  （健康问诊 / 饲养营养 / 行为训练 / 用品导购 / 档案复诊 / 门店业务 / 经营分析）各司其职，
  合规风控 Agent 横切兜底。八个以上 Agent 共用本运行器与同一张工具注册表，
  差异在领域定义与工具子集（见 `app/agent/agents.py`）。
- **业务闭环用 Graph Workflow**：意图 → 槽位收集 → 校验 → 确认闸门 → 执行 → 回执，显式可枚举。
- **不使用 CrewAI / AutoGen 等多 Agent 框架**：跨 Agent 协同由路由层按显式规则调度，
  子 Agent 之间不直接对话。
- **写操作绝不交由 LLM 直接执行**：LLM 只决定「调用哪个工具」，实际写在业务服务层完成。
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime
from typing import Any, AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.agents import resolve_agent
from app.agent.compliance import apply_verdict, review_answer
from app.agent.llm.client import bailian_client
from app.agent.llm.prompts import INTENT_SYSTEM_PROMPT, ROLE_OPERATION_PROMPT
from app.agent.tools.registry import (
    STATUS_ALIAS,
    TOOLS,
    WRITE_TOOLS,
    ToolContext,
    can_invoke,
    clean_product_name,
    normalize_gender,
    normalize_species,
    parse_date,
    search_products,
    tool_manifest,
)
from app.agent.tools.profiles import (
    ROLE_CAPABILITY_SUMMARY,
    ROLE_EXAMPLES,
    ROLE_PROMPT_HINT,
    ROLE_TOOL_PROFILE,
)
from app.config import settings
from app.constants import APPOINTMENT_STATUS_LABEL, PET_GENDER_LABEL, PET_SPECIES_LABEL, SERVICE_TYPE_LABEL, UserRole
from app.models import Appointment, BoardingRoom, ChatMessage, ChatSession, Pet, User
from app.services import boarding_service, camera_service, goods_service
from app.utils.datetime_util import gen_random_str
from app.utils.exceptions import BizError
from app.utils.logger import logger

# ---------------- Graph Workflow 节点定义 ----------------
# 读 / 写意图**直接从工具注册表派生**：
# 只要某个工具用 @tool(..., write=True) 登记，它就会自动进入确认闸门，
# 不会因为忘记维护一份硬编码列表而绕过二次确认（这是写入安全的关键防线）。
WRITE_INTENTS: set[str] = set(WRITE_TOOLS)
READ_INTENTS: set[str] = set(TOOLS) - WRITE_INTENTS

# 槽位白名单**从工具签名派生**：LLM 能填哪些槽位，取决于工具真正接受哪些参数。
# 不要再手写一份清单 —— V8.2 踩过：slots 初始化漏了 gender / birthday，
# 合并时「只补已存在的键」，导致用户说「母」被丢掉、档案落库成默认的「公」。
ALL_SLOT_KEYS: set[str] = {p for meta in TOOLS.values() for p in meta["params"]}

# ---------------- 知识问答识别（洗护 / 营养 / 行为 / 用品） ----------------
# 命中即走 `search_knowledge`。这三类问题以前全被当成「闲聊」或「查档案」：
#   「球球喂养有什么推荐的」→ 查了档案只回一张卡片
#   「球球需要怎么训练」→ 判成闲聊，回「请咨询专业训犬师」
# 知识问答与「买 / 预约」是互斥的：「买袋猫粮」是下单，「猫粮怎么选」才是问知识。
KNOWLEDGE_HINTS: tuple[str, ...] = (
    # 洗护
    "怎么洗", "如何洗", "该怎么洗", "洗护规范", "操作规范", "服务规范", "安全规范",
    "注意事项", "要注意什么", "注意什么", "能洗吗", "可以洗吗", "能不能洗",
    "能洗澡吗", "可以洗澡吗", "多久能洗", "多久能洗澡", "多久可以洗",
    "怎么处理", "怎么安抚", "如何安抚", "安抚", "消毒", "隔离", "交叉感染",
    "用什么洗", "用什么产品", "什么浴液", "应激怎么办", "应激反应",
    "等级", "分级", "步骤", "手法", "流程", "要点", "标准", "试洗",
    "致敏", "成分", "频率", "多久一次", "几次",
    "老年", "幼犬", "幼猫", "哪些情况", "什么情况",
    # 营养
    "喂养", "怎么喂", "如何喂", "喂多少", "喂几次", "吃什么", "吃多少", "能吃吗",
    "能吃", "不能吃", "忌口", "换粮", "什么粮", "粮怎么", "怎么选粮", "选什么粮",
    "罐头", "营养", "益生菌", "鱼油", "补钙", "软便", "挑食", "太瘦", "长胖",
    # 行为
    "怎么训练", "如何训练", "训练方法", "怎么教", "拆家", "乱叫", "一直叫", "叫不停",
    "护食", "乱尿", "乱拉", "随地", "应激", "焦虑", "分离焦虑", "扑人", "怕人",
    "社会化", "定点", "咬人", "打架", "追人",
    # 疾病 / 急症（用户问「狗吃了巧克力怎么办」时不能当闲聊）
    "中毒", "巧克力", "葡萄", "洋葱", "老鼠药", "抽搐", "呕吐", "拉稀", "腹泻",
    "便血", "发烧", "咳嗽", "尿不出", "尿血", "误食", "吃了", "舔了",
    # 健康状态 / 用药（「球球健康状态怎么样，需不需要吃药」不能去查档案或看实景）
    "健康", "吃药", "用药", "喂药", "服药", "要不要吃", "需不需要吃", "该吃", "停药",
    # 用品选购
    "怎么选", "选哪个", "哪种好", "哪个好", "适合什么", "猫砂", "砂盆", "猫抓板",
    "牵引", "航空箱", "喂食器", "饮水机", "尿垫", "窝垫",
)

# 购买 / 预约类动作词：出现即不算知识问答（否则「买袋猫粮」会被当成问怎么选粮）
PURCHASE_HINTS: tuple[str, ...] = (
    "买", "加购", "下单", "下单", "多少钱", "价格", "有货", "库存", "来一", "要一",
    "送到", "备注", "订单", "预约", "约个", "帮我约", "订一个", "取消", "改期", "结算",
)

# 用品实体词：和「推荐 / 有什么」一起出现时，要查商品库而不是讲选购标准。
# 「有什么猫砂推荐」= 请列出门店在售商品；「猫砂怎么选」= 求选购标准（走知识）。
GOODS_HINTS: tuple[str, ...] = (
    "猫砂", "砂盆", "猫抓板", "牵引", "航空箱", "喂食器", "饮水机", "尿垫", "窝垫",
    "玩具", "用品", "主粮", "零食", "罐头",
)

# 「查这只宠物的记录」类词：出现即不算知识问答（否则「看看豆豆的应激记录」会被「应激」抢成知识）
RECORD_HINTS: tuple[str, ...] = (
    "记录", "档案", "历史", "上次", "上一次", "之前那", "病历", "明细",
)


# 常见品种词典：用户说「金毛」「布偶」时不会带「品种」二字，靠这份词典兜住
PET_BREED_WORDS = (
    "金毛", "拉布拉多", "柯基", "泰迪", "比熊", "博美", "柴犬", "哈士奇", "萨摩耶",
    "边牧", "德牧", "吉娃娃", "雪纳瑞", "法斗", "巴哥", "中华田园犬", "贵宾", "斗牛",
    "布偶", "英短", "美短", "暹罗", "加菲", "缅因", "蓝猫", "橘猫", "狸花", "折耳",
    "银渐层", "金渐层", "波斯猫", "无毛猫",
)


def _birthday_from_age_text(text: str) -> date | None:
    """把「3 岁」「8 个月」换算成生日（只取年和月，日统一按 1 号保守估算）。

    建档案时用户更习惯说年龄，工具只接受 birthday，所以入口处先换算好。
    """
    year_match = re.search(r"(\d{1,2})\s*(?:周岁|岁)", text)
    month_match = re.search(r"(\d{1,2})\s*个?月", text)
    years = int(year_match.group(1)) if year_match else 0
    months = int(month_match.group(1)) if (month_match and not year_match) else 0
    if not years and not months:
        return None
    today = date.today()
    total_months = years * 12 + months
    if total_months <= 0 or total_months > 30 * 12:
        return None
    month_index = today.year * 12 + (today.month - 1) - total_months
    return date(month_index // 12, month_index % 12 + 1, 1)


REQUIRED_SLOTS: dict[str, tuple[str, ...]] = {
    # 宠主
    "query_slots": ("appoint_date",),
    "query_my_appointments": (),
    "query_pet_profile": (),
    "query_risk_report": (),
    "create_appointment": ("pet_name", "appoint_date", "slot_time"),
    "cancel_appointment": ("order_no",),
    "create_pet_profile": ("name",),
    "query_boarding_options": (),
    "create_boarding_order": ("pet_name", "check_in", "check_out"),
    "query_goods": (),
    "add_goods_to_cart": ("product_name",),
    "submit_goods_order": (),
    "search_knowledge": (),
    # 店员
    "query_day_schedule": (),
    "query_todo": (),
    "query_customer_pets": (),
    "query_wash_history": ("pet_name",),
    "query_report_summary": (),
    "advance_appointment": ("order_no", "target_status"),
    "confirm_risk": ("order_no",),
    "create_appointment_for_customer": ("phone", "pet_name", "appoint_date", "slot_time"),
    "reschedule_appointment": ("order_no", "appoint_date", "slot_time"),
    # 店长
    "query_capacity_analysis": (),
    "query_churn_list": (),
    "query_staff_performance": (),
    "query_store_settings": (),
    "query_audit_trail": (),
    "update_store_setting": ("setting_key", "setting_value"),
    "toggle_user_status": ("username",),
    "run_sla_scan": (),
}

CONFIRM_WORDS = ("确认", "确定", "好的", "可以", "是的", "没问题", "嗯", "同意", "yes", "ok", "提交")
CANCEL_WORDS = ("不用", "不用了", "取消", "算了", "否", "不要", "no", "放弃")
# 确认 / 取消短语必须「整句就是这个意思」才生效，避免把
# 「明天还有哪些时段可以预约？」里的「可以」误判成确认。
CONFIRM_RE = re.compile(r"^(确认|确定|好的|可以|是的|没问题|嗯|同意|提交|yes|ok|y)[呀吧哦啦啊～~!！。.、,\s]*$", re.I)
CANCEL_RE = re.compile(r"^(取消|不用|不用了|算了|否|不要|放弃|no|n)[呀吧哦啦啊～~!！。.、,\s]*$", re.I)


def is_confirm(text: str) -> bool:
    """判断用户是否在「确认」上一步待执行的写操作（口语：确认 / 好的 / 执行吧）。


    """
    raw = (text or "").strip()
    if not raw or len(raw) > 8:
        return False
    return bool(CONFIRM_RE.match(raw)) or any(w in raw for w in CONFIRM_WORDS)


def is_cancel(text: str) -> bool:
    """判断用户是否在「取消」上一步待执行的写操作。


    """
    raw = (text or "").strip()
    if not raw or len(raw) > 8:
        return False
    return bool(CANCEL_RE.match(raw)) or any(w in raw for w in CANCEL_WORDS)

MAX_HISTORY = 8

SMALLTALK_FALLBACK = (
    "你好呀，我是店铺的洗护小助手 🐾\n"
    "你可以问我：「明天还有哪些时段可以预约？」「帮我看看豆豆的档案」「我最近的预约到哪一步了？」\n"
    "也可以直接说「帮我给豆豆预约明天下午三点洗澡」，我会先跟你确认再提交。"
)


class AgentRunner:
    """多 Agent 协作的执行内核（每个请求一个 runner，共享同一张工具注册表）。

    路由调度 Agent 在这里判定意图并解析出负责的领域 Agent，事件里带上 `agent`；
    执行路径不变：工具闸门仍由 `can_invoke()`（角色白名单 + 端内画像）唯一裁定。
    """

    def __init__(self, db: AsyncSession, user: User, request=None):
        self.db = db
        self.user = user
        self.request = request

    # ------------------------------------------------------------ 对外入口
    async def stream(self, session: ChatSession, text: str) -> AsyncGenerator[dict, None]:
        """对话主循环（SSE 逐事件产出）。


            流程：待确认动作优先处理 → 意图识别（LLM 失败自动降级规则）→ 只读工具直接执行 /
            写工具走确认闸门 → 逐字输出回答并落库。任何异常都收敛成一条可读错误，不让流断在半途。
        """
        text = (text or "").strip()
        if not text:
            yield {"type": "error", "message": "消息内容不能为空"}
            return

        await self._save(session, role="user", content=text)
        yield {"type": "meta", "session_id": session.id, "llm": settings.llm_available}

        # ---- Graph 节点 0：待确认动作优先处理（写操作闸门）----
        if session.pending_action:
            handled = False
            async for event in self._handle_pending(session, text):
                handled = True
                yield event
            if handled:
                yield {"type": "done"}
                return

        # ---- Graph 节点 1：意图识别 + 槽位抽取 ----
        async for event in self._thought("正在理解你的需求…"):
            yield event
        parsed = await self._interpret(session, text)
        intent = parsed["intent"]
        slots = self._align_slots(intent, parsed["slots"], text)
        # 路由分派：意图 → 负责的领域 Agent（只影响展示与领域说明，不改变执行路径）
        agent = resolve_agent(intent, text)
        yield {
            "type": "intent",
            "intent": intent,
            "slots": slots,
            "source": parsed["source"],
            "agent": agent.view(),
        }



        # ---- Graph 节点 1.5：实景（先列在住宠物 → 选中后跳到实景页并自动开播）----
        if intent == "open_camera":
            async for event in self._open_camera(session, text, slots):
                yield event
            yield {"type": "done"}
            return

        # ---- Graph 节点 2：闲聊分支 ----
        if intent == "smalltalk":
            reply = parsed.get("reply") or SMALLTALK_FALLBACK
            async for event in self._answer_and_save(session, reply, intent=intent):
                yield event
            yield {"type": "done"}
            return

        # ---- Graph 节点 3：权限校验 ----
        if not can_invoke(intent, self.user) and intent in TOOLS:
            async for event in self._answer_and_save(
                session, "这个操作需要店员或店长权限哦，请用对应账号登录后再试 🐾", intent=intent
            ):
                yield event
            yield {"type": "done"}
            return

        # ---- Graph 节点 4：槽位收集 ----
        missing = [k for k in REQUIRED_SLOTS.get(intent, ()) if not slots.get(k)]
        if missing:
            question = self._ask_for_missing(intent, missing, slots)
            async for event in self._answer_and_save(session, question, intent=intent):
                yield event
            yield {"type": "done"}
            return

        # ---- Graph 节点 5/6：读操作直接执行；写操作先只读预检，再进入确认闸门 ----
        if intent in WRITE_INTENTS:
            precheck_error = await self._precheck(intent, slots)
            if precheck_error:
                async for event in self._answer_and_save(session, precheck_error, intent=intent):
                    yield event
                yield {"type": "done"}
                return

            session.pending_action = json.dumps(
                {"tool": intent, "args": slots, "idempotent_key": f"agent-{gen_random_str(16)}"},
                ensure_ascii=False,
            )
            await self.db.flush()
            prompt = self._confirm_prompt(intent, slots)
            await self._save(session, role="assistant", content=prompt, intent=intent, step=1)
            yield {"type": "confirm", "tool": intent, "args": slots, "prompt": prompt}
            yield {"type": "done"}
            return

        async for event in self._execute_and_reply(session, intent, slots):
            yield event
        yield {"type": "done"}

    @staticmethod
    def _align_slots(intent: str, slots: dict, text: str) -> dict:
        """槽位对齐：把 LLM 常用的同义字段归并到工具真正接受的参数名上。

        - 建档案：LLM 常把名字放进 `pet_name`；
        - 寄养：常把入住日放进 `appoint_date`；
        - 知识检索：**经常干脆不填 query**，而用户原话本身就是检索语句 ——
          空 query 会让工具报「想查哪方面的规范」，用户看到的是「识别对了却答不出来」。
        """
        if intent == "create_pet_profile" and not slots.get("name") and slots.get("pet_name"):
            slots["name"] = slots["pet_name"]
        if intent == "create_boarding_order":
            slots.setdefault("check_in", slots.get("appoint_date"))
            if not slots.get("check_out"):
                slots["check_out"] = slots.get("check_out") or slots.get("leave_date")
        if intent == "search_knowledge" and not (slots.get("query") or "").strip():
            slots["query"] = text
        return slots

    async def _precheck(self, intent: str, slots: dict) -> str | None:
        """写操作确认前的**只读预检**：先确认对象存在且可操作，避免让用户做无意义的二次确认。

        注意：这里只做查询与校验，不产生任何写操作。
        """
        # 新增的四类写操作：确认前三件事必须先查清（对象在不在、能不能做、要花多少）
        if intent == "create_pet_profile":
            name = (slots.get("name") or "").strip()
            if not name:
                return "宠物名字还没告诉我呢，说一句「它叫豆豆」就行 🐾"
            existed = (
                await self.db.execute(
                    select(Pet.id).where(Pet.user_id == self.user.id, Pet.name == name,
                                         Pet.deleted_at.is_(None))
                )
            ).scalars().first()
            return f"你名下已经有一只叫「{name}」的毛孩子了，换个名字？" if existed else None

        if intent == "create_boarding_order":
            pet = await self._find_pet(slots.get("pet_name"))
            if pet is None:
                return f"没有找到「{slots.get('pet_name') or '宠物'}」的档案，先建个档案再寄养吧 🐾"
            ci, co = parse_date(slots.get("check_in") or ""), parse_date(slots.get("check_out") or "")
            if ci is None or co is None:
                return "日期没听清，请说成「2027-03-10 到 2027-03-13」这样"
            if co <= ci:
                return "离店日期要晚于入住日期哦"
            elig = await boarding_service.eligibility(self.db, pet, ci)
            if not elig["ok"]:
                # 疫苗不通过时直接把原因与补救办法说清楚，别让用户去猜
                return f"{elig['message']} 🐾"
            rooms = await boarding_service.list_rooms(self.db, pet=pet, check_in=ci, check_out=co)
            # 房型（「标准房 / VIP 套房」）与房号都支持：用户说房型时自动挑该房型最便宜的可订房
            room, room_error = boarding_service.resolve_room(
                rooms, room_no=slots.get("room_no"), room_type=slots.get("room_type")
            )
            if room is None:
                return room_error
            slots["room_no"] = room["room_no"]
            slots["_room_name"] = room["name"]

            detail = (
                await self.db.execute(
                    select(BoardingRoom).where(BoardingRoom.id == room["id"])
                )
            ).scalars().first()
            if detail is not None:
                est = await boarding_service.quote(
                    self.db, pet=pet, room=detail, check_in=ci, check_out=co,
                    feeding_plan=slots.get("feeding_plan") or "self",
                    dropoff_method=slots.get("dropoff_method") or "self",
                    pickup_back_method=slots.get("pickup_back_method") or "self",
                )
                slots["_est_total"] = round(est["total_cents"] / 100, 2)
                slots["_room_name"] = room["name"]
                slots["_nights"] = est["nights"]
            return None

        if intent == "add_goods_to_cart":
            keyword = (slots.get("product_name") or "").strip()
            if not keyword:
                return "想买哪件用品？说个名字就行"
            # 与工具层用同一套多级匹配，避免「预检说找不到、其实能买到」
            items, used = await search_products(self.db, keyword, limit=5)
            if not items:
                listing = await goods_service.list_products(self.db)
                names = "、".join(i["name"] for i in listing[:6]) or "（门店暂未上架用品）"
                return (f"没找到「{keyword}」，门店在售：{names}\n"
                        "可以说「有哪些用品」看全部，或者直接说上面某个名字 🐾")
            slots["product_name"] = items[0]["name"]
            slots["_matched_keyword"] = used
            return None

        if intent == "submit_goods_order":
            cart = await goods_service.list_cart(self.db, self.user)
            if not cart["count"]:
                return "购物车还是空的，先说说要买什么吧 🛒"
            slots["_cart_count"] = cart["count"]
            slots["_cart_total"] = cart["total"]
            slots["_cart_names"] = "、".join(f"{i['product_name']}×{i['quantity']}" for i in cart["items"][:3])
            return None

        if intent not in ("cancel_appointment", "reschedule_appointment",
                          "advance_appointment", "confirm_risk"):
            return None
        order_no = slots.get("order_no")
        if not order_no:
            return None
        appt = (
            await self.db.execute(
                select(Appointment).where(Appointment.order_no == order_no,
                                          Appointment.deleted_at.is_(None))
            )
        ).scalars().first()
        if appt is None:
            return f"没有找到单号为 {order_no} 的预约，麻烦再核对一下单号 🐾"
        if self.user.role == UserRole.CUSTOMER.value and appt.user_id != self.user.id:
            return "这笔预约不属于当前账号，无法操作哦。"
        if self.user.role == UserRole.STAFF.value and appt.staff_id not in (None, self.user.id):
            return "这笔预约归属其他店员，我这边没有权限操作。"
        terminal = ("completed", "cancelled", "no_show", "arrived_give_up", "wash_interrupt")
        if intent in ("cancel_appointment", "reschedule_appointment") and appt.status not in ("pending", "confirmed"):
            return (
                f"这笔预约当前状态是「{APPOINTMENT_STATUS_LABEL.get(appt.status, appt.status)}」，"
                "不支持取消或改期。"
            )
        if intent in ("advance_appointment", "confirm_risk") and appt.status in terminal:
            return (
                f"这笔预约当前状态是「{APPOINTMENT_STATUS_LABEL.get(appt.status, appt.status)}」，"
                "已经是终态，无法再推进或复核。"
            )
        return None

    # ------------------------------------------------------------ 写操作闸门
    async def _handle_pending(self, session: ChatSession, text: str) -> AsyncGenerator[dict, None]:
        """处理「上一条写操作还在等确认」的情况：用户确认则执行，取消则清空，其余按新话题处理。


        """
        try:
            action = json.loads(session.pending_action or "{}")
        except (ValueError, TypeError):
            session.pending_action = None
            await self.db.flush()
            return

        tool_name = action.get("tool")
        args = action.get("args") or {}

        if is_cancel(text):
            session.pending_action = None
            await self.db.flush()
            text_out = "好的，这次操作已取消，需要的时候再叫我 🐾"
            async for event in self._answer_and_save(session, text_out):
                yield event
            return

        if not is_confirm(text):
            return  # 不是在确认，交给正常意图识别流程

        session.pending_action = None
        await self.db.flush()
        yield {"type": "thought", "content": f"你已确认，正在执行 {tool_name} …"}
        async for event in self._execute_and_reply(
            session, tool_name, args, key=action.get("idempotent_key")
        ):
            yield event

    # ------------------------------------------------------------ 工具执行
    async def _execute_and_reply(
        self, session: ChatSession, tool_name: str, args: dict, key: str | None = None
    ) -> AsyncGenerator[dict, None]:
        """执行已确认的写工具，并把结果包装成自然语言回答。


            工具异常一律回滚会话对象（_recover_session），否则后续访问过期属性会抛 MissingGreenlet。
        """
        meta = TOOLS.get(tool_name)
        # 注意：params 为 None 表示「未知，不过滤」；空元组表示「该工具不接受任何参数」，
        # 两者语义不同，不能用 not accepted 合并判断（否则无参工具会放行全部入参）。
        accepted = meta.get("params")
        raw_args = args if isinstance(args, dict) else {}
        clean_args = {
            k: v for k, v in raw_args.items()
            if v not in (None, "", []) and (accepted is None or k in accepted)
        }
        dropped = [k for k in raw_args if k not in clean_args and raw_args[k] not in (None, "", [])]
        if dropped:
            logger.info("agent_tool_args_filtered",
                        extra={"extra_fields": {"tool": tool_name, "dropped": dropped}})
        yield {"type": "action", "tool": tool_name, "args": clean_args}

        ctx = ToolContext(self.db, self.user, self.request, key)
        try:
            result = await meta["handler"](ctx, **clean_args)
        except BizError as exc:
            await self.db.rollback()
            await self._recover_session(session)
            yield {"type": "observation", "tool": tool_name, "ok": False, "error": exc.message}
            async for event in self._answer_and_save(
                session, f"抱歉，这次没能完成：{exc.message}", tool=tool_name
            ):
                yield event
            return
        except Exception as exc:  # pragma: no cover - 兜底，保证 SSE 不中断
            await self.db.rollback()
            await self._recover_session(session)
            logger.error("agent tool failed: %s", exc)
            yield {"type": "observation", "tool": tool_name, "ok": False, "error": str(exc)[:160]}
            async for event in self._answer_and_save(
                session, "抱歉，系统开小差了，请稍后重试或改用表单入口 🐾", tool=tool_name
            ):
                yield event
            return

        yield {"type": "observation", "tool": tool_name, "ok": True, "result": result}

        # 知识问答：片段交给模型组织回答，片段本身下发前端折叠展示（真正的 RAG 生成阶段）
        if tool_name == "search_knowledge":
            async for event in self._answer_knowledge(session, clean_args, result):
                yield event
            return

        answer = self._format_answer(tool_name, result)
        async for event in self._answer_and_save(session, answer, tool=tool_name, result=result):
            yield event

    # ------------------------------------------------------------ 知识问答（RAG 生成）
    KNOWLEDGE_SYSTEM_PROMPT = (
        "你是宠物洗护门店的规范问答助手。**只能依据给定的门店规范片段回答**，"
        "不要编造流程、剂量或时间。\n"
        "表达要求：\n"
        "1. 先给结论，再给可执行步骤；口语化、简短，不超过 6 行（180 字以内）；\n"
        "2. 需要指明出处时写「见《文档名 · 小节》」，不要整段复述原文；\n"
        "3. 片段没有覆盖的部分，明确说「规范里没有写」，并建议问得更具体或咨询店长；\n"
        "4. 不做医疗诊断，涉及病症时提示就医。"
    )

    def _knowledge_empty_text(self) -> str:
        return ("知识库里暂时没有直接对应的规范。可以问得具体一点，比如"
                "「过敏体质的猫怎么洗」「疫苗后多久能洗澡」「应激严重怎么安抚」🐾")

    def _knowledge_fallback_text(self, result: dict) -> str:
        """模板化摘要：模型不可用时的兜底，也是片段的结构化清单。"""
        items = result.get("items") or []
        if not items:
            return self._knowledge_empty_text()
        lines = []
        if result.get("pet_name"):
            lines.append(f"按「{result['pet_name']}」的情况找到 {len(items)} 条规范：")
        else:
            lines.append(f"找到 {len(items)} 条相关规范：")
        for idx, item in enumerate(items, 1):
            body = re.sub(r"^#+\s*", "", (item.get("content") or "")).replace("\n", " ")
            if len(body) > 120:
                body = body[:120] + "…"
            basis = "、".join((item.get("matched") or [])[:2])
            # 同一篇文档会被问不同小节：标题带上命中的小节名，
            # 否则用户看到的永远是「1. 应激反应分级与安抚流程」，误以为每次答案都一样
            section = (item.get("section") or "").strip()
            heading = f"{item['title']} · {section}" if section else item["title"]
            lines.append(
                f"{idx}. {heading}\n"
                f"   {body}\n"
                f"   依据：{basis}｜来源：{item.get('source') or '门店规范'}"
            )
        lines.append("以上为门店内部洗护规范，不构成医疗诊断；有症状请先就医。")
        return "\n".join(lines)

    @staticmethod
    def _refs_item(item: dict) -> dict:
        """下发给前端折叠面板的片段结构（只带展示需要的字段）。"""
        body = re.sub(r"^#+\s*", "", (item.get("content") or "")).strip()
        return {
            "title": item.get("title") or "门店规范",
            "section": (item.get("section") or "").strip(),
            "source": item.get("source") or "门店规范",
            "content": body[:260],
            "matched": "、".join((item.get("matched") or [])[:2]),
        }

    async def _compose_knowledge_answer(self, query: str | None, items: list[dict]) -> str:
        """把检索到的片段交给模型组织成回答（RAG 的生成阶段）。

        模型不可用 / 调用失败时退回模板摘要 —— 回答变「朴素」，但不会没有回答。
        """
        fallback = self._knowledge_fallback_text({"items": items})
        if not settings.llm_available:
            return fallback
        blocks: list[str] = []
        for idx, item in enumerate(items, 1):
            section = (item.get("section") or "").strip()
            head = item.get("title") or "门店规范"
            if section:
                head = f"{head} · {section}"
            body = re.sub(r"^#+\s*", "", (item.get("content") or "")).strip()
            blocks.append(f"{idx}. 《{head}》\n{body[:600]}")
        messages = [
            {"role": "system", "content": self.KNOWLEDGE_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"【用户问题】{query or ''}\n\n"
                f"【门店规范片段】\n" + "\n\n".join(blocks)
            )},
        ]
        try:
            res = await bailian_client.chat_with_fallback(messages, temperature=0.2)
        except Exception as exc:  # pragma: no cover - 兜底分支
            logger.warning("knowledge_answer_llm_failed: %s", exc)
            return fallback
        if res is None or not res.ok:
            return fallback
        text = (res.content or "").strip()
        if not text:
            return fallback
        # 气泡是纯文本渲染，去掉模型偶尔冒出来的 markdown 装饰
        return re.sub(r"^[#>*\-\s]+", "", text, flags=re.MULTILINE).replace("**", "").strip()

    async def _answer_knowledge(
        self, session: ChatSession, args: dict, result: dict
    ) -> AsyncGenerator[dict, None]:
        """知识问答的答复流程：先下发片段（前端折叠面板），再流式输出模型回答。"""
        items = result.get("items") or []
        if not items:
            async for event in self._answer_and_save(
                session, self._knowledge_empty_text(), tool="search_knowledge", result=result
            ):
                yield event
            return
        # 片段单独发一条事件：气泡正文只放模型回答，依据放进「检索到的片段」（可折叠）
        yield {"type": "refs", "items": [self._refs_item(i) for i in items]}
        answer = await self._compose_knowledge_answer(args.get("query"), items)
        async for event in self._answer_and_save(
            session, answer, tool="search_knowledge", result=result
        ):
            yield event

    async def _open_camera(
        self, session: ChatSession, text: str, slots: dict
    ) -> AsyncGenerator[dict, None]:
        """看实景：先在聊天里列在住宠物，选定后**跳到宠物实景页并自动打开那一单的画面**。

        多只时给可点选项（前端渲染成 chip），用户不用自己组织句子；
        摄像头没开 / 停用 / 离线时不跳转（跳过去也是黑屏），改为小窗提示原因。
        """
        orders = await camera_service.viewable_orders(self.db, self.user)
        if not orders:
            reply = (
                "现在没有寄养中的宠物，所以还没有实景可看 🐾\n"
                "宠物入住后就能在这里直接看画面。"
            )
            async for event in self._answer_and_save(session, reply, intent="open_camera"):
                yield event
            return

        # 找目标宠物：槽位 → 用户原话里出现的名字 → 只有一只就默认它
        wanted = (slots.get("pet_name") or "").strip()
        matched = None
        if wanted:
            matched = next(
                (o for o in orders if o.get("pet_name") and wanted in o["pet_name"]), None
            )
        if matched is None:
            hits = [o for o in orders if o.get("pet_name") and o["pet_name"] in text]
            if len(hits) == 1:
                matched = hits[0]
        if matched is None and len(orders) == 1:
            matched = orders[0]

        if matched is None:
            lines = ["你现在寄养中的毛孩子："]
            for order in orders:
                state = "可以看" if order["can_watch"] else (order.get("reason") or "暂不可看")
                lines.append(f"· {order['pet_name']}（{order['order_no']}）— {state}")
            lines.append("想看哪一只？点下面的按钮，或者说「看豆豆的实景」都行。")
            yield {"type": "choices", "items": [f"看{o['pet_name']}的实景" for o in orders]}
            async for event in self._answer_and_save(
                session, "\n".join(lines), intent="open_camera"
            ):
                yield event
            return

        pet_name = matched["pet_name"]
        if not matched["can_watch"]:
            # 设备不可用：先解释清楚再问要不要继续（跳过去只会看到空列表）
            reason = matched.get("reason") or "设备不可用"
            yield {
                "type": "camera_error",
                "pet_name": pet_name,
                "order_no": matched["order_no"],
                "reason": reason,
            }
            reply = (
                f"「{pet_name}」的摄像头现在看不了：{reason}。\n"
                "已经提醒门店检查，稍后再试或直接联系店员确认。"
            )
            async for event in self._answer_and_save(session, reply, intent="open_camera"):
                yield event
            return

        yield {
            "type": "navigate",
            "path": f"/user/camera?order_id={matched['order_id']}",
            "label": "宠物实景",
        }
        reply = (
            f"已经为你打开「{pet_name}」的实时画面 🎥\n"
            "· 画面上有手机号后四位浮水印，凭证 5 分钟有效\n"
            "· 看完点「结束观看」，把名额让给家人"
        )
        async for event in self._answer_and_save(session, reply, intent="open_camera"):
            yield event

    async def _recover_session(self, session: ChatSession) -> None:
        """工具异常回滚后重新加载会话对象。

        rollback() 会让 ORM 实例的所有属性过期，此后任何属性访问都会触发
        惰性加载；在纯 async 上下文里这会直接抛 MissingGreenlet。
        因此回滚后必须显式刷新，才能继续安全地写消息。
        """
        sid = session.__dict__.get("id")
        try:
            await self.db.refresh(session)
        except Exception:
            if sid is not None:
                fresh = await self.db.get(ChatSession, sid)
                if fresh is not None:
                    session.__dict__.update(fresh.__dict__)

    # ------------------------------------------------------------ 意图识别
    async def _interpret(self, session: ChatSession, text: str) -> dict:
        """意图识别：先跑规则法兜底，LLM 可用时再用模型纠偏。


            LLM 任何异常都降级为规则结果 —— AI 只能提升效率，不能成为单点。
        """
        rule = self._interpret_by_rule(text)
        result: dict[str, Any] = {
            "intent": rule["intent"],
            "slots": rule["slots"],
            "reply": "", "source": "rule",
        }

        # 「看实景」是纯导航动作，没有歧义：规则命中就直接用规则结果，
        # 不让 LLM 改判成「查预约」（实测 LLM 会把它理解成看订单进度，V8.2）
        if rule["intent"] == "open_camera":
            # 规则结果只有 intent / slots，补齐 source 供上层记录来源
            return {**rule, "source": "rule", "reply": ""}

        if not settings.llm_available:
            if rule["intent"] == "smalltalk":
                result["reply"] = SMALLTALK_FALLBACK
            return result

        history = await self._load_history(session)
        role = self.user.role
        role_hint = ROLE_PROMPT_HINT.get(role, "")
        system_prompt = INTENT_SYSTEM_PROMPT
        operation_prompt = ROLE_OPERATION_PROMPT.get(role)
        if operation_prompt:
            system_prompt = f"{INTENT_SYSTEM_PROMPT}\n\n{operation_prompt}"

        messages = [{"role": "system", "content": system_prompt}]
        messages += history
        messages.append({
            "role": "user",
            "content": (
                f"{role_hint}\n\n"
                + ("【特殊意图】open_camera：用户想看宠物实时画面 / 摄像头 / 在干嘛时，intent 输出 open_camera（不需要工具）\n"
                   if role == UserRole.CUSTOMER.value else "")
                + f"【当前角色可用工具（intent 只能取其中之一、open_camera 或 smalltalk）】\n"
                f"{json.dumps(tool_manifest(role), ensure_ascii=False)}\n"
                f"【今天日期】{date.today().isoformat()}\n"
                f"【用户说】{text}"
            ),
        })
        # LLM 只能提升效率，不能成为单点：任何异常都降级到规则法（项目铁律）
        try:
            res = await bailian_client.chat_with_fallback(messages, json_mode=True, temperature=0)
        except Exception as exc:  # pragma: no cover - 兜底分支，混沌测试覆盖
            logger.warning("llm_interpret_failed: %s", exc)
            res = None
        data = res.data if (res is not None and res.ok) else None
        if not data:
            if rule["intent"] == "smalltalk":
                result["reply"] = SMALLTALK_FALLBACK
            return result

        llm_intent = str(data.get("intent") or "").strip()
        # 画像守门（V8.4.2）：LLM 只能在「当前角色的画像内」改判。
        # 实测它会把「应激反应的三个等级」判成店员的查档案工具，宠主 / 店员撞上
        # 权限报错 —— 与其让用户撞墙，不如退回规则结果；规则也不可调用时保持原样。
        profile = ROLE_TOOL_PROFILE.get(role, ())
        if rule["intent"] == "search_knowledge" and llm_intent == "smalltalk":
            # 规则确凿命中知识问答（关键词或领域疑问句兜底）时，不让 LLM 降回寒暄
            result["intent"] = "search_knowledge"
        elif rule["intent"] in WRITE_INTENTS and rule["intent"] in profile and llm_intent == "smalltalk":
            # 写操作是确定性动作：模型抖一下（返回 smalltalk）不能把「预约 / 取消」变成闲聊，
            # 否则用户会以为系统没听懂（实测冒烟就撞到过：模型 502 抖动后把预约判成寒暄）
            result["intent"] = rule["intent"]
        elif llm_intent == "smalltalk" or llm_intent in profile or (
            llm_intent == "open_camera" and role == UserRole.CUSTOMER.value
        ):
            result["intent"] = llm_intent
            result["source"] = "llm"
        elif rule["intent"] in profile:
            result["intent"] = rule["intent"]
        elif rule["intent"] == "search_knowledge":
            result["intent"] = "search_knowledge"  # 三角色画像都含知识检索，规则命中就别丢

        # 槽位合并策略：规则抽取优先（防止 LLM 编造日期/宠物名），LLM 仅补充规则未识别的项。
        # 白名单取自工具签名（ALL_SLOT_KEYS），因此新增工具参数后无需再改这里。
        llm_slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
        merged = dict(rule["slots"])
        for key_name, value in llm_slots.items():
            if key_name not in ALL_SLOT_KEYS or value in (None, "", []):
                continue
            if merged.get(key_name):
                continue  # 规则已抽到的值优先，避免 LLM 改判
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                merged[key_name] = value
            else:
                merged[key_name] = str(value).strip()
        # 性别 / 物种等枚举值统一归一化：中文口语（母 / 雌猫 / 弟弟）由归一化函数兜住。
        # 归一化失败时置 None（而不是回落 male）——「没听懂」必须让用户补，不能偷偷写成公。
        if merged.get("gender"):
            merged["gender"] = normalize_gender(str(merged["gender"]))
        if merged.get("species"):
            merged["species"] = normalize_species(str(merged["species"]))

        # 服务类型必须落在枚举内
        if merged.get("service_type") and merged["service_type"] not in set(SERVICE_TYPE_LABEL):
            merged["service_type"] = None
        result["slots"] = merged
        if result["intent"] == "smalltalk":
            result["reply"] = str(data.get("reply") or "").strip() or SMALLTALK_FALLBACK
        return result

    def _interpret_by_rule(self, text: str) -> dict:
        """规则法意图识别：按「售前查询 / 写操作 / 运营动作」的顺序匹配关键词。


            顺序即优先级，改规则前先确认不会抢走其他意图的请求。
        """
        slots: dict[str, Any] = {
            "appoint_date": None, "slot_time": None, "pet_name": None,
            "service_type": None, "order_no": None, "keyword": None,
            "phone": None, "target_status": None,
            "setting_key": None, "setting_value": None, "username": None,
            # 宠物之家 / 档案（V8.2）
            "name": None, "species": None, "gender": None, "breed": None,
            "birthday": None, "weight": None, "allergy": None,
            # 寄养（V7.1）
            "check_in": None, "check_out": None, "room_no": None,
            "feeding_plan": None, "dropoff_method": None, "pickup_back_method": None,
            # 用品（V7.2）
            "product_name": None, "spec_name": None, "quantity": None,
            "pickup_method": None, "address": None, "remark": None,
            # 知识检索（V8.3）
            "query": None,
        }

        order_match = re.search(r"PG\d{10,20}", text, re.IGNORECASE)
        if order_match:
            slots["order_no"] = order_match.group(0).upper()

        phone_match = re.search(r"(?<!\d)(1[3-9]\d{9})(?!\d)", text)
        if phone_match:
            slots["phone"] = phone_match.group(1)

        quoted = re.search(r"[「『]([^」』]{1,30})[」』]", text) or re.search(r'"([^"]{1,30})"', text)
        if quoted:
            slots["keyword"] = quoted.group(1).strip()

        for word, mapped in STATUS_ALIAS.items():
            if word in text:
                slots["target_status"] = mapped
                break

        slot_match = re.search(r"(\d{1,2})\s*[:：]\s*(\d{2})", text)
        if slot_match:
            slots["slot_time"] = f"{int(slot_match.group(1)):02d}:{slot_match.group(2)}"
        else:
            hour_match = re.search(r"(\d{1,2})\s*点", text)
            if hour_match:
                slots["slot_time"] = f"{int(hour_match.group(1)):02d}:00"

        parsed_date = parse_date(text)
        if parsed_date:
            slots["appoint_date"] = parsed_date.isoformat()

        if "药浴" in text or "治疗浴" in text:
            slots["service_type"] = "medicated_bath"
        elif "美容" in text or "修剪" in text or "造型" in text:
            slots["service_type"] = "grooming"
        elif "洗澡" in text or "洗护" in text:
            slots["service_type"] = "basic_bath"

        # 店员 / 店长的运营类意图优先匹配（这些工具不在宠主画像里）
        if self.user.role in (UserRole.STAFF.value, UserRole.MANAGER.value):
            role_intent = self._operation_intent_by_rule(text)
            if role_intent:
                return {"intent": role_intent, "slots": slots}

        intent = "smalltalk"
        # 看实景：先判，避免「看看宠物状态」被「宠物档案」抢走
        # 看实景：必须带明确的「观看」意图。
        # 单独的「状态怎么样」不算——「球球健康状态怎么样，需不需要吃药」问的是健康，
        # 不是要看摄像头（实测被 open_camera 抢走，回了「没有寄养中的宠物」）。
        cam_words = ("实景", "摄像头", "监控", "直播", "看看宠物", "看看我的宠物",
                     "在干嘛", "在做什么", "看一眼")
        if any(k in text for k in cam_words) or ("状态怎么样" in text and "看" in text):
            intent = "open_camera" if self.user.role == UserRole.CUSTOMER.value else "smalltalk"
        # 洗护 / 营养 / 行为 / 用品选购问答：必须排在「预约 / 洗澡 / 风险 / 档案 / 下单 / 用品推荐」之前。
        # 否则「疫苗后多久能洗澡」会被「洗澡」抢成创建预约，「皮肤病怎么洗」会被「皮肤病」抢成查档案，
        # 「球球喂养有什么推荐的」会被「推荐」抢成查商品（实测就是这么错的）。
        # 含购买 / 预约动作词的文本在这里直接判 False（见 PURCHASE_HINTS），不会抢走下单意图。
        elif self._looks_like_knowledge_intent(text) and not any(
            k in text for k in ("寄养", "建档案", "建个档", "新建档案")
        ):
            intent = "search_knowledge"
            slots["query"] = text

        # 建档案：口语常是「建个档」「加一只猫」，别被查询档案抢走
        elif any(k in text for k in ("建档案", "建个档", "新建档案", "创建档案", "加一只",
                                      "登记一只", "录入宠物", "给我的狗建", "给我的猫建")):
            intent = "create_pet_profile"
            self._extract_pet_slots(text, slots)
        # 寄养
        elif "寄养" in text:
            if any(k in text for k in ("多少钱", "价格", "空房", "有哪些房", "怎么收费", "能寄养吗", "疫苗")):
                intent = "query_boarding_options"
            else:
                intent = "create_boarding_order"
            date_words = re.findall(r"\d{4}-\d{2}-\d{2}", text)
            if len(date_words) >= 2:
                slots["check_in"], slots["check_out"] = date_words[0], date_words[1]
        # 用品
        elif any(k in text for k in ("购物车", "提交订单", "结算", "下单买", "结账")):
            intent = "submit_goods_order" if any(k in text for k in ("提交", "结算", "结账", "下单")) else "add_goods_to_cart"
        # 「买什么 / 用什么 / 推荐买」是询问，不是加购：必须排在「买」之前，
        # 否则「用什么用品推荐买的」会被当成要加购（实测）。
        elif any(k in text for k in ("买什么", "用什么", "推荐买", "买哪种", "买哪个",
                                      "有什么好", "有什么推荐", "推荐个", "有卖")):
            intent = "query_goods"
            slots["keyword"] = self._extract_product_name(text)
        elif any(k in text for k in ("买", "加购", "来一袋", "来一包", "来一盒")):
            intent = "add_goods_to_cart"
            slots["product_name"] = self._extract_product_name(text)
            qty_match = re.search(r"(\d{1,3})\s*(?:件|个|袋|包|盒|瓶|支|罐|份)", text)
            if qty_match:
                slots["quantity"] = int(qty_match.group(1))
        elif any(k in text for k in ("用品", "有什么好", "推荐", "多少钱", "库存", "有卖")):
            intent = "query_goods"
        elif any(k in text for k in ("取消", "退订", "退掉", "不去了")):
            intent = "cancel_appointment"
        elif any(k in text for k in ("改期", "改时间", "换个时间", "推迟")):
            intent = "reschedule_appointment"
        # 「我自己的预约」优先于时段查询：「我还有几单没洗」里的「还有」不代表问空位
        elif any(k in text for k in ("我的预约", "我最近的", "到哪一步", "进度", "约了",
                                      "订单状态", "几单", "我的单")):
            intent = "query_my_appointments"
        # 查询类先判：疑问句式（哪些 / 还有空 / 几点）优先于「预约」二字，
        # 否则「明天还有哪些时段可以预约？」会被当成「创建预约」。
        elif any(k in text for k in ("哪些", "还有空", "还有位置", "有空", "空位",
                                      "几点", "什么时候", "可约", "时段")):
            intent = "query_slots"
        elif any(k in text for k in ("预约", "约一个", "订一个", "安排", "洗个澡", "洗澡",
                                      "我要约", "帮我约", "想约", "约周")):
            intent = "create_appointment"
        elif any(k in text for k in ("风险", "注意", "安全")):
            intent = "query_risk_report"
        elif any(k in text for k in ("报表", "统计", "数据", "经营")):
            intent = "query_report_summary"
        elif any(k in text for k in ("档案", "过敏", "皮肤病", "应激", "多重", "体重", "我的宠物", "毛孩子")):
            intent = "query_pet_profile"
        elif any(k in text for k in ("我的预约", "订单", "进度", "约了")):
            intent = "query_my_appointments"

        # 知识问答兜底（V8.4.2）：以上关键词覆盖不了所有问法（「为什么必须先看后洗」这类），
        # 与其把洗护领域的疑问句当寒暄打发，不如检索知识库 —— 哪怕只回「通用规范」，
        # 也好过一句「你好呀，我是洗护小助手」的答非所问。
        if intent == "smalltalk" and self._looks_like_knowledge_question(text):
            intent = "search_knowledge"
            slots["query"] = text

        return {"intent": intent, "slots": slots}

    @staticmethod
    def _looks_like_knowledge_intent(text: str) -> bool:
        """是不是在问「通用专业知识」，而不是在查某只宠物的数据 / 下单 / 预约。

        判定 = 命中知识领域词 且 不含购买预约类动作词。
        提到宠物名不算「要查档案」——「球球喂养有什么推荐的」问的是建议，不是档案。
        """
        content = text or ""
        if any(w in content for w in PURCHASE_HINTS):
            return False
        # 「看看豆豆的应激记录」问的是数据不是知识：记录 / 档案 / 历史类一律让位给档案查询
        if any(w in content for w in RECORD_HINTS):
            return False
        # 「有什么猫砂推荐 / 用什么用品」问的是「店里有啥」，让位给 query_goods 列商品；
        # 「猫砂怎么选」没有这组询问词，仍然走知识（选购标准）。
        if any(w in content for w in GOODS_HINTS) and any(
            w in content for w in ("推荐", "有什么", "买什么", "用什么", "哪款", "哪个牌子")
        ):
            return False
        # 「为什么必须先看后洗」这类问原理的句子不带任何固定术语，
        # 用「为什么 / 为何 + 洗护」的组合兜住；不加单独的「为什么」，
        # 否则「为什么我的预约没成功」会被当成知识问答。
        if ("为什么" in content or "为何" in content) and ("洗" in content or "护" in content):
            return True
        return any(w in content for w in KNOWLEDGE_HINTS)

    @staticmethod
    def _looks_like_knowledge_question(text: str) -> bool:
        """领域疑问句判定（兼容旧调用）：领域词 + 求解释的问法，且没有下单 / 预约类动作词。

        只在规则关键词全部落空后的 smalltalk 分支兜底，宁可保守（漏判只会回到寒暄），
        也不抢走「明天帮我约个洗澡」这类动作意图。
        """
        if len(text) < 4:
            return False
        if not AgentRunner._looks_like_knowledge_intent(text):
            return False
        question = ("怎么", "如何", "什么", "为什么", "哪些", "几个", "几级", "多少",
                    "步骤", "方法", "等级", "分级", "标准", "流程", "规范", "注意",
                    "能不能", "可以", "建议", "吗", "？", "?")
        return any(w in text for w in question)

    # ---------------------------------------------------- 规则法槽位抽取（LLM 不可用的兜底）
    @staticmethod
    def _extract_pet_slots(text: str, slots: dict) -> None:
        """从「建档案」这句话里抽名字 / 物种 / 性别 / 品种 / 体重 / 生日 / 过敏史。

        规则法必须能把档案建对：LLM 不可用时全靠它，且它是槽位合并的第一优先级，
        抽错了 LLM 也覆盖不回来（V8.2 的「说母建公」就是这里没抽性别导致的）。
        """
        # 名字：优先「它叫豆豆」「名字叫豆豆」，其次「建个档：豆豆」这种冒号写法
        name_match = re.search(
            r"(?:它叫|名字叫|名字是|名叫|叫|名字[:：]|宠物名[:：])\s*([\u4e00-\u9fa5A-Za-z0-9]{1,10})", text
        )
        if name_match is None:
            name_match = re.search(
                r"(?:建个档|建档案|新建档案|创建档案|登记|录入)[:：，,\s]+([\u4e00-\u9fa5A-Za-z0-9]{1,10})", text
            )
        if name_match:
            candidate = name_match.group(1)
            # 「叫它」「叫什么」这类不是名字
            if candidate not in ("什么", "啥", "它", "我", "你"):
                slots["name"] = candidate.rstrip("的了呢吧啊呀哦，。")

        species = normalize_species(text)
        if species:
            slots["species"] = species

        gender = normalize_gender(text)
        if gender:
            slots["gender"] = gender

        breed_match = re.search(r"(?:品种是|品种为|品种[:：]|品种)\s*([\u4e00-\u9fa5A-Za-z]{2,10})", text)
        if breed_match:
            slots["breed"] = breed_match.group(1)
        else:
            # 没有「品种」二字时按常见品种词典认（「金毛」「布偶」「泰迪」…）
            hit = next((b for b in PET_BREED_WORDS if b in text), None)
            if hit:
                slots["breed"] = hit

        weight_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|KG|Kg|公斤|千克)", text)
        if weight_match:
            slots["weight"] = float(weight_match.group(1))

        # 生日：直接给日期优先，其次用「X 岁 / X 个月」倒推
        parsed = parse_date(text)
        if parsed and re.search(r"\d{4}[-/.]\d{1,2}", text):
            slots["birthday"] = parsed.isoformat()
        else:
            slot_birthday = _birthday_from_age_text(text)
            if slot_birthday:
                slots["birthday"] = slot_birthday.isoformat()

        allergy_match = re.search(r"(?:对)?([\u4e00-\u9fa5A-Za-z]{1,10})(?:成分)?过敏", text)
        if allergy_match:
            word = allergy_match.group(1).strip("的对有它这只毛孩子宠物")
            if word:
                slots["allergy"] = word

    @staticmethod
    def _extract_product_name(text: str) -> str | None:
        """从「买 X」里抽商品名：保留括号里的口味，并剥掉「帮我买」这类动词。

        旧正则只取 `[...]{2,12}粮` 的形式，遇到「成猫全价主粮（三文鱼）」会连动词一起吞进去，
        拼出来的关键词在库里匹配不到（V8.2 实测）。
        """
        tail = ("主粮", "猫粮", "狗粮", "粮", "猫砂", "砂", "浴液", "洗护", "零食",
                "罐头", "玩具", "毛巾", "套装", "磨牙棒", "软骨素", "漏食球", "湿巾")
        pattern = (
            r"([\u4e00-\u9fa5A-Za-z0-9]{2,20}(?:" + "|".join(tail) + r"))"
            r"([（(][^）)]{1,10}[）)])?"
        )
        match = re.search(pattern, text)
        if not match:
            return None
        name = f"{match.group(1)}{match.group(2) or ''}"
        name = clean_product_name(name)
        return name or None

    def _operation_intent_by_rule(self, text: str) -> str | None:
        """店员 / 店长的运营类意图关键词匹配（LLM 不可用时的降级路径）。

        顺序：店长专属 → 店员日常 → 返回 None 交给通用规则。
        """
        is_manager = self.user.role == UserRole.MANAGER.value

        # 写操作优先判定：口语化的「把 X 改成 Y」常常不含「配置」二字，
        # 若放在只读意图之后，会被「流失」「时段」等名词抢先命中（评测集实测踩到）。
        if any(k in text for k in ("改成", "调成", "改为", "调到", "修改为", "设置为")) and any(
            k in text for k in ("天数", "容量", "时段", "时限", "留存", "爽约", "预警", "参数", "配置", "规则")
        ):
            return "update_store_setting"
        if "账号" in text and any(k in text for k in ("启用", "禁用", "停用", "开启", "关闭")):
            return "toggle_user_status"

        if is_manager:
            if any(k in text for k in ("审计", "操作日志", "谁改", "改过什么")):
                return "query_audit_trail"
            if any(k in text for k in ("sla", "SLA", "超时巡检", "巡检")):
                return "run_sla_scan"
            if any(k in text for k in ("经营", "多少单", "做得多", "营收", "报表", "完成率", "爽约率", "复购")):
                return "query_report_summary"
            if any(k in text for k in ("流失", "召回", "该回访", "久没来", "很久没来")):
                return "query_churn_list"
            if any(k in text for k in ("业绩", "工作量", "员工对比", "店员对比", "谁洗得最多", "谁做得多")):
                return "query_staff_performance"
            if any(k in text for k in ("饱和度", "利用率", "加单", "还有空", "哪个时段空", "时段空",
                                        "忙不忙", "闲不闲", "很闲", "是不是很闲")):
                return "query_capacity_analysis"

        # 门店配置只读（放在店长专属意图之后：「最近谁改过门店配置」属于审计，不是查配置）
        if any(k in text for k in ("配置", "参数", "设置", "门店规则")):
            return "query_store_settings"

        if any(k in text for k in ("待办", "要处理", "交接", "交班", "今天要做什么", "有什么要处理")):
            return "query_todo"
        if any(k in text for k in ("排期", "排了几单", "今天排了", "明天排了", "时段安排", "预约安排")):
            return "query_day_schedule"
        if any(k in text for k in ("代客预约", "帮客户预约", "帮客户下单", "客户要预约",
                                    "给客户预约", "为客户预约", "客户要下单")):
            return "create_appointment_for_customer"
        if any(k in text for k in ("复核", "风险确认", "确认风险")):
            return "confirm_risk"
        if any(k in text for k in ("上次洗护", "洗护记录", "历史洗护", "用过什么", "之前洗", "洗护历史")):
            return "query_wash_history"
        if "档案" in text or (
            any(k in text for k in ("客户", "客人", "宠主"))
            and any(k in text for k in ("查", "找", "看看", "信息"))
        ):
            return "query_customer_pets"
        if any(k in text for k in ("这单", "该单", "订单")) and any(
            k in text for k in ("确认", "到店", "开始洗", "完成", "洗完", "取消", "爽约", "放弃", "中断")
        ):
            return "advance_appointment"

        return None

    async def _match_pet_name(self, text: str) -> str | None:
        cond = [Pet.deleted_at.is_(None)]
        if self.user.role == UserRole.CUSTOMER.value:
            cond.append(Pet.user_id == self.user.id)
        pets = (await self.db.execute(select(Pet).where(*cond))).scalars().all()
        for pet in pets:
            if pet.name and pet.name in text:
                return pet.name
        return None

    # ------------------------------------------------------------ 历史与持久化
    async def _load_history(self, session: ChatSession) -> list[dict[str, str]]:
        """取最近若干轮对话作为模型上下文（过长会截断，避免 token 爆掉）。


        """
        rows = (
            await self.db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session.id, ChatMessage.role.in_(["user", "assistant"]))
                .order_by(ChatMessage.id.desc())
                .limit(MAX_HISTORY)
            )
        ).scalars().all()
        return [{"role": m.role, "content": m.content or ""} for m in reversed(rows)]

    async def _save(
        self,
        session: ChatSession,
        *,
        role: str,
        content: str,
        intent: str | None = None,
        tool: str | None = None,
        result: Any = None,
        step: int = 0,
    ) -> ChatMessage:
        """把本轮问答写入会话记录，供历史回看与留存清理。


        """
        from app.utils.logger import mask_sensitive

        # 仅对用户输入做脱敏（用户可能输入自己的手机号）。
        # 助手回复不可脱敏：其中包含预约单号等业务标识，脱敏后会变成不可读的星号串。
        stored = mask_sensitive(content or "") if role == "user" else (content or "")
        msg = ChatMessage(
            session_id=session.id,
            user_id=session.user_id,
            role=role,
            content=stored[:6000],
            intent=intent,
            tool_name=tool,
            tool_result=json.dumps(result, ensure_ascii=False, default=str)[:6000] if result else None,
            step=step,
        )
        self.db.add(msg)
        session.last_message_at = datetime.now()
        if role == "user":
            session.turn_count += 1
        await self.db.commit()
        return msg

    # ------------------------------------------------------------ 文案生成
    async def _thought(self, content: str) -> AsyncGenerator[dict, None]:
        yield {"type": "thought", "content": content}
        await asyncio.sleep(0)

    async def _answer_and_save(
        self, session: ChatSession, text: str, *, intent: str | None = None,
        tool: str | None = None, result: Any = None,
    ) -> AsyncGenerator[dict, None]:
        """逐字流式输出，形成柔和的打字机效果。

        出口统一过一遍**合规风控**（`compliance.review_answer`）：急症置顶就医提示、
        诊断/剂量追加免责、有毒食物被当推荐时改写为警告。规则判定，不额外调模型。
        """
        verdict = review_answer(text, intent=intent)
        if verdict.triggered:
            logger.info("compliance_triggered", extra={"extra_fields": {
                "intent": intent, "flags": verdict.flags}})
            text = apply_verdict(text, verdict)
        for i in range(0, len(text), 2):
            yield {"type": "answer", "delta": text[i : i + 2]}
            await asyncio.sleep(0.018)
        await self._save(session, role="assistant", content=text, intent=intent, tool=tool, result=result,
                         step=1)

    def _ask_for_missing(self, intent: str, missing: list[str], slots: dict) -> str:
        label = {
            "pet_name": "哪只毛孩子", "appoint_date": "哪一天", "slot_time": "几点",
            "order_no": "预约单号", "target_status": "目标状态",
            "phone": "宠主手机号", "username": "账号用户名",
            "setting_key": "配置项", "setting_value": "目标值",
            "name": "宠物名字", "check_in": "入住日期", "check_out": "离店日期",
            "product_name": "商品名称", "quantity": "数量",
        }
        if intent == "query_slots" and "appoint_date" in missing:
            return "想查哪一天的时段呀？可以说「今天」「明天」或者具体日期，比如 2026-10-20 🐾"
        if intent == "create_appointment":
            need = "、".join(label.get(m, m) for m in missing)
            got = []
            if slots.get("pet_name"):
                got.append(f"宠物「{slots['pet_name']}」")
            if slots.get("appoint_date"):
                got.append(f"日期 {slots['appoint_date']}")
            if slots.get("slot_time"):
                got.append(f"时段 {slots['slot_time']}")
            prefix = f"已经记下：{'、'.join(got)}。" if got else ""
            return f"{prefix}还差 {need} 就可以帮你预约啦，麻烦补充一下 🐾"
        if intent == "create_pet_profile":
            return "给它起个名字就行，其余信息（品种、体重、生日）可以以后慢慢补 🐾"
        if intent == "create_boarding_order":
            need = "、".join(label.get(m, m) for m in missing)
            return (f"寄养还需要：{need}。\n"
                    "比如「豆豆 2027-03-10 到 2027-03-13 寄养」，我会先查疫苗和空房再跟你确认。")
        if intent == "add_goods_to_cart":
            return "想买哪件用品？说个名字或关键字就行，比如「低敏无香洗护套装 2 件」。"
        if intent == "cancel_appointment":
            return "请告诉我要取消哪一笔预约的**预约单号**（形如 PG20261014xxxxxx），我先帮你核对。"
        if intent == "reschedule_appointment":
            need = "、".join(label.get(m, m) for m in missing)
            return f"改期还需要：{need}。请一并告诉我，我会先跟你确认再提交。"
        if intent == "advance_appointment":
            need = "、".join(label.get(m, m) for m in missing)
            return (f"推进订单还需要：{need}。\n"
                    "可以直接说「PGxxxx 这单确认」「PGxxxx 到店了」「PGxxxx 洗完了」。")
        if intent == "confirm_risk":
            return "请提供要复核的**预约单号**（形如 PG20261014xxxxxx），我先查一下风险报告。"
        if intent == "query_wash_history":
            return "想查哪只宠物的洗护记录？告诉我宠物名字就行 🐾"
        if intent == "create_appointment_for_customer":
            need = "、".join({"phone": "宠主手机号", "pet_name": "宠物名",
                              "appoint_date": "日期", "slot_time": "时段"}.get(m, m) for m in missing)
            return f"代客预约还需要：{need}。补齐后我会先跟你确认再提交。"
        if intent == "update_store_setting":
            return ("请说明要修改的**配置项**和**目标值**，例如「把流失预警天数改成 60」。\n"
                    "我可以先用「看看门店配置」列出全部配置项。")
        if intent == "toggle_user_status":
            return "请提供要启用的账号用户名，例如「启用账号 staff2」。"
        return f"还需要补充：{'、'.join(label.get(m, m) for m in missing)}"

    async def _find_pet(self, pet_name: str | None) -> Pet | None:
        """按名字找当前账号可见的宠物（预检与确认提示共用）。"""
        cond = [Pet.deleted_at.is_(None)]
        if self.user.role == UserRole.CUSTOMER.value:
            cond.append(Pet.user_id == self.user.id)
        if pet_name:
            cond.append(Pet.name.like(f"%{pet_name}%"))
        return (await self.db.execute(select(Pet).where(*cond).order_by(Pet.id))).scalars().first()

    def _confirm_prompt(self, intent: str, slots: dict) -> str:
        tail = "回复「确认」我就提交，回复「取消」则不执行。"
        if intent == "create_appointment":
            svc = SERVICE_TYPE_LABEL.get(slots.get("service_type") or "basic_bath", "基础洗澡")
            return (
                "帮你确认一下这次预约 🐾\n"
                f"· 毛孩子：{slots.get('pet_name')}\n"
                f"· 服务：{svc}\n"
                f"· 到店时间：{slots.get('appoint_date')} {slots.get('slot_time')}\n" + tail
            )
        if intent == "create_pet_profile":
            bits = [f"· 名字：{slots.get('name')}"]
            if slots.get("species"):
                bits.append(f"· 物种：{PET_SPECIES_LABEL.get(slots['species'], slots['species'])}")
            if slots.get("gender"):
                # 性别必须回显在确认卡上：用户说「母」却建出「公」，就是因为既没抽取也没回显
                bits.append(f"· 性别：{PET_GENDER_LABEL.get(slots['gender'], slots['gender'])}")
            if slots.get("breed"):
                bits.append(f"· 品种：{slots['breed']}")
            if slots.get("birthday"):
                bits.append(f"· 生日：{slots['birthday']}")
            if slots.get("weight"):
                bits.append(f"· 体重：{slots['weight']}kg")
            if slots.get("allergy"):
                bits.append(f"· 过敏史：{slots['allergy']}")
            return "帮你建个档案 🐾\n" + "\n".join(bits) + "\n其余信息（绝育、应激等级）可以之后在档案里补。\n" + tail

        if intent == "create_boarding_order":
            est = slots.get("_est_total")
            nights = slots.get("_nights")
            return (
                "寄养确认单 🐾\n"
                f"· 毛孩子：{slots.get('pet_name')}\n"
                f"· 宠舍：{slots.get('_room_name') or slots.get('room_no') or '系统选最便宜的可订房'}\n"
                f"· 入住 → 离店：{slots.get('check_in')} → {slots.get('check_out')}"
                + (f"（{nights} 晚）" if nights else "") + "\n"
                + (f"· 预估费用：¥{est:.2f}（以门店最终结算为准）\n" if est else "")
                + "提交即表示同意寄养条款与责任划分，并授权紧急就医。\n" + tail
            )

        if intent == "add_goods_to_cart":
            return (
                f"把「{slots.get('product_name')}」加入购物车 🛒\n"
                + (f"· 规格：{slots.get('spec_name')}\n" if slots.get("spec_name") else "")
                + f"· 数量：{slots.get('quantity') or 1}\n"
                + "加购后可以说「提交订单」，我再帮你结算。\n" + tail
            )

        if intent == "submit_goods_order":
            return (
                "用品订单确认 🛒\n"
                f"· 商品：{slots.get('_cart_names') or '购物车商品'}\n"
                f"· 件数：{slots.get('_cart_count')} 件\n"
                f"· 金额：¥{slots.get('_cart_total')}"
                + ("（含配送费）" if (slots.get("pickup_method") == "delivery") else "（到店自提）") + "\n" + tail
            )

        if intent == "cancel_appointment":
            return f"即将取消预约 {slots.get('order_no')}，取消后时段会释放给其他毛孩子。\n" + tail
        if intent == "create_appointment_for_customer":
            svc = SERVICE_TYPE_LABEL.get(slots.get("service_type") or "basic_bath", "基础洗澡")
            return (
                "帮你确认一下这单代客预约 🐾\n"
                f"· 宠主手机号：{slots.get('phone')}\n"
                f"· 毛孩子：{slots.get('pet_name')}\n"
                f"· 服务：{svc}\n"
                f"· 到店时间：{slots.get('appoint_date')} {slots.get('slot_time')}\n" + tail
            )
        if intent == "advance_appointment":
            target = STATUS_ALIAS.get(slots.get("target_status") or "", slots.get("target_status"))
            label = APPOINTMENT_STATUS_LABEL.get(target, target)
            return (
                "即将推进订单状态：\n"
                f"· 单号：{slots.get('order_no')}\n"
                f"· 目标状态：{label}\n" + tail
            )
        if intent == "confirm_risk":
            return (
                f"即将复核确认预约 {slots.get('order_no')} 的洗护风险报告。\n"
                "复核后该报告将标记为已确认，并由你负责执行处置措施。\n" + tail
            )
        if intent == "update_store_setting":
            return (
                f"即将修改门店配置：{slots.get('setting_key')} → {slots.get('setting_value')}\n"
                "超出取值范围的配置会被直接拒绝。\n" + tail
            )
        if intent == "toggle_user_status":
            return f"即将切换账号「{slots.get('username')}」的启用状态。\n" + tail
        if intent == "run_sla_scan":
            return (
                "即将手动触发店员确认 SLA 巡检（超时订单会升级提醒，必要时按配置自动取消）。\n" + tail
            )
        return (
            f"即将把预约 {slots.get('order_no')} 改到 {slots.get('appoint_date')} {slots.get('slot_time')}。\n" + tail
        )

    def _format_answer(self, tool_name: str, result: dict) -> str:
        """把工具返回的结构化结果转成给用户看的中文回答（含数字与时间格式化）。


        """
        if tool_name == "query_slots":
            available = [s for s in result.get("slots", []) if s.get("available")]
            if not available:
                return f"{result['appoint_date']} 已经约满啦，要不要看看别的日期？🐾"
            lines = [f"{result['appoint_date']} 还有 {len(available)} 个时段可以约："]
            for s in available:
                lines.append(f"· {s['slot_time']}（余 {s['remain']}/{s['capacity']}）")
            lines.append("告诉我想约哪个时段，我帮你安排～")
            return "\n".join(lines)

        if tool_name == "query_pet_profile":
            pets = result.get("pets") or []
            if not pets:
                return "还没有找到宠物档案呢，先为毛孩子建一个温暖的小窝吧 🏠"
            lines = []
            for p in pets[:3]:
                tags = []
                if p.get("allergy"):
                    tags.append("有过敏史")
                if p.get("skin_disease"):
                    tags.append("有皮肤病史")
                if p.get("aggressive"):
                    tags.append("有攻击倾向")
                if (p.get("stress_level") or 0) >= 2:
                    tags.append("应激偏高")
                lines.append(
                    f"· {p['name']}（{p.get('breed') or '未知品种'}，{p.get('weight') or '-'}kg）"
                    + ("｜" + "、".join(tags) if tags else "｜暂无风险标记")
                )
            return "这是当前的宠物档案 🐾\n" + "\n".join(lines)

        if tool_name == "query_my_appointments":
            items = result.get("items") or []
            if not items:
                return "暂时还没有预约记录，要不要给毛孩子安排一次香喷喷的洗护？🛁"
            lines = [f"共 {result['total']} 笔预约，最近 {len(items)} 笔："]
            for a in items:
                lines.append(
                    f"· {a['order_no']}｜{a.get('pet_name')}｜{a['appoint_date']} {a['slot_time']}"
                    f"｜{a['status_label']}"
                )
            return "\n".join(lines)

        if tool_name == "query_risk_report":
            level = result.get("risk_level_label") or "-"
            items = result.get("risk_items") or []
            detail = "\n".join(f"· 【{i['level'] == 'high' and '高风险' or '低风险'}】{i['desc']}" for i in items)
            return (
                f"预约 {result.get('order_no')} 的风险等级是「{level}」。\n"
                + (detail + "\n" if detail else "未命中任何风险规则。\n")
                + f"建议：{result.get('suggestion') or '按标准流程执行即可'}"
            )

        if tool_name == "search_knowledge":
            return self._knowledge_fallback_text(result)

        if tool_name == "query_report_summary":
            return (
                f"近 {result['range']} 的经营概况：\n"
                f"· 订单量（已确认及以上）：{result['total_orders']}\n"
                f"· 已完成：{result['completed_orders']}\n"
                f"· 爽约率：{result['no_show_rate']}%\n"
                f"· 复购率：{result['repurchase_rate']}%\n"
                f"· 流失预警宠物：{result['churn_count']} 只"
            )

        if tool_name == "create_appointment":
            return (
                f"预约提交成功啦 🎉\n"
                f"· 单号：{result['order_no']}\n"
                f"· 毛孩子：{result.get('pet_name')}\n"
                f"· 到店时间：{result['appoint_date']} {result['slot_time']}\n"
                f"· 状态：{result.get('status_label')}\n"
                f"· 风险等级：{result.get('risk_level_label') or '待判别'}\n"
                "门店确认后会通过站内消息通知你～"
            )

        if tool_name == "cancel_appointment":
            return f"预约 {result['order_no']} 已取消（{result['from_status']} → {result['to_status']}）。"

        if tool_name == "reschedule_appointment":
            return (
                f"预约 {result['order_no']} 已改到 {result['appoint_date']} {result['slot_time']}，"
                f"累计改期 {result['reschedule_times']} 次。"
            )

        # ---------------- 店员端工具 ----------------
        if tool_name == "query_day_schedule":
            lines = [f"{result['appoint_date']}（{result['weekday']}）共 {result['total']} 单，"
                     f"单时段容量 {result['capacity']}："]
            for s_ in result["slots"]:
                mark = "满" if s_["full"] else f"余 {s_['remain']}"
                detail = "、".join(f"{a['pet_name']}({a['status_label']})" for a in s_["appointments"])
                lines.append(f"· {s_['slot_time']}｜{s_['used']}/{s_['capacity']} {mark}"
                             + (f"｜{detail}" if detail else ""))
            return "\n".join(lines)

        if tool_name == "query_todo":
            lines = [f"{result['date']} 的{result['scope']}待办：",
                     f"· 待确认预约：{result['pending_confirm_total']} 条",
                     f"· 今日预约：{result['today_total']} 条",
                     f"· 待复核风险报告：{result['risk_unconfirmed_total']} 份"]
            for a in result["pending_confirm"]:
                lines.append(f"  - 待确认 {a['order_no']}｜{a['pet_name']}｜{a['slot_time']}")
            for r in result["risk_unconfirmed"]:
                lines.append(f"  - 待复核 {r['order_no']}｜{r['pet_name']}｜{r['risk_level_label']}（{r['hits']} 项）")
            brief = result.get("shift_brief") or {}
            lines.append(f"交班简报：累计洗护 {brief.get('wash_total')} 次，"
                         f"本月 {brief.get('this_month')} 次，平均时长 {brief.get('avg_minutes')} 分钟")
            return "\n".join(lines)

        if tool_name == "query_customer_pets":
            pets = result.get("pets") or []
            if not pets:
                return f"没有找到匹配「{result.get('keyword') or ''}」的客户档案，换个关键词试试？"
            lines = [f"找到 {result['count']} 条客户档案："]
            for p in pets[:5]:
                tags = []
                if p.get("aggressive"):
                    tags.append("攻击倾向")
                if p.get("allergy"):
                    tags.append("过敏史")
                if p.get("skin_disease"):
                    tags.append("皮肤病")
                if (p.get("stress_level") or 0) >= 2:
                    tags.append("应激偏高")
                lines.append(
                    f"· {p['name']}（{p.get('breed') or '未知品种'}，{p.get('weight') or '-'}kg）"
                    f"｜宠主 {p.get('owner_name') or '-'}｜{p.get('owner_phone') or '-'}"
                    + ("｜" + "、".join(tags) if tags else "｜无风险标记")
                )
            return "\n".join(lines)

        if tool_name == "query_wash_history":
            if not result.get("found"):
                return result.get("message") or "没有找到该宠物的档案"
            if not result.get("total"):
                return result.get("message") or "该宠物还没有洗护记录"
            last = result["last"]
            lines = [f"{result['pet_name']} 共 {result['total']} 条洗护记录，最近一次 {result['last_visit']}：",
                     f"· 服务：{last.get('service_type_label')}",
                     f"· 皮肤：{last.get('skin_condition') or '未记录'}",
                     f"· 毛发：{last.get('hair_condition') or '未记录'}",
                     f"· 产品：{last.get('products') or '未记录'}",
                     f"· 店员备注：{last.get('staff_note') or '未记录'}"]
            return "\n".join(lines)

        if tool_name == "advance_appointment":
            return (f"订单 {result['order_no']} 状态已更新："
                    f"{result['from_status']} → {result['to_status']}"
                    + (f"（原因：{result['reason']}）" if result.get("reason") else ""))

        if tool_name == "confirm_risk":
            if result.get("already_confirmed"):
                return f"预约 {result['order_no']} 的风险报告此前已复核过，无需重复确认。"
            return (f"预约 {result['order_no']} 的风险报告已复核确认，"
                    f"风险等级「{result['risk_level_label']}」。"
                    + (f"处置措施：{result['handle_measure']}" if result.get("handle_measure") else ""))

        if tool_name == "create_appointment_for_customer":
            return (
                f"代客预约已提交 🎉\n"
                f"· 单号：{result['order_no']}\n"
                f"· 毛孩子：{result['pet_name']}"
                + ("（复用已有档案）\n" if result.get("reused_existing_pet") else "（已临时建档）\n")
                + f"· 到店时间：{result['appoint_date']} {result['slot_time']}\n"
                f"· 状态：{result['status_label']}\n"
                f"· 风险等级：{result['risk_level_label']}"
            )

        # ---------------- 店长端工具 ----------------
        if tool_name == "query_capacity_analysis":
            lines = [f"排期区间 {result['range']}：单时段容量 {result['capacity']}，",
                     f"整体利用率 {result['utilization_rate']}%（已用 {result['total_used']}/{result['total_capacity']}），",
                     f"完全约满的时段有 {result['fully_booked_count']} 个。"]
            if result["busiest"]:
                lines.append("最忙的时段：")
                for b in result["busiest"]:
                    lines.append(f"· {b['date']} {b['slot_time']}｜{b['used']}/{b['capacity']}")
            if result["most_available"]:
                lines.append("还比较空的时段（可加单）：")
                for b in result["most_available"][:5]:
                    lines.append(f"· {b['date']} {b['slot_time']}｜剩余 {b['remain']}")
            return "\n".join(lines)

        if tool_name == "query_churn_list":
            if not result["items"]:
                return f"按当前配置（{result['churn_days']} 天）暂无流失预警客户，毛孩子们都按时回店啦 🐾"
            lines = [f"按「{result['churn_days']} 天未洗护」口径，共 {result['total']} 只宠物需要回访："]
            for p in result["items"]:
                idle = p.get("idle_days")
                lines.append(
                    f"· {p['pet_name']}｜宠主 {p.get('owner_name') or '-'}｜"
                    f"最后洗护 {p.get('last_wash_date') or '从未'}"
                    + (f"｜已空闲 {idle} 天" if idle is not None else "")
                )
            return "\n".join(lines)

        if tool_name == "query_staff_performance":
            lines = [f"统计区间 {result['range']}，店员工作量对比："]
            for w in result.get("completed_by_staff") or []:
                lines.append(f"· {w.get('staff_name')}：已完成 {w.get('finished_count')} 单")
            if result.get("bookings_by_staff"):
                lines.append("预约量（含未完成）：")
                for w in result["bookings_by_staff"]:
                    lines.append(f"· {w.get('staff_name')}：{w.get('count')} 单")
            return "\n".join(lines) if len(lines) > 1 else "区间内没有店员完成订单的数据。"

        if tool_name == "query_store_settings":
            lines = [f"当前门店配置共 {result['count']} 项："]
            for it in result["settings"]:
                rng = it.get("range") or [None, None]
                rng_text = f"（{rng[0]} ~ {rng[1]}）" if rng[0] is not None else ""
                lines.append(f"· {it['desc'] or it['key']}：{it['value']}{rng_text}   [key: {it['key']}]")
            return "\n".join(lines)

        if tool_name == "query_audit_trail":
            if not result["items"]:
                return f"模块「{result['module']}」下暂无审计记录。"
            lines = [f"审计日志（模块：{result['module']}，共 {result['total']} 条）："]
            for i in result["items"][:8]:
                lines.append(
                    f"· {i['created_at']}｜{i['module']}/{i['action']}｜{i['operator']}"
                    f"｜业务 {i['biz_id'] or '-'}｜{i['status']}"
                )
            return "\n".join(lines)

        if tool_name == "update_store_setting":
            if not result["changed"]:
                return f"「{result['desc'] or result['setting_key']}」当前值就是 {result['new_value']}，无需修改。"
            return (f"门店配置已更新：\n"
                    f"· {result['desc'] or result['setting_key']}\n"
                    f"· {result['old_value']} → {result['new_value']}")

        if tool_name == "toggle_user_status":
            return (f"账号「{result['username']}」（{result.get('real_name') or '-'}，{result['role']}）"
                    f"已由「{result['from_status']}」变为「{result['to_status']}」。")

        if tool_name == "run_sla_scan":
            return f"SLA 巡检已执行，结果：{json.dumps(result, ensure_ascii=False)[:400]}"

        if tool_name == "query_boarding_options":
            elig = result.get("eligibility") or {}
            lines = [f"{result['check_in']} → {result['check_out']}（{result['nights']} 晚）"]
            if elig:
                lines.append(("✅ " if elig.get("ok") else "⚠️ ") + str(elig.get("message") or ""))
            rooms = [r for r in result.get("rooms", []) if r.get("available")]
            if rooms:
                lines.append("可订宠舍：")
                for r in rooms[:5]:
                    lines.append(f"· {r['name']}（{r['room_no']}，约 ¥{r['est_daily']:.0f}/晚）")
                    break
                if len(rooms) > 1:
                    lines.append(f"…共 {len(rooms)} 间可订")
            else:
                lines.append("这几天没有可订的宠舍，换个日期试试？")
            return "\n".join(lines)

        if tool_name == "query_goods":
            items = result.get("items") or []
            if not items:
                return "没找到相关用品，换个关键词试试？🐾"
            lines = [f"找到 {result['total']} 件用品" + (f"（已按「{result['pet_name']}」的档案标记安全性）" if result.get("pet_name") else "") + "："]
            for i in items[:5]:
                flag = "⚠️ 不适合" if i.get("unsafe") else ""
                lines.append(f"· {i['name']}　¥{i.get('price')}　库存 {i.get('total_stock')} {flag}".rstrip())
            lines.append("想买哪件告诉我，我帮你加购物车。")
            return "\n".join(lines)

        if tool_name == "create_pet_profile":
            extra = []
            if result.get("species"):
                extra.append(PET_SPECIES_LABEL.get(result["species"], result["species"]))
            if result.get("gender"):
                extra.append(PET_GENDER_LABEL.get(result["gender"], result["gender"]))
            if result.get("breed"):
                extra.append(str(result["breed"]))
            if result.get("birthday"):
                extra.append(f"生日 {result['birthday']}")
            if result.get("weight"):
                extra.append(f"{result['weight']}kg")
            if result.get("allergy"):
                extra.append("已记录过敏史")
            tail = f"（{'，'.join(extra)}）" if extra else ""
            return (f"档案建好啦：「{result['name']}」{tail} 🐾\n"
                    "接下来可以让我帮它预约洗护，或者补全疫苗驱虫记录。")

        if tool_name == "create_boarding_order":
            return (
                f"寄养申请已提交 🏠\n"
                f"· 单号：{result['order_no']}\n"
                f"· 毛孩子：{result['pet_name']}\n"
                f"· 宠舍：{result['room_name']}（{result['room_no']}）\n"
                f"· 时间：{result['check_in_date']} → {result['check_out_date']}（{result['nights']} 晚）\n"
                f"· 预估：¥{result['total_amount']:.2f}\n"
                f"· 接送：{result['dropoff_label']} / {result['pickup_back_label']}\n"
                f"状态：{result['status_label']}，门店确认后会推送消息给你。"
            )

        if tool_name == "add_goods_to_cart":
            lines = [f"已加入购物车：{result['product_name']}（{result['spec_name']}）×{result['quantity']}，¥{result['price']}"]
            if result.get("warnings"):
                lines.append("⚠️ 注意：" + "；".join(result["warnings"]))
            lines.append(f"购物车现有 {result['cart_count']} 件，合计 ¥{result['cart_total']}。说「提交订单」我就帮你结算。")
            return "\n".join(lines)

        if tool_name == "submit_goods_order":
            method = "到店自提" if result.get("pickup_method") == "self" else "门店配送"
            return (
                f"用品订单已提交 🛒\n"
                f"· 单号：{result['order_no']}\n"
                f"· 共 {result['item_count']} 件，合计 ¥{result['total_amount']:.2f}"
                + (f"（含配送费 ¥{result['delivery_fee']:.2f}）" if result.get("delivery_fee") else "") + "\n"
                f"· 取货方式：{method}\n"
                f"· 核销码：{result['pickup_code']}（到店出示）"
            )

        return "操作已完成 🐾"


__all__ = ["AgentRunner", "READ_INTENTS", "WRITE_INTENTS", "APPOINTMENT_STATUS_LABEL"]
