# Agent 对话与工具说明（V4 + V5 · 已交付）

> 本文件描述**已实现**的多 Agent 协作对话能力：路由调度 Agent 分派、领域子 Agent 执行、
> 合规风控 Agent 兜底，含 SSE 协议、30 个工具、Graph Workflow 闸门与前端交互。
> 架构约束见 [`03-Agent架构设计.md`](03-Agent架构设计.md)：**路由 + 领域子 Agent 分工，RAG 作统一知识底座，
> 业务闭环用状态机 / Graph Workflow，Agent 之间不自由协商**。

---

## 一、能力入口

| 入口 | 方法 | 说明 |
|---|---|---|
| `POST /api/v1/chat/message` | SSE | 发送消息，流式返回思考 / 工具调用 / 回答（支持 `session_id` 续聊，为空则使用当前活跃会话） |
| `GET /api/v1/chat/sessions` | 查询 | 会话列表（标题、轮次、最后消息预览） |
| `POST /api/v1/chat/sessions` | 新建 | 创建新会话 |
| `GET /api/v1/chat/sessions/{id}/messages` | 查询 | 会话历史（仅 user / assistant 角色） |
| `DELETE /api/v1/chat/sessions/{id}` | 逻辑删除 | 删除会话 |
| `GET /api/v1/chat/capabilities` | 查询 | 当前角色可用的工具清单、模型、架构声明、示例问题 |
| `GET /api/v1/chat/purge` | 运维 | 按 `session_retention_days` 物理清理超期会话（仅店长） |

前端页面：`/user/chat`（宠主端）。

---

## 二、SSE 事件协议

事件以 `data: {json}\n\n` 逐条推送，前端用 `fetch + ReadableStream` 消费（EventSource 不支持 POST 与自定义头）。

| `type` | 载荷 | 含义 |
|---|---|---|
| `meta` | `session_id`, `llm` | 流开始，回传会话 ID 与 LLM 可用性 |
| `thought` | `content` | 思考链（ReAct 的 Thought） |
| `intent` | `intent`, `slots`, `source` | 意图识别结果（`source` = `llm` / `rule`） |
| `action` | `tool`, `args` | 决定调用的工具与参数（ReAct 的 Action） |
| `observation` | `tool`, `ok`, `result` / `error` | 工具执行结果（ReAct 的 Observation） |
| `confirm` | `tool`, `args`, `prompt` | **写操作确认闸门**：需用户确认后才执行 |
| `navigate` | `path`, `label` | 跳转到某功能页（V8.4：实景直达；V8.4.9 带 `?order_id=`） |
| `choices` | `items[]` | 需要用户二选一时下发的**可点选项**（V8.4.9：多只宠物时选「看谁的实景」） |
| `camera_error` | `reason`, `order_id?` | 实景看不了时的**原因**（未装摄像头 / 已停用 / 订单不在可看状态），前端弹窗展示 |
| `refs` | `items[]`（标题 · 小节 / 正文 / 相关度 / 来源） | 知识问答的依据片段（V8.4.5），前端折叠展示 |
| `answer` | `delta` | 回答增量（逐字流式，前端拼接到气泡并显示闪烁光标） |
| `error` | `message` | 错误信息（SSE 不中断） |
| `done` | — | 本轮结束 |
| `end` | — | 流结束（服务端 finally 必定发送） |

---

## 三、Graph Workflow（显式流程骨架）

```
[START] 用户消息
   ↓ 落库 user 消息
[gate] 是否存在 pending_action？
   ├─ 是且消息是「确认」→ [execute] 执行待确认的写操作 → [reply]
   ├─ 是且消息是「放弃」→ 清空 pending → [reply]
   └─ 否 → 继续
   ↓
[intent] 意图识别（LLM 优先；LLM 不可用自动降级为规则匹配）
   ↓
├─ smalltalk ─────────────────────────→ [reply]
├─ 越权（staff_only 且角色为宠主）──────→ [reply 友好提示]
├─ 槽位缺失 ─────────────────────────→ [ask 追问缺失槽位]
├─ 只读意图 → [execute tool] → [reply]
└─ 写意图 → [precheck 只读预检] → [confirm 二次确认] → 等用户「确认」
                                └─ 预检失败 → [reply 友好拒绝]
```

**确认词判定纪律**：`is_confirm()` / `is_cancel()` 要求**整句就是这个意思**（正则整串匹配，且长度 ≤ 8），
避免把「明天还有哪些时段**可以**预约？」里的「可以」误判成确认。

**写操作预检**：取消 / 改期前先做**只读**校验（单号是否存在、是否归属当前用户、状态是否允许），
不通过就直接给出友好说明，避免让用户做无意义的二次确认。

---

## 三补、Agent 归属与三端可见性（V5）

三个端共用同一套 Agent 定义与同一个执行内核，差异体现在**哪些 Agent 可激活**与**Agent 内的工具白名单**。

| Agent | 宠主端 | 店员端 | 店长端 | 说明 |
|---|---|---|---|---|
| 路由调度 | ✅ | ✅ | ✅ | 意图判定与分派，三端共用 |
| 健康问诊 | ✅ 完整预问诊 | ✅ 预问诊辅助 | ❌ | 不诊断、不开处方 |
| 饲养营养 | ✅ | ✅ | ❌ | 喂食量 / 换粮 / 营养品 |
| 行为训练 | ✅ | ✅ | ❌ | 正向训练，拒绝体罚方案 |
| 用品导购 | ✅ 自家宠物 | ❌ | ❌ | 不硬推品牌 |
| 宠物档案 | ✅ 仅名下宠物 | ✅ 全量可读写 | ❌ | 长期记忆的唯一写入口 |
| 门店业务 | ✅ 预约/寄养/用品/实景 | ✅ 开单/核销/照护记录 | ✅ 含 SLA 处置 | 写操作走服务层 |
| 经营分析 | ❌ | ✅ 看板与统计 | ✅ 含审计与配置 | 店长专属能力最全 |
| 合规风控 | ✅ | ✅ | ✅ | 横切，有否决权 |

可激活数按端裁剪：宠主 8 个 / 店员 8 个 / 店长 4 个（路由 + 门店业务 + 经营分析 + 风控）。

| 角色 | 画像名称 | 可见工具数 | 侧重 Agent |
|---|---|---|---|
| customer | 宠主自助助手 | 13 | 健康问诊 / 营养 / 行为 / 导购 / 档案 / 门店业务 |
| staff | 店员运营助理 | 11 | 门店业务 / 宠物档案 / 健康问诊（辅助）/ 风控 |
| manager | 店长经营助理 | 11 | 经营分析 / 知识库治理 / SLA 处置 / 风控 |

**工具池 30 个，按端收敛为 13 / 11 / 11**：工具池可以增长，但给 LLM 看的清单必须收敛，
否则会显著拉低工具选择准确率、并让提示词过长。

**双重判定**：`can_invoke()` = 角色白名单（`@tool(roles=...)`）→ 画像收敛（`ROLE_TOOL_PROFILE`）。
即使 LLM 幻觉出一个「角色允许但不在画像内」的工具，也会被拒绝执行。

**执行内核三端完全共用**：`AgentRunner`、ReAct 循环、SSE 事件协议、确认闸门、幂等键规范、
会话存储全部不分角色；差异只体现在**可激活的 Agent、工具画像与领域提示词**上。

**写安全的关键设计**：`WRITE_INTENTS = set(WRITE_TOOLS)` **从工具注册表派生** ——
任何 `write=True` 的新工具都会自动进入二次确认闸门，不可能因忘记维护硬编码列表而绕过。

**入参安全**：`@tool` 登记时用 `inspect` 记录处理函数的参数名，
执行前按签名过滤槽位；LLM 给出工具不接受的参数（如问「今天要处理什么」时带上日期）会被静默剔除，
避免 `TypeError` 直接打断会话。

---

## 三补二、RAG 知识底座与定时任务（V6 → V8.5）

- **RAG 是所有 Agent 的统一知识底座**，检索在**对话链路内**由 Agent 自主触发（`search_knowledge` 工具），
  不设独立的知识检索页面。命中片段写入 `knowledge_refs`（**每条带 `matched` 命中原因**）并注入 LLM 提示词，
  同时以 `refs` 事件下发前端折叠展示——用户能点开看是哪篇文档的哪个小节。
- **知识库管理页只做文档治理**（店长）：上传、切块、查看任务状态、删除、重建索引；没有「搜索」页签。
- **定时任务**：`app/tasks` 内 5 个任务（SLA 巡检 / 疫苗临期 / 复购回访 / 会话清理 / 锁行清理），
  由进程内置调度器驱动、`task_run` 行锁保证多实例不重复执行；店长可 `GET /api/v1/tasks` 查看状态、
  `POST /api/v1/tasks/{name}/run` 手动补跑。详见 [`08-定时任务与知识库说明.md`](08-定时任务与知识库说明.md)。

---

## 四、工具集（30 个 · 只调用业务服务层）

### 4.1 V8.2 新增：宠主「宠物之家 + 档案」能力（6 个）

| 工具 | 类型 | 作用 | 落库路径 |
|---|---|---|---|
| `create_pet_profile` | 写 | 只要名字就能建档案，其余（品种/体重/生日/过敏）后补 | `pet_service.create_pet` |
| `query_boarding_options` | 读 | 一次返回寄养资格（疫苗）+ 房型 + 每日价格 | `boarding_service.eligibility` / `list_rooms` |
| `create_boarding_order` | 写 | 提交寄养申请；未指定房型时**自动选最便宜的可订房** | `boarding_service.create_order` |
| `query_goods` | 读 | 商品价格/库存/过敏与禁忌标记（可按宠物档案评估） | `goods_service.list_products` |
| `add_goods_to_cart` | 写 | 按商品名匹配规格并加购，命中过敏只提示不拦 | `goods_service.add_to_cart` |
| `submit_goods_order` | 写 | 把购物车提交为订单（自提/配送），返回核销码 | `goods_service.create_order` |

> **商品名匹配（V8.2.1）**：`query_goods` / `add_goods_to_cart` 与确认前预检共用 `search_products()`，
> 由严到宽四级回退：同名 → 双向包含 → 去括号主体 / 括号内口味 → 字符相似度（≥0.45）。
> 用户少写括号（「成猫全价主粮三文鱼」）或带动词（「帮我买…」）都能命中；
> 真找不到时直接列出**门店在售商品名**，而不是只回一句「没找到」。
>
> **知识检索（V8.3）**：`search_knowledge` 走 Chroma 向量检索（`knowledge_service.search_by_query`），
> 无必填槽位；给了 `pet_name` 会叠加档案关键词做个性化召回。只读工具，不进确认闸门，
> 向量库或 embedding 不可用时自动降级为标签匹配（见 docs/08）。
>
> **RAG 的两段式（V8.4.5）**：命中片段**交给模型生成回答**（`_compose_knowledge_answer`，
> 只依据片段、180 字内、不编造），片段本身通过 SSE `refs` 事件单独下发，前端在气泡下方
> 折叠展示（标题 · 小节 / 正文 / 相关度 / 来源），历史回看由 `tool_result` 还原。
> 模型不可用时退回模板摘要 —— 回答可以朴素，但不能没有回答。
>
> **建档案槽位（V8.2.1）**：`gender` / `species` 走 `normalize_gender()` / `normalize_species()` 归一化，
> 支持「母 / 雌 / 妹妹 / 女孩」等口语；认不出时**报错让用户补**，不会静默写成默认的「公」。
> 槽位白名单由工具签名派生（`ALL_SLOT_KEYS`），新增工具参数不需要再同步清单。

另有 **`open_camera` 特殊意图**（不是工具）：用户说「看看宠物状态 / 打开摄像头 / 在干嘛」时，
服务端直接下发 `navigate` 事件，前端跳到 `/user/camera`。规则命中即优先于 LLM，
避免被理解成「查预约进度」。

**V8.4.9 改为「先问看谁，再跳页面」**（宠主端）：

1. 只有 1 只可看的在住宠物 → 直接 `navigate /user/camera?order_id=<id>`；
2. 有多只 → 下发 `choices`（「看豆豆的实景」「看咪咪的实景」…），等宠主点选再跳；
   宠主也可以直接打字说宠物名，按名字匹配；
3. 看不了（宠舍未装摄像头 / 摄像头已停用 / 订单不在可看状态）→ 下发 `camera_error`，
   前端弹窗说明**具体原因**，不是甩一句「看不了」。

跳转落地在**宠物实景页**而不是聊天内弹窗 —— 实景页有完整的观看凭证、时长留痕与结束观看，
聊天里复刻一份必然与功能页不一致。落地页读 `?order_id=` 自动申请凭证并开播。

> 确认卡会复述关键字段：建档案给「名字 + 物种 + 体重 + 过敏史」；寄养给「宠舍 + 入住→离店 + 晚数 + 预估费用」；
> 加购给「商品 + 规格 + 数量」；下单给「件数 + 金额 + 取货方式」。确认前一律不落库。
> 寄养预检还会先跑一次疫苗资格：不通过就直接把「哪只宠物、有效期到哪天、怎么补录」说清楚。

### 4.2 V8.3 新增：知识检索工具（1 个 · 仅对话内可用）

| 工具 | 类型 | 作用 | 落库路径 |
|---|---|---|---|
| `search_knowledge` | 读 | 按问题检索知识分片（Chroma 向量 + 标签兜底），返回 top-3 与命中依据 | `knowledge_service.search_by_query` |

> 这个工具是 RAG 的**唯一入口**（另一个入口是风险报告链路内部的自动检索）。
> 它只由 Agent 在对话中按需调用，前端没有对应的独立搜索框——检索的价值是支撑回答，
> 脱离回答单独搜一段文本，用户拿不到结论。

| # | 工具 | 类型 | 底层调用 | 权限 |
|---|---|---|---|---|
| 1 | `query_slots` | 只读 | `setting_service` + `appointment` 容量统计 | 全部 |
| 2 | `query_pet_profile` | 只读 | `pet_service.pet_to_out` | 全部（宠主仅自己） |
| 3 | `query_my_appointments` | 只读 | `appointment_service.list_appointments` | 全部（按角色过滤） |
| 4 | `query_risk_report` | 只读 | `risk_service.get_by_appointment` | 全部（宠主仅自己） |
| 5 | `query_report_summary` | 只读 | `stats_service.summary` | staff / manager |
| 6 | `create_appointment` | 受控写 | `appointment_service.create_by_customer` | 全部 |
| 7 | `cancel_appointment` | 受控写 | `appointment_service.change_status` | 全部 |
| 8 | `reschedule_appointment` | 受控写 | `appointment_service.reschedule` | staff / manager |
| 9 | `query_day_schedule` | 只读 | `schedule_service.load_by_date` | staff / manager |
| 10 | `query_todo` | 只读 | `appointment_service` + `risk_service` + `wash_service` | staff / manager |
| 11 | `query_customer_pets` | 只读 | `pet_service.list_pets` + `owners_map` | staff / manager |
| 12 | `query_wash_history` | 只读 | `wash_service.list_wash_records` | staff / manager |
| 13 | `advance_appointment` | 受控写 | `appointment_service.change_status` | staff / manager |
| 14 | `confirm_risk` | 受控写 | `risk_service.confirm_report` | staff / manager |
| 15 | `create_appointment_for_customer` | 受控写 | `appointment_service.create_by_staff` | staff / manager |
| 16 | `query_capacity_analysis` | 只读 | `schedule_service.week_schedule` | staff / manager |
| 17 | `query_churn_list` | 只读 | `stats_service.summary` | manager |
| 18 | `query_staff_performance` | 只读 | `stats_service` + `schedule_service.staff_load` | manager |
| 19 | `query_store_settings` | 只读 | `setting_service.get_all_settings` | staff / manager |
| 20 | `query_audit_trail` | 只读 | `audit_service.list_logs` | manager |
| 21 | `update_store_setting` | 受控写 | `setting_service.update_setting` | manager |
| 22 | `toggle_user_status` | 受控写 | `auth_service.toggle_user_status` | manager |
| 23 | `run_sla_scan` | 受控写 | `appointment_service.sla_scan` | manager |

**实测**：宠主可见 13 个、店员 11 个、店长 11 个（越权工具在 `capabilities` 与执行前双重过滤）。

**铁律落地**：
- 工具内部**只有服务层调用与只读查询**，没有任何拼接 SQL；
- 写操作一律携带 `idempotent_key`（`agent-<随机16位>`），与表单入口共用同一幂等规范；
- Agent 层物理上拿不到数据库 Session 的写能力（只通过 `ToolContext` 传入会话对象给服务层）。

---

## 五、语义兜底：规则识别（LLM 不可用时）

`_interpret_by_rule()` 使用中文关键词 + 正则抽取，保证无 Key 时对话仍可用：

| 抽取项 | 规则 |
|---|---|
| 意图 | 关键词优先级：取消 → 改期 → 预约 → 时段 → 风险 → 报表 → 档案 → 我的预约 → 闲聊 |
| 日期 | `2026-10-20` / `10-20` / 今天 / 明天 / 后天 / 大后天 |
| 时段 | `15:00` / `15：00` / `15点` |
| 服务 | 药浴 → 药浴；美容/修剪/造型 → 美容修剪；洗澡/洗护 → 基础洗澡 |
| 单号 | `PG\d{10,20}` |

**槽位合并策略**：**规则抽取优先**，LLM 只补充规则未识别的项 ——
防止 LLM 编造日期或宠物名；`service_type` 必须落在枚举内，否则丢弃。

---

## 六、会话与数据合规

| 表 | 说明 |
|---|---|
| `chat_session` | 会话（标题、状态、`pending_action` 待确认动作、轮次、最后消息时间、逻辑删除） |
| `chat_message` | 消息（角色、内容、意图、工具名、工具入参与出参、ReAct 轮次） |

- **脱敏**：仅对**用户输入**做手机号 / 身份证脱敏后入库；
  **助手回复不脱敏** —— 其中包含预约单号等业务标识，脱敏会破坏可读性（见开发日志 E-14）。
- **留存**：按门店配置 `session_retention_days` 到期物理删除（`GET /chat/purge`，V4 由 arq 定时接管）。
- **免责**：风险相关回答复用 `risk_service.DISCLAIMER`，明确「不构成医疗诊断」。

---

## 七、可观测性

```bash
# 助手能力与工具清单（按角色返回）
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/chat/capabilities

# 手动清理超期会话（店长）
curl -H "Authorization: Bearer $MANAGER_TOKEN" http://127.0.0.1:8000/api/v1/chat/purge
```

日志事件：`agent tool failed`、`llm_call_failed`、`llm_risk_enhanced`；审计日志模块 `agent` / `chat`。

---

## 八、已验证用例（后端 74 项冒烟中的 21 项 + 浏览器 4 项）

| 用例 | 结果 |
|---|---|
| SSE 事件流包含 `meta` / `intent` / `answer` / `end` | ✅ |
| 查时段返回中文可用回答 | ✅ |
| 写操作进入二次确认闸门，**不直接落库** | ✅ |
| 确认后经业务服务层真实创建预约（订单数 +1） | ✅ |
| 不存在的单号在确认前就被友好拒绝（不产生确认卡） | ✅ |
| 闲聊有友好回复（含降级文案） | ✅ |
| 宠主仅见 13 个工具、店员 11 个、店长 11 个 | ✅ |
| 会话创建 / 历史 / 逻辑删除 / 已删除不可访问 | ✅ |
| 浏览器端：发送消息 → 新增用户与助手气泡、SSE 流式回复、展示工具调用轨迹 | ✅ |
