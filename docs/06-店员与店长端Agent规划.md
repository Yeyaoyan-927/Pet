# 店员端 / 店长端 Agent 规划（V5 · 已交付）

> **交付状态：已实现并验证** —— 后端冒烟 261/261、浏览器端到端 123/123、类型检查与构建通过。
> 关键实现落点：`app/agent/tools/profiles.py`（三端激活组合）、`app/agent/tools/registry.py`（30 个工具）、
> `app/agent/react.py`（角色化路由与闸门）、`app/agent/llm/prompts.py`（领域提示词）、
> `frontend/src/views/chat/index.vue`（三角色共用对话组件）。

> **目标**：把多 Agent 协作能力从「宠主自助」扩展到「店员日常运营」与「店长经营管理」，
> 让三个端共用同一套 Agent 定义与同一个执行内核，只在**可激活 Agent 与工具白名单**上分化。
> **架构约束不变**：路由调度 + 领域子 Agent 分工；RAG 作统一知识底座（对话内检索）；
> 业务闭环用**状态机 / Graph Workflow**；Agent 之间不自由协商；**写操作绝不交由 LLM 直接执行**。

---

## 一、现状差距分析（先看清缺什么）

| 能力 | 现状 | 差距 |
|---|---|---|
| 对话后端链路 | `POST /api/v1/chat/message`（SSE）**对三角色已通用** | ✅ 无需改动核心 |
| 工具注册表 | V5 改造前只有 8 个工具，`@tool(..., staff_only=True)` 仅能拦宠主 | ❌ 缺 `manager_only`，缺店员/店长专属工具 |
| 角色过滤 | `can_invoke()` 只判断「是否宠主」 | ❌ 无法表达「店员可见、店长可见、宠主不可见」三态 |
| 提示词 | 只有一份 `INTENT_SYSTEM_PROMPT`（面向宠主） | ❌ 店员/店长说「今天忙不忙」时缺少运营语境 |
| 前端入口 | 仅 `/user/chat`，菜单按 `roles: ['customer']` 隐藏 | ❌ 店员/店长完全没有对话入口 |
| 测试 | 冒烟用例覆盖宠主对话 | ❌ 无店员/店长角色用例 |

**结论**：这不是「再造两套 Agent」，而是**给同一套 Agent 定义配上三端的激活组合**。后端核心改动量约占 20%，其余是工具、领域提示词、前端与测试。

---

## 二、设计原则

1. **一套 Agent 定义，三套激活组合**：路由调度、领域子 Agent、合规风控的定义全局唯一；
   三端只在「哪些 Agent 可激活 + Agent 内工具白名单」上不同（`ROLE_TOOL_PROFILE`）。
2. **每端工具数收敛到 11~13**：工具过多会显著拉低 LLM 的工具选择准确率。全量工具可增长，但**单端画像必须收敛**。
3. **读多写少**：店员/店长的价值主要在「聚合查询与批量处理」，写操作一律走确认闸门。
4. **越权双重拦截**：`capabilities` 接口按角色过滤一次，工具执行前 `can_invoke` 再拦一次。
5. **手机号可见性延续现有规则**：店员只见脱敏，店长可见原始号码（复用 `phone_for`）。

---

## 三、工具画像设计

### 3.1 宠主端（现状，8 个，保持不变）

`query_slots` · `query_pet_profile` · `query_my_appointments` · `query_risk_report` ·
`query_report_summary`(staff_only) · `create_appointment` · `cancel_appointment` · `reschedule_appointment`

> 注：`query_report_summary` 与 `reschedule_appointment` 对宠主不可见，宠主实际可见 6 个。

### 3.2 店员端（10 个：6 新增 + 1 复用 + 3 新增写）

| # | 工具 | 类型 | 用途 | 底层服务 |
|---|---|---|---|---|
| 1 | `query_day_schedule` | 只读 🆕 | 「明天几点比较空 / 今天排了多少单」→ 排期与容量 | `schedule_service.load_by_date` |
| 2 | `query_todo` | 只读 🆕 | 「我今天有什么要处理的」→ 待确认 / 待复核风险 / 待到店汇总 | `appointment_service` + `risk_service` |
| 3 | `query_customer_pets` | 只读 🆕 | 按手机号 / 宠主名 / 宠物名查客户档案（店员可见全部，含风险标记） | `pet_service` |
| 4 | `query_wash_history` | 只读 🆕 | 某宠物历史洗护记录（现场沟通用：上次皮肤状况、用了什么产品） | `wash_service` |
| 5 | `query_risk_report` | 只读 ♻️ | 查某笔预约的风险报告 | `risk_service` |
| 6 | `advance_appointment` | 受控写 🆕 | 「确认这单 / 王小明的狗到了 / 洗完了」→ 推进状态机 | `appointment_service.change_status` |
| 7 | `confirm_risk` | 受控写 🆕 | 风险复核确认 + 记录处置措施 | `risk_service.confirm` |
| 8 | `create_appointment_for_customer` | 受控写 🆕 | 代客预约（手机号不存在自动建临时客户） | `appointment_service.create_by_staff` |
| 9 | `reschedule_appointment` | 受控写 ♻️ | 改期 | `appointment_service.reschedule` |
| 10 | `query_report_summary` | 只读 ♻️ | 门店经营概览（与前端报表权限保持一致） | `stats_service.summary` |

> 原规划的 `query_shift_brief` 已合并进第 2 项 `query_todo`，其返回值含 `shift_brief` 字段。

**店员端提示词要点**：默认视角是「我的客户 + 归属我的预约」，除非明确说「全部」；
涉及宠主隐私（手机号）自动脱敏；写操作前必须复述单号 + 宠物名 + 时间。

### 3.3 店长端（10 个：6 新增 + 1 复用 + 3 新增写）

| # | 工具 | 类型 | 用途 | 底层服务 |
|---|---|---|---|---|
| 1 | `query_report_summary` | 只读 ♻️ | 经营概览（订单量 / 爽约率 / 复购率） | `stats_service.summary` |
| 2 | `query_capacity_analysis` | 只读 🆕 | 「这周哪个时段还有空可以加单」→ 时段饱和度分析 | `schedule_service.week_schedule` |
| 3 | `query_churn_list` | 只读 🆕 | 流失预警名单（超过 `churn_days` 未洗护） | `stats_service.churn` |
| 4 | `query_staff_performance` | 只读 🆕 | 员工业绩对比（完成单数 / 负载） | `stats_service.staff_workload` + `schedule_service.staff_load` |
| 5 | `query_audit_trail` | 只读 🆕 | 审计日志查询（**manager_only**） | `operation_log` |
| 6 | `query_store_settings` | 只读 🆕 | 当前门店参数（容量 / SLA 时限 / 流失天数） | `setting_service.list_settings` |
| 7 | `query_todo` | 只读 ♻️ | 门店级待办（全局视角，不限归属） | 同店员端，去掉 `mine` 过滤 |
| 8 | `update_store_setting` | 受控写 🆕 | 改配置（**manager_only**，范围校验 + 二次确认） | `setting_service.update_setting` |
| 9 | `toggle_user_status` | 受控写 🆕 | 启用 / 禁用员工账号（**manager_only**） | `auth_service` / `user` 服务 |
| 10 | `run_sla_scan` | 受控写 🆕 | 手动触发 SLA 巡检（为 V6 arq 定时任务预留入口） | `appointment_service.sla_scan` |

**店长端提示词要点**：回答经营问题必须带**区间与口径**（如「近 30 天，口径为已确认及以上」）；
配置类写操作必须先念出「当前值 → 新值」并要求确认；审计查询结果默认脱敏。

### 3.4 三端 Agent 激活总览

| 端 | 可见工具数 | 侧重 Agent |
|---|---|---|
| 宠主 customer | 13 | 健康问诊 / 饲养营养 / 行为训练 / 用品导购 / 宠物档案 / 门店业务 / 风控（8 个可激活） |
| 店员 staff | 11 | 门店业务 / 宠物档案 / 健康问诊（预问诊辅助）/ 经营分析 / 风控（8 个可激活） |
| 店长 manager | 11 | 门店业务 / 经营分析 / 风控（4 个可激活：路由 + 3 个领域） |
| **工具池总量** | **30**（全部按 Agent 归组，三端各取子集） | 共 **9 个 Agent**：1 路由 + 7 领域 + 1 风控 |

三端共用的部分：路由调度 Agent、ReAct 执行内核、SSE 事件协议、确认闸门、幂等键规范、会话存储。
三端分化的部分：可激活的 Agent、Agent 内工具白名单、领域提示词。
完整的三端可见性矩阵见 [`03-Agent架构设计.md`](03-Agent架构设计.md) 第五节。

**实现期对原规划的两处调整（已在代码中落地）：**

1. **`query_shift_brief` 合并进 `query_todo`**：两者高度重合（都是"我该处理什么"），
   合并后 `query_todo` 同时返回待办清单与交班简报，腾出的画像名额留给 `query_report_summary`。
2. **`query_report_summary` 纳入店员画像**：前端 `/report/summary` 本就对店员开放，
   若 Agent 侧禁止会造成「同一份数据两个入口权限不一致」。

---

## 四、代码改动清单

### 4.1 后端

| 文件 | 改动 | 说明 |
|---|---|---|
| `app/agent/tools/registry.py` | 改 | `@tool` 增加 `roles: list[str] \| None` 参数；`can_invoke()` 改为角色白名单判定；新增 11 个工具函数 |
| `app/agent/tools/profiles.py` | 新增 | `ROLE_TOOL_PROFILE: dict[str, list[str]]`（角色 → 工具名白名单）+ `ROLE_PROMPT_HINT` |
| `app/agent/llm/prompts.py` | 改 | 新增 `STAFF_OPERATION_PROMPT` / `MANAGER_OPERATION_PROMPT`；`INTENT_SYSTEM_PROMPT` 增加角色槽位说明 |
| `app/agent/react.py` | 改 | `_interpret()` 按角色注入工具清单与角色提示；`_ask_for_missing` / `_confirm_prompt` / `_format_answer` 补新工具文案分支 |
| `app/routers/chat.py` | 改 | `capabilities` 返回角色化工具清单与角色示例问题；新增 `GET /chat/tool-profile`（调试用，仅店长） |
| `app/services/*` | 改 | `pet_service.list_pets` 增加按手机号 / 宠主名搜索；`operation_log` 增加查询服务方法 |

**权限模型升级（已实现）**：

```python
@tool("advance_appointment", "...", write=True, roles=(UserRole.STAFF.value, UserRole.MANAGER.value))
def advance_appointment(ctx, order_no: str, target_status: str, reason: str | None = None): ...

def can_invoke(name: str, user: User) -> bool:
    meta = TOOLS.get(name)
    if meta is None:
        return False
    allowed = meta.get("roles")            # None = 三角色皆可
    if allowed is not None and user.role not in allowed:
        return False
    return name in ROLE_TOOL_PROFILE.get(user.role, ())   # 画像收敛
```

**实现期发现并修复的两个关键缺陷（都是"写安全"级别）：**

1. **写意图硬编码导致新工具绕过确认闸门**：`advance_appointment` 初期直接改库、未走二次确认。
   已改为 `WRITE_INTENTS = set(WRITE_TOOLS)` **从注册表派生** —— 今后任何 `write=True` 的新工具
   都会自动进入闸门，不可能因忘记维护列表而绕过。
2. **工具入参透传导致 TypeError**：LLM 给出的槽位可能超出工具实际声明（如"今天要处理什么"带上日期），
   直接 `**kwargs` 传入会 500。已改为**按处理函数签名过滤入参**（`@tool` 登记时用 `inspect` 记录参数名）。

### 4.2 前端

| 文件 | 改动 |
|---|---|
| `src/views/staff/Chat.vue` | 新增（或抽公共 `src/views/chat/Index.vue` 按 `userStore.role` 渲染） |
| `src/views/manager/Chat.vue` | 新增（复用同一组件，仅提示词与示例不同） |
| `src/router/index.ts` | 新增 `/staff/chat`（roles: staff/manager）—— 计划中的 `/manager/chat` 已并入该页 |
| `src/utils/dict.ts` | `MENU_META` 补「运营助理」；`TOOL_LABEL` 补 11 个新工具中文名 |
| `src/api/chat.ts` | 无需改动（接口已通用） |

> **实际实现**：已抽成单一组件 `views/chat/index.vue`，`/user/chat` 与 `/staff/chat` 两个路由共用同一组件；
> 欢迎语、示例问题、输入框提示与工具标签全部由 `capabilities` 与角色决定，不存在重复代码。
>
> **交付期的一处调整**：原计划的 `/manager/chat` 已**取消菜单入口**。原因是它与 `/staff/chat`
> 对店长而言完全等价（同一组件 + 后端按角色下发同一套经营画像），单列只会造成「两个入口、一个功能」。
> 店长从「门店运营 → 运营助理（末位）」进入，页面自动呈现「店长经营助理」。
> 旧链接保留一条重定向，避免外部收藏 404。

### 4.3 测试

| 用例 | 断言 |
|---|---|
| 店员 `capabilities` | 返回 10 个工具；不含 `query_audit_trail` / `update_store_setting` |
| 店长 `capabilities` | 返回 10 个工具；含 `query_audit_trail` / `update_store_setting` |
| 宠主请求店员工具 | SSE 返回友好拒绝，`action` 事件不出现 |
| 店员推进状态（`advance_appointment`） | 先出 `confirm` 事件；未确认前订单状态不变 |
| 确认后推进状态 | 状态真实变更，且 `operation_log` 有对应记录 |
| 店长改配置越界 | 返回友好错误，配置值不变 |
| 店长改配置合法 | 配置生效，`data_type` 与范围校验通过 |
| 店员查审计日志 | 无该工具 → 友好拒绝 |
| 店员查客户档案的手机号 | 返回脱敏值（`138****1111`） |
| 店长查同一客户档案 | 可见原始号码，且写审计日志 |

---

## 五、风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 工具数量膨胀导致 LLM 选错工具 | 答非所问、误调工具 | 画像收敛（宠主 12 / 店员 10 / 店长 10）；`can_invoke` 拒绝画像外工具；提示词只注入当前角色工具清单 |
| 店员批量操作误改数据 | 订单状态错乱 | 写操作强制二次确认 + 复述关键字段；全部落审计日志 |
| 店长改配置写入非法值 | 业务逻辑错乱 | 复用 `setting_service` 的类型 + 范围校验，非法值拒绝并回退默认 |
| 手机号越权可见 | 隐私泄露 | 沿用 `phone_for()`：默认脱敏，仅店长可见原始；导出与查看均记审计 |
| 角色提示词串味（店员答经营问题） | 体验混乱 | 每角色独立提示词 + 独立的 `capabilities` 示例问题 |
| 与 V6 定时任务职责重复 | 双入口不一致 | `run_sla_scan` 只做「手动触发」，真正的定时由 V6 arq 承担，两者调用同一服务方法 |

---

## 六、工作量与版本归属

| 工作项 | 预估 |
|---|---|
| 权限模型升级 + `profiles.py` + 11 个工具实现 | 1.5 天 |
| 角色提示词 + `react.py` 文案分支 | 1 天 |
| `capabilities` 角色化 + 新增查询服务方法 | 0.5 天 |
| 前端对话页抽公共组件 + 路由菜单 | 1 天 |
| 冒烟用例 10 项 + 浏览器端到端补充 | 1 天 |
| **合计** | **约 5 人日** |

**版本归属：V5（多角色 Agent 扩展）**。
原「测试与交付验收」顺延为 **V6** —— 功能扩展必须在测试与交付之前完成。

---

## 七、验收标准

- [x] 三角色 `capabilities` 各自返回正确的工具清单（12 / 10 / 10），且互不越权
- [ ] 店员可通过对话完成「确认预约 → 到店 → 开始洗护 → 完成」全流程（每步二次确认）
- [ ] 店长可通过对话查询经营数据，回答必须带区间与口径
- [ ] 店长改门店配置走范围校验，非法值被拒绝
- [ ] 全部写操作在 `operation_log` 可追溯，且与表单入口结果一致（同一服务方法 + 同一幂等键规范）
- [ ] 新增冒烟用例 10 项全绿；浏览器端到端补充店员/店长对话交互用例
- [ ] `docs/02` UI 规范补充两个新页面的设计说明

---

## 八、与规划书的偏差说明

规划书原定「精简工具集」面向宠主自助场景。
本规划把工具池扩展到 30 个，但按 Agent 归组、按端收敛画像，保证单端 11~13 个，
既满足「精简」的初衷（对 LLM 而言始终是小工具集），又覆盖了店员与店长的真实运营诉求。

> 历史命名说明：规划书中的 V3.1-Final / V3.2 / V3.3 / V4.0 是另一套序列，
> 与本项目的 V1 → V8 序列（V5 已交付）不通用，勿混用。
