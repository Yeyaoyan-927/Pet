"""领域 Agent 定义与路由分派（多 Agent 协作层）。

设计口径：**一套执行内核 + 八份领域配置**。
- 8 个 Agent 共用同一个 `AgentRunner`、工具注册表、SSE 协议与确认闸门；
- 每个 Agent 只声明「负责哪些工具 / 哪些知识域 / 哪些端可激活 / 对外怎么介绍」；
- 路由 Agent 按意图查表分派，子 Agent 之间不直接对话（跨域协同由路由层显式编排）。

**权限边界不变**：本模块只决定「这轮回答属于哪个领域、由谁对用户自我介绍」，
真正的工具执行闸门仍是 `registry.can_invoke()`（角色白名单 + `ROLE_TOOL_PROFILE` 画像）。
换句话说，Agent 归属是**编排与可观测层**，不是第二套权限系统——避免两处判定漂移。

本模块只放数据与纯函数，不导入 AgentRunner / 业务服务，避免循环依赖。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentDefinition:
    """一个领域 Agent 的静态定义（数据，不含执行逻辑）。"""

    key: str
    name: str
    summary: str
    intents: tuple[str, ...]
    roles: tuple[str, ...]
    knowledge_domains: tuple[str, ...] = ()

    def view(self) -> dict[str, str]:
        """给前端 / capabilities 用的轻量视图。"""
        return {"key": self.key, "name": self.name, "summary": self.summary}


# ---------------------------------------------------------------- 八个 Agent
AGENT_ROUTER = AgentDefinition(
    key="router",
    name="路由调度 Agent",
    summary="判定意图、分派给领域 Agent、合并多域结果；闲聊与导航也由它直接处理",
    intents=(),
    roles=("customer", "staff", "manager"),
)

AGENT_HEALTH = AgentDefinition(
    key="health",
    name="健康问诊 Agent",
    summary="症状预问诊、疾病与急症类知识检索、风险等级查询；不诊断、不开处方",
    intents=("query_risk_report", "confirm_risk", "search_knowledge"),
    roles=("customer", "staff"),
    knowledge_domains=("disease",),
)

AGENT_NUTRITION = AgentDefinition(
    key="nutrition",
    name="饲养营养 Agent",
    summary="喂食量与频次、粮与罐头选择、换粮过渡、营养品是否需要补",
    intents=(),
    roles=("customer", "staff"),
    knowledge_domains=("nutrition",),
)

AGENT_BEHAVIOR = AgentDefinition(
    key="behavior",
    name="行为训练 Agent",
    summary="拆家、吠叫、护食、乱尿、应激的成因分析与正向训练方案，拒绝体罚",
    intents=(),
    roles=("customer", "staff"),
    knowledge_domains=("behavior",),
)

AGENT_SHOPPING = AgentDefinition(
    key="shopping",
    name="用品导购 Agent",
    summary="按品种 / 年龄 / 痛点匹配用品，给选型标准与避坑点，不硬推品牌",
    intents=("query_goods", "add_goods_to_cart", "submit_goods_order"),
    roles=("customer",),
    knowledge_domains=("goods",),
)

AGENT_PROFILE = AgentDefinition(
    key="profile",
    name="宠物档案 Agent",
    summary="宠物档案与洗护历史查询、建档；疫苗驱虫到期提醒由定时任务承担，不在此 Agent",
    intents=("query_pet_profile", "create_pet_profile", "query_customer_pets", "query_wash_history"),
    roles=("customer", "staff"),
)

AGENT_STORE = AgentDefinition(
    key="store",
    name="门店业务 Agent",
    summary="查时段、预约与改期取消、寄养下单、订单推进与排期查看",
    intents=(
        "query_slots",
        "query_my_appointments",
        "create_appointment",
        "cancel_appointment",
        "reschedule_appointment",
        "query_day_schedule",
        "advance_appointment",
        "create_appointment_for_customer",
        "query_boarding_options",
        "create_boarding_order",
    ),
    roles=("customer", "staff", "manager"),
)

AGENT_OPERATIONS = AgentDefinition(
    key="operations",
    name="经营分析 Agent",
    summary="经营指标、时段饱和度、流失预警、员工业绩、审计与门店配置",
    intents=(
        "query_report_summary",
        "query_capacity_analysis",
        "query_churn_list",
        "query_staff_performance",
        "query_store_settings",
        "update_store_setting",
        "toggle_user_status",
        "run_sla_scan",
        "query_audit_trail",
        "query_todo",
    ),
    roles=("staff", "manager"),
)

AGENT_COMPLIANCE = AgentDefinition(
    key="compliance",
    name="合规风控 Agent",
    summary="横切所有回答出口：急症置顶就医提示、诊断与剂量追加免责、有毒食物推荐直接拦截",
    intents=(),
    roles=("customer", "staff", "manager"),
)

AGENTS: tuple[AgentDefinition, ...] = (
    AGENT_ROUTER,
    AGENT_HEALTH,
    AGENT_NUTRITION,
    AGENT_BEHAVIOR,
    AGENT_SHOPPING,
    AGENT_PROFILE,
    AGENT_STORE,
    AGENT_OPERATIONS,
    AGENT_COMPLIANCE,
)

AGENT_MAP: dict[str, AgentDefinition] = {a.key: a for a in AGENTS}

# ---------------------------------------------------------------- 工具 → Agent
# 每个工具唯一主归属；`search_knowledge` 的归属会在运行时按知识域细分。
TOOL_AGENT: dict[str, str] = {
    # 门店业务
    "query_slots": "store",
    "query_my_appointments": "store",
    "create_appointment": "store",
    "cancel_appointment": "store",
    "reschedule_appointment": "store",
    "query_day_schedule": "store",
    "advance_appointment": "store",
    "create_appointment_for_customer": "store",
    "query_boarding_options": "store",
    "create_boarding_order": "store",
    # 用品导购
    "query_goods": "shopping",
    "add_goods_to_cart": "shopping",
    "submit_goods_order": "shopping",
    # 档案复诊
    "query_pet_profile": "profile",
    "create_pet_profile": "profile",
    "query_customer_pets": "profile",
    "query_wash_history": "profile",
    # 健康问诊
    "query_risk_report": "health",
    "confirm_risk": "health",
    # 经营分析
    "query_report_summary": "operations",
    "query_capacity_analysis": "operations",
    "query_churn_list": "operations",
    "query_staff_performance": "operations",
    "query_store_settings": "operations",
    "update_store_setting": "operations",
    "toggle_user_status": "operations",
    "run_sla_scan": "operations",
    "query_audit_trail": "operations",
    "query_todo": "operations",
    # 知识检索：默认健康域，运行时按关键词细分到营养 / 行为
    "search_knowledge": "health",
}

# ---------------------------------------------------------------- 知识域判定
# 只用于「这轮问答属于哪个领域 Agent」，不影响执行路径与工具选择。
# 顺序即优先级：疾病 / 急症信号永远先判，避免「狗吃了巧克力怎么办」被当成喂养问题。
_DOMAIN_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "disease",
        ("呕吐", "拉稀", "腹泻", "便血", "发烧", "发热", "咳嗽", "抽搐", "中毒", "巧克力",
         "葡萄", "洋葱", "老鼠药", "皮肤", "掉毛", "癣", "耳螨", "眼睛", "尿血", "尿不出",
         "不吃饭", "没精神", "疫苗", "驱虫", "洗澡", "绝育", "伤口", "瘸", "喘", "急救"),
    ),
    (
        "nutrition",
        ("粮", "喂", "罐头", "营养", "换粮", "生骨肉", "熟自制", "零食", "益生菌",
         "鱼油", "软骨素", "补钙", "奶粉", "辅食", "挑食", "长胖", "饮水", "吃多少"),
    ),
    (
        "behavior",
        ("拆家", "乱叫", "吠", "护食", "乱尿", "乱拉", "应激", "焦虑", "训练", "扑人",
         "怕人", "分离", "定点", "社会化", "咬人", "追尾", "打滚"),
    ),
    (
        "goods",
        ("猫砂", "砂盆", "猫抓板", "牵引", "笼子", "航空箱", "尿垫", "喂食器", "饮水机",
         "项圈", "玩具", "窝", "尺寸", "选哪个", "推荐"),
    ),
)

# 知识域 → Agent（`search_knowledge` 命中哪个域就由哪个 Agent 出面）
DOMAIN_AGENT: dict[str, str] = {
    "disease": "health",
    "nutrition": "nutrition",
    "behavior": "behavior",
    "goods": "shopping",
    "care": "health",
    "store": "profile",
}


def detect_knowledge_domain(text: str) -> str:
    """按关键词判定知识问答属于哪个领域，默认疾病域。"""
    content = text or ""
    for domain, keywords in _DOMAIN_KEYWORDS:
        if any(word in content for word in keywords):
            return domain
    return "disease"


def resolve_agent(intent: str, text: str = "") -> AgentDefinition:
    """意图 → 负责的 Agent。

    规则：闲聊 / 导航归路由 Agent；知识检索按领域细分；其余查工具归属表。
    查不到就退回路由 Agent（不冒充某个领域，避免给用户错误预期）。
    """
    if intent in ("smalltalk", "open_camera", ""):
        return AGENT_ROUTER
    if intent == "search_knowledge":
        return AGENT_MAP[DOMAIN_AGENT.get(detect_knowledge_domain(text), "health")]
    return AGENT_MAP.get(TOOL_AGENT.get(intent, ""), AGENT_ROUTER)


def agents_for_role(role: str) -> tuple[AgentDefinition, ...]:
    """当前端可激活的 Agent（路由与风控对所有端恒在）。"""
    return tuple(a for a in AGENTS if role in a.roles)


def agent_manifest(role: str) -> list[dict[str, str]]:
    """给 capabilities 的 Agent 清单。"""
    return [a.view() for a in agents_for_role(role)]
