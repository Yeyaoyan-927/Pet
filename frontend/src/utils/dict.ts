/** 业务字典与配色映射：状态色、风险色、文案。单一事实来源，页面不得自行硬编码。 */

export const SPECIES_LABEL: Record<string, string> = { dog: '犬', cat: '猫', other: '其他' }
export const GENDER_LABEL: Record<string, string> = { male: '公', female: '母' }
export const STRESS_LABEL: Record<number, string> = { 0: '无', 1: '轻度', 2: '中度', 3: '重度' }
export const VACCINE_TYPE_LABEL: Record<string, string> = {
  vaccine: '疫苗',
  deworm_inner: '体内驱虫',
  deworm_outer: '体外驱虫'
}
export const ROLE_LABEL: Record<string, string> = {
  customer: '宠主',
  staff: '店员',
  manager: '店长'
}
export const SERVICE_TYPE_LABEL: Record<string, string> = {
  basic_bath: '基础洗澡',
  medicated_bath: '药浴',
  grooming: '美容修剪'
}
export const ENGINE_LABEL: Record<string, string> = {
  rule: '规则引擎',
  llm: 'AI 增强',
  manual: '人工修正'
}

/** 预约状态 → 柔和底色 + 深色文字（对应用户指定的状态色语义） */
export const APPOINTMENT_STATUS_META: Record<
  string,
  { label: string; bg: string; color: string }
> = {
  pending: { label: '待确认', bg: 'var(--pp-warning-bg)', color: '#c47c2b' },
  confirmed: { label: '已确认', bg: 'var(--pp-primary-lighter)', color: '#3f7fb8' },
  arrived: { label: '已到店', bg: 'var(--pp-info-bg)', color: '#4e7d9f' },
  in_service: { label: '洗护中', bg: '#dbeafa', color: '#2f6fa8' },
  completed: { label: '已完成', bg: 'var(--pp-success-bg)', color: '#4e8a4d' },
  cancelled: { label: '已取消', bg: 'var(--pp-neutral-bg)', color: '#857b6e' },
  no_show: { label: '爽约', bg: 'var(--pp-neutral-bg)', color: '#7a7167' },
  arrived_give_up: { label: '已到店放弃', bg: 'var(--pp-danger-bg)', color: '#c25a3f' },
  wash_interrupt: { label: '洗护中断', bg: 'var(--pp-danger-bg)', color: '#c25a3f' }
}

export const RISK_LEVEL_META: Record<string, { label: string; bg: string; color: string }> = {
  high: { label: '高风险', bg: 'var(--pp-danger-bg)', color: '#c25a3f' },
  low: { label: '低风险', bg: 'var(--pp-warning-bg)', color: '#c47c2b' },
  none: { label: '无风险', bg: 'var(--pp-success-bg)', color: '#4e8a4d' }
}

export const MESSAGE_TYPE_LABEL: Record<string, string> = {
  appointment_created: '预约提交',
  appointment_confirmed: '预约确认',
  appointment_cancelled: '预约取消',
  appointment_completed: '洗护完成',
  appointment_remind: '到店提醒',
  risk_alert: '风险提醒',
  system: '系统消息'
}

/** 状态机：当前状态 → 可用操作（与后端 APPOINTMENT_TRANSITIONS 保持一致） */
export const STATUS_ACTIONS: Record<
  string,
  { status: string; label: string; type: 'primary' | 'success' | 'warning' | 'danger' }[]
> = {
  pending: [
    { status: 'confirmed', label: '确认预约', type: 'primary' },
    { status: 'cancelled', label: '取消', type: 'danger' }
  ],
  confirmed: [
    { status: 'arrived', label: '已到店', type: 'primary' },
    { status: 'no_show', label: '爽约', type: 'warning' },
    { status: 'cancelled', label: '取消', type: 'danger' }
  ],
  arrived: [
    { status: 'in_service', label: '开始洗护', type: 'primary' },
    { status: 'arrived_give_up', label: '到店放弃', type: 'danger' }
  ],
  in_service: [
    { status: 'completed', label: '完成洗护', type: 'success' },
    { status: 'wash_interrupt', label: '洗护中断', type: 'danger' }
  ]
}

/** 需要填写原因的终止类状态 */
export const REASON_REQUIRED_STATUS = ['cancelled', 'no_show', 'arrived_give_up', 'wash_interrupt']

export const INTENT_LABEL: Record<string, string> = {
  query_slots: '查询时段',
  query_pet_profile: '查询档案',
  query_my_appointments: '查询预约',
  query_risk_report: '查询风险',
  query_report_summary: '查询报表',
  create_appointment: '创建预约',
  cancel_appointment: '取消预约',
  reschedule_appointment: '预约改期',
  search_knowledge: '查洗护规范',
  smalltalk: '闲聊'
}

export const TOOL_LABEL: Record<string, string> = {
  // 宠主
  query_slots: '查询可预约时段',
  query_pet_profile: '读取宠物档案',
  query_my_appointments: '读取预约列表',
  query_risk_report: '读取风险报告',
  query_report_summary: '读取经营统计',
  create_appointment: '提交预约（需确认）',
  cancel_appointment: '取消预约（需确认）',
  reschedule_appointment: '预约改期（需确认）',
  // 宠主 · 宠物之家与档案（V8.2）
  create_pet_profile: '新建宠物档案（需确认）',
  query_boarding_options: '查询寄养资格与房型',
  create_boarding_order: '提交寄养申请（需确认）',
  query_goods: '查询用品价格与库存',
  add_goods_to_cart: '加入购物车（需确认）',
  submit_goods_order: '提交用品订单（需确认）',
  // 洗护安全知识库（RAG，V8.3）
  search_knowledge: '检索洗护规范（知识库）',
  // 店员
  query_day_schedule: '查询门店排期',
  query_todo: '查询待办与交班简报',
  query_customer_pets: '查询客户档案',
  query_wash_history: '查询洗护历史',
  advance_appointment: '推进订单状态（需确认）',
  confirm_risk: '风险复核确认（需确认）',
  create_appointment_for_customer: '代客预约（需确认）',
  // 店长
  query_capacity_analysis: '分析时段饱和度',
  query_churn_list: '查询流失预警',
  query_staff_performance: '查询员工业绩',
  query_store_settings: '查询门店配置',
  query_audit_trail: '查询审计日志',
  update_store_setting: '修改门店配置（需确认）',
  toggle_user_status: '启停账号（需确认）',
  run_sla_scan: '触发 SLA 巡检（需确认）'
}

export const EXPORT_TYPES = [
  { value: 'summary', label: '经营概览', desc: '订单量、爽约率、复购率、服务占比、店员工作量、流失预警' },
  { value: 'appointments', label: '预约明细', desc: '区间内全部预约单及状态、风险等级、取消/终止原因' },
  { value: 'wash', label: '洗护记录', desc: '洗护时间、皮肤毛发状况、使用产品与店员记录' },
  { value: 'pets', label: '客户档案', desc: '宠物基础信息、健康标记、应急联系人（含原始电话）' }
]

export const MENU_META: Record<string, { title: string; icon: string; group: string }> = {
  '/user/home': { title: '我的首页', icon: 'HomeFilled', group: '宠主服务' },
  '/user/pets': { title: '宠物档案', icon: 'Star', group: '宠主服务' },
  '/user/appointment/create': { title: '发起预约', icon: 'Calendar', group: '宠主服务' },
  '/user/appointments': { title: '我的预约', icon: 'Tickets', group: '宠主服务' },
  '/user/messages': { title: '消息中心', icon: 'Bell', group: '宠主服务' },
  '/user/boarding': { title: '宠物寄养', icon: 'HomeFilled', group: '宠主服务' },
  '/user/goods': { title: '宠物用品', icon: 'ShoppingBag', group: '宠主服务' },
  '/user/camera': { title: '宠物实景', icon: 'VideoCamera', group: '宠主服务' },
  '/user/chat': { title: 'AI 洗护助手', icon: 'MagicStick', group: '宠主服务' },
  '/staff/boarding': { title: '寄养管理', icon: 'Van', group: '门店运营' },
  '/staff/rooms': { title: '宠舍管理', icon: 'House', group: '门店运营' },
  '/staff/goods': { title: '用品管理', icon: 'ShoppingBag', group: '门店运营' },
  '/staff/camera': { title: '实景采集', icon: 'VideoCamera', group: '门店运营' },
  '/staff/chat': { title: '运营助理', icon: 'MagicStick', group: '门店运营' },
  '/staff/home': { title: '门店看板', icon: 'DataBoard', group: '门店运营' },
  '/staff/appointments': { title: '预约管理', icon: 'Calendar', group: '门店运营' },
  '/staff/risk': { title: '风险复核', icon: 'WarnTriangleFilled', group: '门店运营' },
  '/staff/pets': { title: '客户档案', icon: 'UserFilled', group: '门店运营' },
  '/staff/wash-records': { title: '洗护记录', icon: 'Sunny', group: '门店运营' },
  '/schedule': { title: '门店排期', icon: 'Grid', group: '门店运营' },
  '/staff/knowledge': { title: 'RAG 知识库', icon: 'Collection', group: '系统管理' },
  '/staff/settings': { title: '门店配置', icon: 'Setting', group: '系统管理' },
  '/report/summary': { title: '经营报表', icon: 'TrendCharts', group: '数据统计' },
  '/report/boarding': { title: '寄养看板', icon: 'House', group: '数据统计' },
  '/report/goods': { title: '用品看板', icon: 'ShoppingBag', group: '数据统计' },
  '/report/export': { title: '数据导出', icon: 'Download', group: '数据统计' }
}

/** 寄养状态 → el-tag 语义色（暖色治愈系：蜜桃橙待办、柔和蓝进行中、抹茶绿完成、珊瑚红异常） */
export const BOARDING_STATUS_TONE: Record<string, string> = {
  pending: 'warning',
  confirmed: 'primary',
  waiting_checkin: 'info',
  checked_in: 'primary',
  waiting_pickup: 'info',
  completed: 'success',
  early_pickup: 'warning',
  overdue_unpicked: 'danger',
  cancelled: 'info',
  no_show: 'danger',
  medical_terminated: 'danger'
}

export const ROOM_STATUS_TONE: Record<string, string> = {
  idle: 'success',
  occupied: 'primary',
  cleaning: 'warning',
  maintenance: 'info'
}

export const CARE_ITEM_LABEL: Record<string, string> = {
  medication: '用药',
  feeding: '喂食',
  walk: '遛放',
  taboo: '禁忌'
}
