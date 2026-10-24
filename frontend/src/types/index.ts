/** 全局 TypeScript 类型定义。接口统一返回 ApiResult<T>。 */

export interface ApiResult<T = unknown> {
  code: number
  message: string
  data: T
}

export interface PageData<T> {
  items: T[]
  total: number
  page: number
  size: number
}

export type UserRole = 'customer' | 'staff' | 'manager'

export interface UserInfo {
  id: number
  username: string
  real_name: string | null
  phone_masked: string | null
  phone?: string | null
  role: UserRole
  status: number
  is_temp?: number
  last_login_at?: string | null
  created_at?: string
}

export interface LoginResult {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: UserInfo
}

/* ---------------- 宠物档案 ---------------- */
export type Species = 'dog' | 'cat' | 'other'

export interface Pet {
  id: number
  user_id: number
  staff_id: number | null
  name: string
  species: Species
  breed: string | null
  gender: 'male' | 'female'
  birthday: string | null
  weight: number | null
  sterilized: number
  allergy: string | null
  skin_disease: string | null
  stress_level: number
  aggressive: number
  emergency_contact: string | null
  emergency_phone: string | null
  remark: string | null
  age_month?: number | null
  owner_name?: string | null
  created_at?: string
  updated_at?: string
}

export interface VaccineRecord {
  id: number
  pet_id: number
  record_type: 'vaccine' | 'deworm_inner' | 'deworm_outer'
  name: string | null
  record_date: string
  next_date: string | null
  remark: string | null
}

/* ---------------- 预约 ---------------- */
export type AppointmentStatus =
  | 'pending'
  | 'confirmed'
  | 'arrived'
  | 'in_service'
  | 'completed'
  | 'cancelled'
  | 'no_show'
  | 'arrived_give_up'
  | 'wash_interrupt'

export interface Appointment {
  id: number
  order_no: string
  user_id: number
  pet_id: number
  pet_name: string | null
  pet_breed: string | null
  owner_name: string | null
  owner_phone: string | null
  service_type: string
  service_type_label: string | null
  appoint_date: string
  slot_time: string
  status: AppointmentStatus
  status_label: string | null
  staff_id: number | null
  staff_name: string | null
  risk_level: string | null
  risk_level_label?: string | null
  remark: string | null
  cancel_reason: string | null
  terminate_reason: string | null
  reschedule_times: number
  confirm_at: string | null
  arrive_at: string | null
  finish_at: string | null
  created_at: string | null
}

export interface SlotItem {
  slot_time: string
  capacity: number
  used: number
  remain: number
  disabled: boolean
}

export interface OverviewStats {
  today_total: number
  today_pending: number
  today_confirmed: number
  today_arrived: number
  today_finished: number
  week_total: number
}

/* ---------------- 风险 ---------------- */
export interface RiskItem {
  key: string
  level: 'high' | 'low' | 'none'
  desc: string
  advice: string
}

export interface RiskReport {
  id: number
  appointment_id: number
  pet_id: number
  pet_name: string | null
  order_no: string | null
  appoint_date: string | null
  slot_time: string | null
  risk_level: 'high' | 'low' | 'none'
  risk_level_label: string
  engine_type: string
  risk_items: RiskItem[]
  ai_summary: string | null
  suggestion: string | null
  confirmed: number
  confirmed_by: number | null
  confirmed_at: string | null
  handle_measure: string | null
  invalidated: number
  created_at: string
}

/* ---------------- 洗护记录 ---------------- */
export interface WashRecord {
  id: number
  appointment_id: number
  order_no: string | null
  pet_id: number
  pet_name: string | null
  pet_breed: string | null
  pet_species: Species | null
  owner_name: string | null
  owner_phone: string | null
  staff_id: number | null
  service_type: string
  service_type_label: string
  appoint_date: string | null
  slot_time: string | null
  wash_start: string | null
  wash_end: string | null
  skin_condition: string | null
  hair_condition: string | null
  products: string | null
  staff_note: string | null
  created_at: string
}

export interface WashStats {
  total: number
  this_month: number
  avg_minutes: number
  service_distribution: TrendPoint[]
}

/* ---------------- 排期 ---------------- */
export interface ScheduleBrief {
  id: number
  order_no: string
  pet_name: string | null
  pet_species: Species | null
  owner_name: string | null
  owner_phone: string | null
  service_type: string
  service_type_label: string
  status: AppointmentStatus
  status_label: string
  risk_level: string | null
  staff_id: number | null
}

export interface ScheduleSlot {
  slot_time: string
  capacity: number
  used: number
  remain: number
  full: boolean
  appointments: ScheduleBrief[]
}

export interface ScheduleDay {
  date: string
  weekday: string
  is_today: boolean
  total: number
  slots: ScheduleSlot[]
}

export interface ScheduleData {
  start: string
  end: string
  capacity: number
  days: ScheduleDay[]
  generated_at: string
}

/* ---------------- 消息 ---------------- */
export interface MessageItem {
  id: number
  title: string
  content: string | null
  msg_type: string
  msg_type_label: string
  biz_id: number | null
  is_read: number
  read_at: string | null
  created_at: string
}

/* ---------------- 门店配置 ---------------- */
export interface SettingItem {
  id: number
  setting_key: string
  setting_value: string
  value_type: 'int' | 'bool' | 'string'
  default_value: string
  setting_desc: string | null
  min_value: number | null
  max_value: number | null
}

/* ---------------- 报表 ---------------- */
export interface TrendPoint {
  label: string
  value: number
}

export interface StaffWorkload {
  staff_id: number
  staff_name: string
  finished_count: number
}

export interface ChurnPet {
  pet_id: number
  pet_name: string
  owner_name: string | null
  last_wash_date: string | null
  idle_days: number | null
}

export interface ReportSummary {
  range_start: string
  range_end: string
  total_orders: number
  completed_orders: number
  cancelled_orders: number
  no_show_orders: number
  no_show_rate: number
  repurchase_rate: number
  service_ratio: TrendPoint[]
  status_distribution: TrendPoint[]
  daily_trend: TrendPoint[]
  peak_hours: TrendPoint[]
  staff_workload: StaffWorkload[]
  churn_pets: ChurnPet[]
  risk_high_count: number
  give_up_count: number
  churn_days: number
}

export interface AuditLogItem {
  id: number
  module: string
  action: string
  user_id: number | null
  staff_id: number | null
  biz_id: number | null
  ip: string | null
  status: number
  detail: string | null
  created_at: string
}

/* ---------------- RAG 知识库管理 ---------------- */
export type KnowledgeChunkStrategy = 'fixed' | 'paragraph' | 'heading'
export type KnowledgeProcessStatus = 'pending' | 'processing' | 'completed' | 'failed'

export interface KnowledgeDocument {
  id: number
  original_name: string
  file_ext: string
  mime_type: string | null
  size_bytes: number
  sha256: string
  uploaded_by: number
  uploader_name: string | null
  status: KnowledgeProcessStatus
  status_label: string
  chunk_strategy: KnowledgeChunkStrategy
  chunk_strategy_label: string
  chunk_size: number
  chunk_overlap: number
  text_length: number
  total_chunks: number
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeChunk {
  id: number
  document_id: number
  chunk_index: number
  section_title: string | null
  content: string
  page_start: number | null
  page_end: number | null
  paragraph_start: number | null
  paragraph_end: number | null
  char_start: number
  char_end: number
  source_label: string
  created_at: string
}

export interface KnowledgeTask {
  id: number
  document_id: number | null
  document_name: string | null
  task_type: 'ingest' | 'rebuild'
  status: KnowledgeProcessStatus
  status_label: string
  progress: number
  message: string | null
  error_message: string | null
  created_by: number
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeLimits {
  max_file_mb: number
  max_batch_files: number
  allowed_extensions: string[]
  default_strategy: KnowledgeChunkStrategy
  default_chunk_size: number
  default_chunk_overlap: number
  min_chunk_size: number
  max_chunk_size: number
  max_chunk_overlap: number
}

export interface KnowledgeMeta {
  documents: number
  chunks: number
  failed_documents: number
  active_tasks: number
  index: { ok: boolean; space: string; entries: number }
  limits: KnowledgeLimits
  permissions: Record<'staff' | 'manager', string[]>
  role: UserRole
  can_manage: boolean
}

export interface KnowledgeUploadItem {
  accepted: boolean
  duplicate: boolean
  message: string
  file_name?: string
  document: KnowledgeDocument | null
  task: KnowledgeTask | null
}

export interface KnowledgeUploadResult {
  items: KnowledgeUploadItem[]
  accepted: number
  duplicates: number
  rejected: number
}

/* ---------------- AI 对话 ---------------- */
export type ChatRole = 'user' | 'assistant'

export interface ChatSessionItem {
  id: number
  title: string
  status: string
  turn_count: number
  last_message_at: string | null
  preview: string
  created_at: string
}

/** 知识库检索到的片段（RAG 依据），气泡下方折叠展示 */
export interface KnowledgeRef {
  title: string
  section: string
  source: string
  content: string
  matched: string
}

export interface ChatHistoryMessage {
  id: number
  role: ChatRole
  content: string
  intent: string | null
  tool_name: string | null
  /** 知识问答的依据片段（仅 search_knowledge 的消息有） */
  refs?: KnowledgeRef[] | null
  created_at: string
}

/** 领域 Agent 的轻量视图（后端按当前端下发可激活清单） */
export interface AgentBrief {
  key: string
  name: string
  summary: string
}

export interface ChatCapabilities {
  llm_available: boolean
  model: string | null
  max_steps: number
  architecture: string
  /** 当前角色与画像（后端按角色下发工具清单） */
  role: UserRole
  role_profile: string
  capability_summary: string
  /** 当前端可激活的 Agent（路由与风控恒在，领域 Agent 按端裁剪） */
  agents: AgentBrief[]
  tools: { name: string; description: string; write: boolean }[]
  examples: string[]
}

/** SSE 事件（服务端推送的流式结构） */
export type AgentEvent =
  | { type: 'meta'; session_id: number; llm: boolean }
  | { type: 'thought'; content: string }
  | { type: 'intent'; intent: string; slots: Record<string, string | null>; source: string; agent?: AgentBrief }
  | { type: 'action'; tool: string; args: Record<string, unknown> }
  | { type: 'observation'; tool: string; ok?: boolean; result?: unknown; error?: string }
  | { type: 'confirm'; tool: string; args: Record<string, unknown>; prompt: string }
  /** 服务端建议跳转（如「看看宠物状态」→ 宠物实景）；只做导航，不含任何写操作 */
  | { type: 'navigate'; path: string; label?: string }
  | { type: 'answer'; delta: string }
  /** 知识问答检索到的片段（随答案一起下发，前端折叠展示） */
  | { type: 'refs'; items: KnowledgeRef[] }
  /** 多选一：实景选宠物等场景，前端渲染成可点 chip */
  | { type: 'choices'; items: string[] }
  /** 摄像头不可用（未装 / 停用 / 离线）：小窗说明原因，不跳转 */
  | { type: 'camera_error'; pet_name: string; order_no: string; reason: string }
  | { type: 'error'; message: string }
  | { type: 'done' }
  | { type: 'end' }

/** 前端对话气泡模型 */
export interface ChatBubble {
  id: string
  role: ChatRole
  content: string
  streaming?: boolean
  intent?: string
  /** 本轮由哪个领域 Agent 接手（路由调度分派结果） */
  agent?: AgentBrief
  tool?: string
  thoughts?: string[]
  confirm?: { tool: string; args: Record<string, unknown>; prompt?: string }
  /** 知识问答的检索依据（可折叠） */
  refs?: KnowledgeRef[]
  /** 助手给出的可点选项（如「看豆豆的实景」） */
  choices?: string[]
  error?: string
}

export interface DictOption {
  value: string
  label: string
}

/* ---------------- 宠物寄养（V7.1） ---------------- */
export interface BoardingRoom {
  id: number
  room_no: string
  room_type: string
  room_type_label: string
  name: string
  species_limit: string
  weight_limit: number | null
  ratio_percent: number
  capacity: number
  status: string
  status_label: string
  facilities: string[]
  remark: string | null
  available?: boolean
  unavailable_note?: string
  est_daily_cents?: number
}

export interface BoardingCarePlan {
  id: number
  item_type: string
  content: string
  frequency: string | null
  need_staff: number
}

export interface BoardingCareLog {
  id: number
  log_date: string
  eating?: string
  drinking?: string
  stool?: string
  spirit?: string
  activity?: string
  abnormal: number
  abnormal_note?: string
  photos: string[]
  sop_checked: string[]
  staff_id?: number
  created_at: string
}

export interface BoardingPickupTask {
  id: number
  order_id: number
  order_no?: string
  task_type: string
  task_type_label: string
  status: string
  status_label: string
  address?: string
  slot_time?: string
  fee: number
  departed_at?: string
  picked_at?: string
  arrived_at?: string
  sign_off_by?: string
}

/** 提前接回申请（宠主发起 → 门店审核） */
export interface BoardingEarlyPickup {
  id: number
  order_id: number
  order_no?: string | null
  pet_name?: string | null
  expect_pickup_date: string
  reason?: string | null
  status: 'pending' | 'approved' | 'rejected'
  status_label: string
  review_note?: string | null
  reviewed_by?: number | null
  reviewed_at?: string | null
  created_at?: string
}

export interface BoardingOrder {
  id: number
  order_no: string
  user_id: number
  pet_id: number
  pet_name?: string
  pet_species?: string
  owner_name?: string
  owner_phone?: string
  room_id: number
  room_no?: string
  room_type: string
  room_type_label: string
  status: string
  status_label: string
  check_in_date: string
  check_out_date: string
  nights: number
  extend_times: number
  feeding_plan: string
  feeding_plan_label: string
  food_note?: string
  dropoff_method: string
  dropoff_method_label: string
  pickup_back_method: string
  pickup_back_method_label: string
  shipping_method: string
  shipping_method_label: string
  shipping_address?: string
  shipping_slot?: string
  /** 最近一条提前接回申请（详情接口返回） */
  early_pickup?: BoardingEarlyPickup | null
  daily_fee: number
  subtotal: number
  discount_percent: number
  extra_fee: number
  shipping_fee: number
  total_amount: number
  settle_note?: string
  vaccine_ok: number
  vaccine_note?: string
  isolate_required: number
  risk_level?: string
  emergency_contact?: string
  emergency_phone?: string
  medical_authorized: number
  checkin_at?: string
  checkout_at?: string
  checkin_note?: string
  checkout_note?: string
  cancel_reason?: string
  terminate_reason?: string
  remark?: string
  created_at: string
  care_plans?: BoardingCarePlan[]
  care_logs?: BoardingCareLog[]
  pickup_tasks?: BoardingPickupTask[]
}

export interface BoardingQuote {
  nights: number
  weight_label: string
  base_price_cents: number
  room_ratio_percent: number
  daily_fee_cents: number
  subtotal_cents: number
  holiday_nights: number
  discount_percent: number
  discounted_cents: number
  feeding_fee_cents: number
  shipping_fee_cents: number
  total_cents: number
}

export interface BoardingMeta {
  order_status: Record<string, string>
  room_type: Record<string, string>
  room_status: Record<string, string>
  feeding_plan: Record<string, string>
  shipping_method: Record<string, string>
  dropoff_method: Record<string, string>
  pickup_back_method: Record<string, string>
  pickup_status: Record<string, string>
  care_item_types: Record<string, string>
  rules: Record<string, number>
}

export interface BoardingDashboard {
  range_start: string
  range_end: string
  orders: number
  revenue: number
  avg_nights: number
  avg_price: number
  total_rooms: number
  occupied_now: number
  occupancy_rate: number
  room_type_stat: { room_type: string; label: string; count: number; revenue: number }[]
  status_stat: { status: string; label: string; count: number }[]
  care_logs: number
  abnormal_logs: number
  abnormal_rate: number
  room_status_stat: Record<string, number>
}

/* ---------------- 宠物用品（V7.2） ---------------- */
export interface GoodsSku {
  id: number
  spec_name: string
  price: number
  price_cents: number
  unit_price: number | null
  weight_g: number | null
  stock: number
  low_stock: boolean
  barcode?: string | null
}

export interface GoodsProduct {
  id: number
  name: string
  brand?: string | null
  category: string
  category_label: string
  species: string
  stage: string
  stage_label: string
  size: string
  size_label: string
  main_image?: string | null
  selling_points: string[]
  promo_tags: string[]
  allergy_tags: string[]
  taboo_tags: string[]
  min_price?: number
  max_price?: number
  total_stock?: number
  sales_count?: number
  skus: GoodsSku[]
  unsafe: boolean
  conflicts: string[]
  detail?: string | null
  min_weight?: number | null
  max_weight?: number | null
  pet_name?: string | null
  alternative?: { id: number; name: string; price: number } | null
}

export interface CartLine {
  id: number
  sku_id: number
  product_id: number
  product_name: string
  spec_name: string
  image?: string | null
  price: number
  quantity: number
  subtotal: number
  stock: number
  pet_id?: number | null
  pet_name?: string | null
  unsafe: boolean
  conflicts: string[]
}

export interface GoodsOrderItemLine {
  id: number
  sku_id: number
  product_id: number
  product_name: string
  spec_name: string
  image?: string | null
  price: number
  quantity: number
  subtotal: number
}

export interface GoodsOrder {
  id: number
  order_no: string
  user_id: number
  owner_name?: string | null
  owner_phone?: string | null
  status: string
  status_label: string
  pay_status: string
  pay_status_label: string
  item_count: number
  total_amount: number
  delivery_fee: number
  pickup_method: string
  pickup_method_label: string
  address?: string | null
  remark?: string | null
  pickup_code: string
  cancel_reason?: string | null
  confirmed_at?: string | null
  completed_at?: string | null
  created_at: string
  items: GoodsOrderItemLine[]
}

export interface GoodsDashboard {
  range_start: string
  range_end: string
  orders: number
  completed: number
  cancelled: number
  stockout: number
  revenue: number
  avg_price: number
  avg_items: number
  top_products: { name: string; qty: number; revenue: number }[]
  category_stat: { category: string; label: string; revenue: number }[]
  low_stock_count: number
  low_stock: { sku_id: number; product_name: string; spec_name: string; stock: number; warn_threshold: number }[]
  cancel_rate: number
}

/* ---------------- 宠物实景（V7.3） ---------------- */
export interface CameraLiveItem {
  order_id: number
  order_no: string
  pet_name?: string | null
  pet_id: number
  room_id: number
  device_id?: number | null
  provider_type?: string | null
  device_status?: string | null
  can_watch: boolean
  reason: string
  check_out_date: string
}

export interface CameraSessionOut {
  session_id: number
  token: string
  expires_in: number
  stream_path: string
  push_path: string
  provider_type: string
  fps: number
  resolution: string
  watermark: string
  order_no: string
  device_id: number
  /** true = 门店暂无真实推流，后端返回单帧演示画面，前端按帧轮询刷新 */
  demo?: boolean
}

export interface CameraDeviceItem {
  id: number
  room_id: number
  room_no?: string | null
  name: string
  provider_type: string
  provider_label: string
  status: string
  status_label: string
  enabled: number
  fps: number
  resolution: string
  stream_url?: string | null
  last_heartbeat_at?: string | null
  implemented: boolean
}

export interface CameraStats {
  range_start: string
  range_end: string
  watch_count: number
  total_seconds: number
  avg_seconds: number
  unique_viewers: number
  snapshots: number
  device_total: number
  device_online: number
  online_rate: number
  offline_devices: { id: number; name: string; last_heartbeat_at?: string | null }[]
}

export interface CameraSnapshotItem {
  id: number
  order_id: number
  image_url: string
  note?: string | null
  created_at: string
}

/** 寄养资格预检结果（疫苗是硬门槛） */
export interface BoardingEligibility {
  ok: boolean
  code: string
  message: string
  pet_id: number
  pet_name: string
  check_in: string
  vaccine_until: string | null
  weight_kg: number
  weight_label: string
  min_nights: number
}
