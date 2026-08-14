"""角色工具画像（Role Tool Profile）。

设计原则：**一个 Agent 内核，三套工具画像**。
- 工具池可以增长，但**单个角色可见的工具必须收敛**（宠主 ≤14 / 店员、店长 ≤11），
  否则会显著拉低 LLM 的工具选择准确率，也会让提示词过长。
  V8.3 加 `search_knowledge` 后宠主为 13 个，实测意图评测仍 42/42，暂不继续扩张。
- `can_invoke()` 采用「角色白名单 + 画像收敛」双重判定：
  角色允许 ≠ 可调用，还必须在自己的画像里。

本模块**只放数据，不导入任何业务模块**，避免循环依赖。
"""
from __future__ import annotations

# ---------------------------------------------------------------- 角色画像
CUSTOMER_TOOLS: tuple[str, ...] = (
    # 洗护预约
    "query_slots",
    "query_pet_profile",
    "query_my_appointments",
    "query_risk_report",
    "create_appointment",
    "cancel_appointment",
    # 档案：只要名字就能建（V8.2）
    "create_pet_profile",
    # 宠物之家：寄养（查资格/房型 + 下单）与用品（查商品 / 加购 / 下单）
    "query_boarding_options",
    "create_boarding_order",
    "query_goods",
    "add_goods_to_cart",
    "submit_goods_order",
    # 洗护安全规范检索（RAG，V8.3）
    "search_knowledge",
)

STAFF_TOOLS: tuple[str, ...] = (
    # 只读
    "query_day_schedule",
    "query_todo",
    "query_customer_pets",
    "query_wash_history",
    "query_risk_report",
    "query_report_summary",
    # 受控写
    "advance_appointment",
    "confirm_risk",
    "create_appointment_for_customer",
    "reschedule_appointment",
    # 洗护安全规范检索（RAG，V8.3）
    "search_knowledge",
)

MANAGER_TOOLS: tuple[str, ...] = (
    # 只读
    "query_report_summary",
    "query_capacity_analysis",
    "query_churn_list",
    "query_staff_performance",
    "query_store_settings",
    "query_todo",
    # 店长专属只读
    "query_audit_trail",
    # 受控写 / 运维
    "update_store_setting",
    "toggle_user_status",
    "run_sla_scan",
    # 洗护安全规范检索（RAG，V8.3）
    "search_knowledge",
)

ROLE_TOOL_PROFILE: dict[str, tuple[str, ...]] = {
    "customer": CUSTOMER_TOOLS,
    "staff": STAFF_TOOLS,
    "manager": MANAGER_TOOLS,
}

# 角色画像的对外名称，用于前端展示与 capabilities 返回
ROLE_PROFILE_NAME: dict[str, str] = {
    "customer": "宠主自助助手",
    "staff": "店员运营助理",
    "manager": "店长经营助理",
}

# ---------------------------------------------------------------- 角色语境提示
# 会被拼进意图识别的 system prompt，让模型理解该角色在门店里的位置与说话方式。
ROLE_PROMPT_HINT: dict[str, str] = {
    "customer": (
        "当前用户是【宠主】。他只关心自己名下的宠物与预约；\n"
        "涉及手机号等隐私一律按脱敏展示；\n"
        "不要主动给出门店经营数据，也不要暴露其他客户的信息。"
    ),
    "staff": (
        "当前用户是【店员】，负责门店现场运营。\n"
        "默认按「归属我的预约 / 我今天要处理的单」理解他的问题；只有明确说「全部」「所有人的」时才放开范围。\n"
        "客户档案不受归属限制：任何店员都能查改任意客户档案，不要回答「不是你的客户」。\n"
        "涉及宠主隐私（手机号）自动脱敏；推进订单状态前必须复述单号 + 宠物名 + 目标状态并要求确认。"
    ),
    "manager": (
        "当前用户是【店长】，关心门店整体经营。\n"
        "回答经营类问题**必须带上统计区间与统计口径**（例如「近 30 天，口径为已确认及以上状态的预约」）。\n"
        "他有权查看审计日志与门店配置；配置类写操作必须先说明「当前值 → 新值」并要求确认。\n"
        "数据异常时给出可执行建议，而不是只罗列数字。"
    ),
}

# ---------------------------------------------------------------- 角色示例问题
ROLE_EXAMPLES: dict[str, list[str]] = {
    "customer": [
        "明天还有哪些时段可以预约？",
        "帮我看看豆豆的档案",
        "我最近的预约到哪一步了？",
        "帮我给豆豆预约明天 15:00 洗澡",
        "取消预约 PG20261014123456",
    ],
    "staff": [
        "我今天有什么要处理的？",
        "明天门店排了多少单，哪个时段比较空？",
        "帮我查一下客户 13812345678 的宠物档案",
        "豆豆上次洗护有什么异常吗？",
        "PG20261014123456 这单确认一下",
        "帮我给客户预约明天 15:00 洗澡",
    ],
    "manager": [
        "近 30 天经营情况怎么样？",
        "这周哪个时段还有空可以加单？",
        "有哪些客户该回访了？",
        "看看这个月店员的工作量对比",
        "最近谁改过门店配置？",
        "把流失预警天数从 90 改成 60",
    ],
}

# ---------------------------------------------------------------- 工具分工说明
# 用于生成 capabilities 里的引导文案，帮助用户知道「这个角色能问什么」
ROLE_CAPABILITY_SUMMARY: dict[str, str] = {
    "customer": "查时段、看档案、管预约、了解洗护风险与安全规范",
    "staff": "处理今日待办、查客户与洗护历史、推进订单状态、风险复核、代客预约、查洗护规范",
    "manager": "看经营数据、查时段饱和度与流失预警、对比员工业绩、查审计与配置、查洗护规范",
}
