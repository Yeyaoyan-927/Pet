"""业务常量：状态机、角色、配置键与校验规则。单一事实来源，禁止在业务代码里散落魔法字符串。"""
from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    CUSTOMER = "customer"
    STAFF = "staff"
    MANAGER = "manager"


class KnowledgeDocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class KnowledgeTaskType(StrEnum):
    INGEST = "ingest"
    REBUILD = "rebuild"


class KnowledgeTaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class KnowledgeChunkStrategy(StrEnum):
    FIXED = "fixed"
    PARAGRAPH = "paragraph"
    HEADING = "heading"


KNOWLEDGE_DOCUMENT_STATUS_LABEL = {
    KnowledgeDocumentStatus.PENDING.value: "待处理",
    KnowledgeDocumentStatus.PROCESSING.value: "处理中",
    KnowledgeDocumentStatus.COMPLETED.value: "已完成",
    KnowledgeDocumentStatus.FAILED.value: "失败",
}

KNOWLEDGE_TASK_STATUS_LABEL = {
    KnowledgeTaskStatus.PENDING.value: "待处理",
    KnowledgeTaskStatus.PROCESSING.value: "处理中",
    KnowledgeTaskStatus.COMPLETED.value: "完成",
    KnowledgeTaskStatus.FAILED.value: "失败",
}

KNOWLEDGE_CHUNK_STRATEGY_LABEL = {
    KnowledgeChunkStrategy.FIXED.value: "固定长度",
    KnowledgeChunkStrategy.PARAGRAPH.value: "按段落",
    KnowledgeChunkStrategy.HEADING.value: "按标题",
}


ROLE_LABEL = {
    UserRole.CUSTOMER.value: "宠主",
    UserRole.STAFF.value: "店员",
    UserRole.MANAGER.value: "店长",
}

# 宠物档案的基础字典：Agent 确认卡 / 回执要按中文回显，避免把 male / dog 直接抛给用户
PET_SPECIES_LABEL = {"dog": "犬", "cat": "猫", "other": "其他"}
PET_GENDER_LABEL = {"male": "公", "female": "母"}


class ServiceType(StrEnum):
    BASIC_BATH = "basic_bath"        # 基础洗澡
    MEDICATED_BATH = "medicated_bath"  # 药浴
    GROOMING = "grooming"            # 美容修剪


SERVICE_TYPE_LABEL = {
    ServiceType.BASIC_BATH.value: "基础洗澡",
    ServiceType.MEDICATED_BATH.value: "药浴",
    ServiceType.GROOMING.value: "美容修剪",
}
SERVICE_PRICE_HINT = {
    ServiceType.BASIC_BATH.value: 88,
    ServiceType.MEDICATED_BATH.value: 168,
    ServiceType.GROOMING.value: 258,
}


class AppointmentStatus(StrEnum):
    PENDING = "pending"                  # 待确认
    CONFIRMED = "confirmed"              # 已确认
    ARRIVED = "arrived"                  # 已到店
    IN_SERVICE = "in_service"            # 洗护中
    COMPLETED = "completed"              # 已完成
    CANCELLED = "cancelled"              # 已取消
    NO_SHOW = "no_show"                  # 爽约
    ARRIVED_GIVE_UP = "arrived_give_up"  # 已到店放弃
    WASH_INTERRUPT = "wash_interrupt"    # 洗护中断


APPOINTMENT_STATUS_LABEL = {
    AppointmentStatus.PENDING.value: "待确认",
    AppointmentStatus.CONFIRMED.value: "已确认",
    AppointmentStatus.ARRIVED.value: "已到店",
    AppointmentStatus.IN_SERVICE.value: "洗护中",
    AppointmentStatus.COMPLETED.value: "已完成",
    AppointmentStatus.CANCELLED.value: "已取消",
    AppointmentStatus.NO_SHOW.value: "爽约",
    AppointmentStatus.ARRIVED_GIVE_UP.value: "已到店放弃",
    AppointmentStatus.WASH_INTERRUPT.value: "洗护中断",
}

# 状态机：key -> 允许流转到的状态集合
APPOINTMENT_TRANSITIONS: dict[str, set[str]] = {
    AppointmentStatus.PENDING.value: {
        AppointmentStatus.CONFIRMED.value,
        AppointmentStatus.CANCELLED.value,
    },
    AppointmentStatus.CONFIRMED.value: {
        AppointmentStatus.ARRIVED.value,
        AppointmentStatus.CANCELLED.value,
        AppointmentStatus.NO_SHOW.value,
    },
    AppointmentStatus.ARRIVED.value: {
        AppointmentStatus.IN_SERVICE.value,
        AppointmentStatus.ARRIVED_GIVE_UP.value,
    },
    AppointmentStatus.IN_SERVICE.value: {
        AppointmentStatus.COMPLETED.value,
        AppointmentStatus.WASH_INTERRUPT.value,
    },
    AppointmentStatus.COMPLETED.value: set(),
    AppointmentStatus.CANCELLED.value: set(),
    AppointmentStatus.NO_SHOW.value: set(),
    AppointmentStatus.ARRIVED_GIVE_UP.value: set(),
    AppointmentStatus.WASH_INTERRUPT.value: set(),
}

# 终止类状态：变更为这些状态时必须填写原因（与前端 REASON_REQUIRED_STATUS 对齐）
REASON_REQUIRED_STATUS = {
    AppointmentStatus.CANCELLED.value,
    AppointmentStatus.NO_SHOW.value,
    AppointmentStatus.ARRIVED_GIVE_UP.value,
    AppointmentStatus.WASH_INTERRUPT.value,
}

# 占用时段容量的状态（取消/爽约/放弃/中断后释放时段）
ACTIVE_APPOINTMENT_STATUS = {
    AppointmentStatus.PENDING.value,
    AppointmentStatus.CONFIRMED.value,
    AppointmentStatus.ARRIVED.value,
    AppointmentStatus.IN_SERVICE.value,
    AppointmentStatus.COMPLETED.value,
}

# 计入"订单量统计"的状态（已确认及以上）
VALID_ORDER_STATUS = {
    AppointmentStatus.CONFIRMED.value,
    AppointmentStatus.ARRIVED.value,
    AppointmentStatus.IN_SERVICE.value,
    AppointmentStatus.COMPLETED.value,
    AppointmentStatus.ARRIVED_GIVE_UP.value,
    AppointmentStatus.WASH_INTERRUPT.value,
}

# 需要填写终止原因的状态
TERMINATE_REQUIRED_STATUS = {
    AppointmentStatus.ARRIVED_GIVE_UP.value,
    AppointmentStatus.WASH_INTERRUPT.value,
    AppointmentStatus.CANCELLED.value,
    AppointmentStatus.NO_SHOW.value,
}


class RiskLevel(StrEnum):
    HIGH = "high"
    LOW = "low"
    NONE = "none"


RISK_LEVEL_LABEL = {
    RiskLevel.HIGH.value: "高风险",
    RiskLevel.LOW.value: "低风险",
    RiskLevel.NONE.value: "无风险",
}


class EngineType(StrEnum):
    RULE = "rule"
    LLM = "llm"


class MessageType(StrEnum):
    APPOINTMENT_CREATED = "appointment_created"
    APPOINTMENT_CONFIRMED = "appointment_confirmed"
    APPOINTMENT_CANCELLED = "appointment_cancelled"
    APPOINTMENT_COMPLETED = "appointment_completed"
    APPOINTMENT_REMIND = "appointment_remind"
    RISK_ALERT = "risk_alert"
    VACCINE_REMIND = "vaccine_remind"
    REPURCHASE_REMIND = "repurchase_remind"
    BOARDING_CREATED = "boarding_created"
    BOARDING_STATUS = "boarding_status"
    BOARDING_LOG = "boarding_log"
    BOARDING_ABNORMAL = "boarding_abnormal"
    GOODS_CREATED = "goods_created"
    GOODS_STATUS = "goods_status"
    CAMERA_OFFLINE = "camera_offline"
    SYSTEM = "system"


MESSAGE_TYPE_LABEL = {
    MessageType.APPOINTMENT_CREATED.value: "预约提交",
    MessageType.APPOINTMENT_CONFIRMED.value: "预约确认",
    MessageType.APPOINTMENT_CANCELLED.value: "预约取消",
    MessageType.APPOINTMENT_COMPLETED.value: "洗护完成",
    MessageType.APPOINTMENT_REMIND.value: "到店提醒",
    MessageType.RISK_ALERT.value: "风险提醒",
    MessageType.VACCINE_REMIND.value: "疫苗临期提醒",
    MessageType.REPURCHASE_REMIND.value: "复购回访提醒",
    MessageType.BOARDING_CREATED.value: "寄养申请",
    MessageType.BOARDING_STATUS.value: "寄养状态",
    MessageType.BOARDING_LOG.value: "照护日报",
    MessageType.BOARDING_ABNORMAL.value: "照护异常",
    MessageType.GOODS_CREATED.value: "用品订单",
    MessageType.GOODS_STATUS.value: "用品状态",
    MessageType.CAMERA_OFFLINE.value: "设备离线",
    MessageType.SYSTEM.value: "系统消息",
}


class StaffConfirmStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    INVALID = "invalid"


# ---------------------------------------------------------------- 宠物寄养（V7.1）
class BoardingOrderStatus(StrEnum):
    PENDING = "pending"                        # 待确认
    CONFIRMED = "confirmed"                    # 已确认
    WAITING_CHECKIN = "waiting_checkin"        # 待入住
    CHECKED_IN = "checked_in"                  # 已入住（寄养中）
    WAITING_PICKUP = "waiting_pickup"          # 待接回
    COMPLETED = "completed"                    # 已完成（正常接回）
    EARLY_PICKUP = "early_pickup"              # 提前接回
    OVERDUE_UNPICKED = "overdue_unpicked"      # 超时未接回
    CANCELLED = "cancelled"                    # 已取消
    NO_SHOW = "no_show"                        # 爽约未入住
    MEDICAL_TERMINATED = "medical_terminated"  # 健康异常终止


BOARDING_STATUS_LABEL = {
    BoardingOrderStatus.PENDING.value: "待确认",
    BoardingOrderStatus.CONFIRMED.value: "已确认",
    BoardingOrderStatus.WAITING_CHECKIN.value: "待入住",
    BoardingOrderStatus.CHECKED_IN.value: "寄养中",
    BoardingOrderStatus.WAITING_PICKUP.value: "待接回",
    BoardingOrderStatus.COMPLETED.value: "已完成",
    BoardingOrderStatus.EARLY_PICKUP.value: "提前接回",
    BoardingOrderStatus.OVERDUE_UNPICKED.value: "超时未接回",
    BoardingOrderStatus.CANCELLED.value: "已取消",
    BoardingOrderStatus.NO_SHOW.value: "爽约未入住",
    BoardingOrderStatus.MEDICAL_TERMINATED.value: "健康异常终止",
}

# 状态流转表（与预约状态机同一套工程纪律：集中定义、非法流转 409、审计留痕）
BOARDING_TRANSITIONS: dict[str, set[str]] = {
    BoardingOrderStatus.PENDING.value: {
        BoardingOrderStatus.CONFIRMED.value, BoardingOrderStatus.CANCELLED.value,
    },
    BoardingOrderStatus.CONFIRMED.value: {
        BoardingOrderStatus.WAITING_CHECKIN.value, BoardingOrderStatus.CANCELLED.value,
        BoardingOrderStatus.NO_SHOW.value,
    },
    BoardingOrderStatus.WAITING_CHECKIN.value: {
        BoardingOrderStatus.CHECKED_IN.value, BoardingOrderStatus.CANCELLED.value,
        BoardingOrderStatus.NO_SHOW.value,
    },
    BoardingOrderStatus.CHECKED_IN.value: {
        BoardingOrderStatus.WAITING_PICKUP.value, BoardingOrderStatus.EARLY_PICKUP.value,
        BoardingOrderStatus.MEDICAL_TERMINATED.value,
    },
    BoardingOrderStatus.WAITING_PICKUP.value: {
        BoardingOrderStatus.COMPLETED.value, BoardingOrderStatus.EARLY_PICKUP.value,
        BoardingOrderStatus.OVERDUE_UNPICKED.value, BoardingOrderStatus.MEDICAL_TERMINATED.value,
    },
    # 以下为终态，无出边：completed / early_pickup / overdue_unpicked / cancelled / no_show /
    # medical_terminated
}

# 终止类状态：必须填写原因
BOARDING_REASON_REQUIRED_STATUS = {
    BoardingOrderStatus.CANCELLED.value,
    BoardingOrderStatus.NO_SHOW.value,
    BoardingOrderStatus.EARLY_PICKUP.value,
    BoardingOrderStatus.MEDICAL_TERMINATED.value,
    BoardingOrderStatus.OVERDUE_UNPICKED.value,
}

# 占用房态（房型容量校验口径）：终态后释放
BOARDING_ACTIVE_STATUS = {
    BoardingOrderStatus.PENDING.value,
    BoardingOrderStatus.CONFIRMED.value,
    BoardingOrderStatus.WAITING_CHECKIN.value,
    BoardingOrderStatus.CHECKED_IN.value,
    BoardingOrderStatus.WAITING_PICKUP.value,
}

BOARDING_TERMINAL_STATUS = {
    BoardingOrderStatus.COMPLETED.value,
    BoardingOrderStatus.EARLY_PICKUP.value,
    BoardingOrderStatus.OVERDUE_UNPICKED.value,
    BoardingOrderStatus.CANCELLED.value,
    BoardingOrderStatus.NO_SHOW.value,
    BoardingOrderStatus.MEDICAL_TERMINATED.value,
}


class BoardingRoomStatus(StrEnum):
    IDLE = "idle"                # 空闲
    OCCUPIED = "occupied"        # 占用中
    CLEANING = "cleaning"        # 清洁中（退房消杀）
    MAINTENANCE = "maintenance"  # 维护中


BOARDING_ROOM_STATUS_LABEL = {
    BoardingRoomStatus.IDLE.value: "空闲",
    BoardingRoomStatus.OCCUPIED.value: "占用中",
    BoardingRoomStatus.CLEANING.value: "清洁中",
    BoardingRoomStatus.MAINTENANCE.value: "维护中",
}


class FeedingPlan(StrEnum):
    SELF = "self"                  # 自备食物
    STANDARD = "standard"          # 门店标准粮
    PREMIUM = "premium"            # 升级粮
    PRESCRIPTION = "prescription"  # 处方餐


FEEDING_PLAN_LABEL = {
    FeedingPlan.SELF.value: "自备食物",
    FeedingPlan.STANDARD.value: "门店标准粮",
    FeedingPlan.PREMIUM.value: "升级粮",
    FeedingPlan.PRESCRIPTION.value: "处方餐",
}


class ShippingMethod(StrEnum):
    """历史字段：保留用于兼容旧数据，新逻辑改用下面两组（到店 / 离店各选一个）。"""

    SELF_DELIVER = "self"       # 自送到店
    PICKUP = "pickup"           # 上门接宠
    RETURN_HOME = "return"      # 送宠到家（离店）


SHIPPING_METHOD_LABEL = {
    ShippingMethod.SELF_DELIVER.value: "自送到店",
    ShippingMethod.PICKUP.value: "上门接宠",
    ShippingMethod.RETURN_HOME.value: "送宠到家",
}


class DropoffMethod(StrEnum):
    """送宠到店（第一行）：自行送到 / 门店上门接。"""

    SELF = "self"      # 自行送到
    PICKUP = "pickup"  # 上门接宠


DROPOFF_METHOD_LABEL = {
    DropoffMethod.SELF.value: "自行送到",
    DropoffMethod.PICKUP.value: "上门接宠",
}


class PickupBackMethod(StrEnum):
    """离店接宠（第二行）：自行接取 / 门店送宠到家。"""

    SELF = "self"      # 自行接取
    RETURN = "return"  # 送宠到家


PICKUP_BACK_METHOD_LABEL = {
    PickupBackMethod.SELF.value: "自行接取",
    PickupBackMethod.RETURN.value: "送宠到家",
}


class PickupTaskStatus(StrEnum):
    PENDING = "pending"    # 待出发
    DEPARTED = "departed"  # 已出发
    PICKED = "picked"      # 已接到
    ARRIVED = "arrived"    # 已送达


PICKUP_TASK_STATUS_LABEL = {
    PickupTaskStatus.PENDING.value: "待出发",
    PickupTaskStatus.DEPARTED.value: "已出发",
    PickupTaskStatus.PICKED.value: "已接到",
    PickupTaskStatus.ARRIVED.value: "已送达",
}


# ---------------------------------------------------------------- 宠物用品（V7.2）
class GoodsOrderStatus(StrEnum):
    PENDING = "pending"                      # 待确认
    CONFIRMED = "confirmed"                  # 已确认
    READY = "ready"                          # 待取货
    COMPLETED = "completed"                  # 已完成（核销/送达）
    CANCELLED = "cancelled"                  # 已取消
    STOCKOUT = "stockout_cancelled"          # 缺货取消


GOODS_STATUS_LABEL = {
    GoodsOrderStatus.PENDING.value: "待确认",
    GoodsOrderStatus.CONFIRMED.value: "已确认",
    GoodsOrderStatus.READY.value: "待取货",
    GoodsOrderStatus.COMPLETED.value: "已完成",
    GoodsOrderStatus.CANCELLED.value: "已取消",
    GoodsOrderStatus.STOCKOUT.value: "缺货取消",
}

GOODS_TRANSITIONS: dict[str, set[str]] = {
    GoodsOrderStatus.PENDING.value: {
        GoodsOrderStatus.CONFIRMED.value, GoodsOrderStatus.CANCELLED.value,
    },
    GoodsOrderStatus.CONFIRMED.value: {
        GoodsOrderStatus.READY.value, GoodsOrderStatus.CANCELLED.value,
        GoodsOrderStatus.STOCKOUT.value,
    },
    GoodsOrderStatus.READY.value: {
        GoodsOrderStatus.COMPLETED.value, GoodsOrderStatus.CANCELLED.value,
    },
    # 终态：completed / cancelled / stockout_cancelled
}

GOODS_REASON_REQUIRED_STATUS = {
    GoodsOrderStatus.CANCELLED.value,
    GoodsOrderStatus.STOCKOUT.value,
}

# 占用库存的状态（下单即占用，取消释放，核销时不再重复扣减）
GOODS_ACTIVE_STATUS = {
    GoodsOrderStatus.PENDING.value,
    GoodsOrderStatus.CONFIRMED.value,
    GoodsOrderStatus.READY.value,
}

GOODS_TERMINAL_STATUS = {
    GoodsOrderStatus.COMPLETED.value,
    GoodsOrderStatus.CANCELLED.value,
    GoodsOrderStatus.STOCKOUT.value,
}


class GoodsPayStatus(StrEnum):
    UNPAID = "unpaid"                    # 未支付（暂不接支付）
    PAID_OFFLINE = "paid_offline"        # 线下已收款
    REFUNDED_OFFLINE = "refunded_offline"  # 线下已退款


GOODS_PAY_LABEL = {
    GoodsPayStatus.UNPAID.value: "未支付",
    GoodsPayStatus.PAID_OFFLINE.value: "线下已收款",
    GoodsPayStatus.REFUNDED_OFFLINE.value: "线下已退款",
}


class PickupMethod(StrEnum):
    SELF = "self"          # 到店自提
    DELIVERY = "delivery"  # 门店配送


PICKUP_METHOD_LABEL = {
    PickupMethod.SELF.value: "到店自提",
    PickupMethod.DELIVERY.value: "门店配送",
}

PRODUCT_CATEGORY_LABEL = {
    "basic_food": "主粮", "snack": "零食", "toy": "玩具", "clean": "清洁",
    "clothes": "服饰", "health": "保健", "daily": "日用",
}

PRODUCT_STAGE_LABEL = {"puppy": "幼年", "adult": "成年", "senior": "老年", "all": "全期"}
PRODUCT_SIZE_LABEL = {"small": "小型", "medium": "中型", "large": "大型", "all": "全犬种"}


# ---------------------------------------------------------------- 宠物实景（V7.3）
CAMERA_PROVIDER_LABEL = {
    "local_webcam": "门店电脑摄像头（简版：本机采集 + 后端转发）",
    "rtsp_hls": "网络摄像头 RTSP → FFmpeg → HLS（正式版，预留）",
    "cloud_live": "云厂商直播服务（可选，预留）",
}

CAMERA_STATUS_LABEL = {
    "online": "在线", "offline": "离线", "disabled": "已停用",
}

# 可观看的寄养状态（离店即失效）
CAMERA_VIEWABLE_BOARDING_STATUS = {
    BoardingOrderStatus.CHECKED_IN.value,
    BoardingOrderStatus.WAITING_PICKUP.value,
}


class SettingKey(StrEnum):
    CANCEL_WINDOW_HOURS = "cancel_window_hours"
    DEFAULT_SLOT_CAPACITY = "default_slot_capacity"
    NO_SHOW_THRESHOLD = "no_show_threshold"
    MAX_RESCHEDULE_TIMES = "max_reschedule_times"
    STAFF_CONFIRM_TIMEOUT_HOURS = "staff_confirm_timeout_hours"
    SESSION_RETENTION_DAYS = "session_retention_days"
    AUTO_CANCEL_ON_TIMEOUT = "auto_cancel_on_timeout"
    CHURN_DAYS = "churn_days"
    VACCINE_REMIND_DAYS = "vaccine_remind_days"
    # ---- 宠物寄养（V7.1）：定价与规则全部可配，不硬编码 ----
    BOARD_MIN_NIGHTS = "board_min_nights"
    BOARD_PRICE_CAT = "board_price_cat"
    BOARD_PRICE_SMALL = "board_price_small"
    BOARD_PRICE_MEDIUM = "board_price_medium"
    BOARD_PRICE_LARGE = "board_price_large"
    BOARD_PRICE_GIANT = "board_price_giant"
    BOARD_LONG_STAY_DAYS = "board_long_stay_days"
    BOARD_LONG_STAY_PERCENT = "board_long_stay_percent"
    BOARD_HOLIDAY_DATES = "board_holiday_dates"
    BOARD_HOLIDAY_PERCENT = "board_holiday_percent"
    BOARD_PICKUP_FEE = "board_pickup_fee"
    BOARD_RETURN_FEE = "board_return_fee"
    BOARD_PREMIUM_FEE = "board_premium_fee"
    BOARD_PRESCRIPTION_FEE = "board_prescription_fee"
    # ---- 宠物用品（V7.2）----
    GOODS_DELIVERY_FEE = "goods_delivery_fee"
    GOODS_STOCK_WARN_DEFAULT = "goods_stock_warn_default"
    GOODS_LOW_STOCK_ALERT = "goods_low_stock_alert"
    # ---- 宠物实景（V7.3）：隐私与带宽红线 ----
    CAMERA_MAX_STREAMS_PER_ORDER = "camera_max_streams_per_order"
    CAMERA_TOKEN_TTL_SECONDS = "camera_token_ttl_seconds"
    CAMERA_VIEW_START_HOUR = "camera_view_start_hour"
    CAMERA_VIEW_END_HOUR = "camera_view_end_hour"
    CAMERA_FRAME_FPS = "camera_frame_fps"
    CAMERA_SNAPSHOT_RETENTION_DAYS = "camera_snapshot_retention_days"
    CAMERA_OFFLINE_MINUTES = "camera_offline_minutes"
    CAMERA_DEMO_MODE = "camera_demo_mode"


class SettingValueType(StrEnum):
    INT = "int"
    BOOL = "bool"
    STRING = "string"


class SettingRule:
    """门店配置项的元数据：类型 + 取值范围 + 中文说明。后端保存前据此校验，非法值拒绝并回退默认值。"""

    __slots__ = ("key", "value_type", "default", "desc", "min", "max")

    def __init__(self, key, value_type, default, desc, min=None, max=None):
        self.key = key
        self.value_type = value_type
        self.default = default
        self.desc = desc
        self.min = min
        self.max = max


SETTING_RULES: dict[str, SettingRule] = {
    SettingKey.CANCEL_WINDOW_HOURS.value: SettingRule(
        SettingKey.CANCEL_WINDOW_HOURS.value, SettingValueType.INT, "4",
        "距预约开始时间小于该小时数时，宠主不可自助取消", 0, 168),
    SettingKey.DEFAULT_SLOT_CAPACITY.value: SettingRule(
        SettingKey.DEFAULT_SLOT_CAPACITY.value, SettingValueType.INT, "3",
        "单个时段（1 小时）最大可接待的洗护订单数", 1, 50),
    SettingKey.NO_SHOW_THRESHOLD.value: SettingRule(
        SettingKey.NO_SHOW_THRESHOLD.value, SettingValueType.INT, "3",
        "同一宠主累计爽约达到该次数后进入限制名单", 1, 20),
    SettingKey.MAX_RESCHEDULE_TIMES.value: SettingRule(
        SettingKey.MAX_RESCHEDULE_TIMES.value, SettingValueType.INT, "2",
        "单个预约允许的最大改期次数", 0, 10),
    SettingKey.STAFF_CONFIRM_TIMEOUT_HOURS.value: SettingRule(
        SettingKey.STAFF_CONFIRM_TIMEOUT_HOURS.value, SettingValueType.INT, "2",
        "待确认预约超过该小时数触发店员升级提醒", 1, 72),
    SettingKey.SESSION_RETENTION_DAYS.value: SettingRule(
        SettingKey.SESSION_RETENTION_DAYS.value, SettingValueType.INT, "90",
        "会话数据留存天数，到期由异步任务物理删除", 1, 365),
    SettingKey.AUTO_CANCEL_ON_TIMEOUT.value: SettingRule(
        SettingKey.AUTO_CANCEL_ON_TIMEOUT.value, SettingValueType.BOOL, "true",
        "超时未确认是否自动取消预约（不计入爽约）", None, None),
    SettingKey.CHURN_DAYS.value: SettingRule(
        SettingKey.CHURN_DAYS.value, SettingValueType.INT, "60",
        "超过该天数无已完成洗护记录的宠物进入流失预警名单", 7, 365),
    SettingKey.VACCINE_REMIND_DAYS.value: SettingRule(
        SettingKey.VACCINE_REMIND_DAYS.value, SettingValueType.INT, "7",
        "疫苗 / 驱虫记录到期前多少天开始提醒宠主（定时任务使用）", 1, 60),
    # ---- 宠物寄养（V7.1）----
    SettingKey.BOARD_MIN_NIGHTS.value: SettingRule(
        SettingKey.BOARD_MIN_NIGHTS.value, SettingValueType.INT, "2",
        "寄养最少入住晚数", 1, 30),
    SettingKey.BOARD_PRICE_CAT.value: SettingRule(
        SettingKey.BOARD_PRICE_CAT.value, SettingValueType.INT, "30",
        "猫的寄养日费基准价（元/晚，标准房型 1.0 系数）", 0, 2000),
    SettingKey.BOARD_PRICE_SMALL.value: SettingRule(
        SettingKey.BOARD_PRICE_SMALL.value, SettingValueType.INT, "40",
        "小型犬寄养日费基准价（元/晚，≤7.5kg）", 0, 2000),
    SettingKey.BOARD_PRICE_MEDIUM.value: SettingRule(
        SettingKey.BOARD_PRICE_MEDIUM.value, SettingValueType.INT, "50",
        "中型犬寄养日费基准价（元/晚，7.5–20kg）", 0, 2000),
    SettingKey.BOARD_PRICE_LARGE.value: SettingRule(
        SettingKey.BOARD_PRICE_LARGE.value, SettingValueType.INT, "60",
        "大型犬寄养日费基准价（元/晚，20–30kg）", 0, 2000),
    SettingKey.BOARD_PRICE_GIANT.value: SettingRule(
        SettingKey.BOARD_PRICE_GIANT.value, SettingValueType.INT, "70",
        "超大型犬寄养日费基准价（元/晚，>30kg）", 0, 2000),
    SettingKey.BOARD_LONG_STAY_DAYS.value: SettingRule(
        SettingKey.BOARD_LONG_STAY_DAYS.value, SettingValueType.INT, "18",
        "长住折扣起始晚数（达到该晚数按长住折扣计价）", 1, 365),
    SettingKey.BOARD_LONG_STAY_PERCENT.value: SettingRule(
        SettingKey.BOARD_LONG_STAY_PERCENT.value, SettingValueType.INT, "90",
        "长住折扣百分比（90 表示 9 折）", 10, 100),
    SettingKey.BOARD_HOLIDAY_DATES.value: SettingRule(
        SettingKey.BOARD_HOLIDAY_DATES.value, SettingValueType.STRING, "",
        "节假日日期列表（逗号分隔 YYYY-MM-DD），这些日期按节假日系数计价", None, None),
    SettingKey.BOARD_HOLIDAY_PERCENT.value: SettingRule(
        SettingKey.BOARD_HOLIDAY_PERCENT.value, SettingValueType.INT, "130",
        "节假日系数百分比（130 表示 1.3 倍）", 100, 300),
    SettingKey.BOARD_PICKUP_FEE.value: SettingRule(
        SettingKey.BOARD_PICKUP_FEE.value, SettingValueType.INT, "30",
        "上门接宠费（元/次）", 0, 500),
    SettingKey.BOARD_RETURN_FEE.value: SettingRule(
        SettingKey.BOARD_RETURN_FEE.value, SettingValueType.INT, "30",
        "送宠到家费（元/次）", 0, 500),
    SettingKey.BOARD_PREMIUM_FEE.value: SettingRule(
        SettingKey.BOARD_PREMIUM_FEE.value, SettingValueType.INT, "10",
        "升级粮每日加价（元/晚）", 0, 500),
    SettingKey.BOARD_PRESCRIPTION_FEE.value: SettingRule(
        SettingKey.BOARD_PRESCRIPTION_FEE.value, SettingValueType.INT, "20",
        "处方餐每日加价（元/晚）", 0, 500),
    # ---- 宠物用品（V7.2）----
    SettingKey.GOODS_DELIVERY_FEE.value: SettingRule(
        SettingKey.GOODS_DELIVERY_FEE.value, SettingValueType.INT, "10",
        "用品配送到家费用（元/单，自提为 0）", 0, 200),
    SettingKey.GOODS_STOCK_WARN_DEFAULT.value: SettingRule(
        SettingKey.GOODS_STOCK_WARN_DEFAULT.value, SettingValueType.INT, "5",
        "新增 SKU 的默认库存预警阈值", 0, 1000),
    SettingKey.GOODS_LOW_STOCK_ALERT.value: SettingRule(
        SettingKey.GOODS_LOW_STOCK_ALERT.value, SettingValueType.BOOL, "true",
        "库存低于阈值时是否提醒店长（消息中心）", None, None),
    # ---- 宠物实景（V7.3）----
    SettingKey.CAMERA_MAX_STREAMS_PER_ORDER.value: SettingRule(
        SettingKey.CAMERA_MAX_STREAMS_PER_ORDER.value, SettingValueType.INT, "2",
        "单个寄养订单同时允许的观看路数（防账号共享）", 1, 10),
    SettingKey.CAMERA_TOKEN_TTL_SECONDS.value: SettingRule(
        SettingKey.CAMERA_TOKEN_TTL_SECONDS.value, SettingValueType.INT, "300",
        "观看凭证有效期（秒），过期需重新获取", 60, 3600),
    SettingKey.CAMERA_VIEW_START_HOUR.value: SettingRule(
        SettingKey.CAMERA_VIEW_START_HOUR.value, SettingValueType.INT, "8",
        "允许观看的起始整点（避免打扰宠物休息）", 0, 23),
    SettingKey.CAMERA_VIEW_END_HOUR.value: SettingRule(
        SettingKey.CAMERA_VIEW_END_HOUR.value, SettingValueType.INT, "22",
        "允许观看的结束整点", 1, 24),
    SettingKey.CAMERA_FRAME_FPS.value: SettingRule(
        SettingKey.CAMERA_FRAME_FPS.value, SettingValueType.INT, "5",
        "推流帧率（fps），门店上行带宽不足时下调", 1, 15),
    SettingKey.CAMERA_SNAPSHOT_RETENTION_DAYS.value: SettingRule(
        SettingKey.CAMERA_SNAPSHOT_RETENTION_DAYS.value, SettingValueType.INT, "30",
        "抓拍留存天数，到期由定时任务清理", 1, 365),
    SettingKey.CAMERA_OFFLINE_MINUTES.value: SettingRule(
        SettingKey.CAMERA_OFFLINE_MINUTES.value, SettingValueType.INT, "10",
        "设备心跳超时判离线的分钟数", 1, 120),
    # 演示环境没有真实摄像头推流时，服务端合成带时间戳的「演示画面」，
    # 让宠主端能看到播放器、抓拍、相册全链路；画面本身有明确标注，不冒充真实监控。
    SettingKey.CAMERA_DEMO_MODE.value: SettingRule(
        SettingKey.CAMERA_DEMO_MODE.value, SettingValueType.BOOL, "true",
        "无真实推流时是否显示演示画面（门店接入真摄像头后建议关闭）", None, None),
}
