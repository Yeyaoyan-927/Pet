"""宠物寄养（V7.1）：房型 / 订单 / 照护计划 / 照护日志 / 接送任务。

金额统一以**分**（Integer）存储与计算 —— 定价含百分比系数（房型、节假日、长住折扣），
用浮点会把 40×1.3×1.2 这类乘法算出误差，金额一律不做浮点运算。
对外输出时同时给 `*_cents`（分）与展示用元值（见 boarding_service.to_out）。
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class BoardingRoom(Base, TimestampMixin):
    """宠舍（房型 + 具体房间）。房型系数决定定价，房号决定房态。"""

    __tablename__ = "boarding_room"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    room_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, comment="房号")
    room_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment="standard 标准单间 / garden 花园景房 / sunny 阳光房 / vip 套房",
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="房型展示名")
    species_limit: Mapped[str] = mapped_column(
        String(10), nullable=False, default="all", comment="适配物种 dog / cat / all"
    )
    weight_limit: Mapped[int | None] = mapped_column(Integer, comment="最大适配体重（kg）")
    ratio_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, comment="房型系数百分比：100=1.0 倍，120=1.2 倍"
    )
    capacity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="可容纳宠物数（未绝育 / 攻击倾向强制 1）"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="idle", index=True,
        comment="idle 空闲 / occupied 占用中 / cleaning 清洁中 / maintenance 维护中",
    )
    facilities: Mapped[str | None] = mapped_column(String(255), comment="设施标签，逗号分隔")
    remark: Mapped[str | None] = mapped_column(String(255), comment="备注")


class BoardingOrder(Base, TimestampMixin):
    """寄养订单。状态机见 constants.BOARDING_TRANSITIONS，非法流转一律 409。"""

    __tablename__ = "boarding_order"
    __table_args__ = (
        Index("idx_board_date_status", "check_in_date", "check_out_date", "status"),
        Index("idx_board_room_status", "room_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, comment="寄养单号")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="宠主 ID")
    pet_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="宠物 ID")
    room_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="宠舍 ID")
    room_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="房型快照")
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", index=True, comment="寄养状态"
    )

    check_in_date: Mapped[date] = mapped_column(Date, nullable=False, comment="入住日期")
    check_out_date: Mapped[date] = mapped_column(Date, nullable=False, comment="离店日期")
    nights: Mapped[int] = mapped_column(Integer, nullable=False, comment="寄养晚数")

    # 喂食
    feeding_plan: Mapped[str] = mapped_column(
        String(16), nullable=False, default="self", comment="self / standard / premium / prescription"
    )
    food_note: Mapped[str | None] = mapped_column(String(255), comment="自备食物明细与喂食说明")

    # 接送
    shipping_method: Mapped[str] = mapped_column(
        String(16), nullable=False, default="self",
        comment="历史字段（兼容旧数据）：self 自送 / pickup 上门接 / return 送宠到家",
    )
    # 送宠到店与离店接宠拆成两组，各自单选（用户可自行送到 + 自行接取，也可组合）
    dropoff_method: Mapped[str] = mapped_column(
        String(16), nullable=False, default="self", comment="送宠到店：self 自行送到 / pickup 上门接宠"
    )
    pickup_back_method: Mapped[str] = mapped_column(
        String(16), nullable=False, default="self", comment="离店接宠：self 自行接取 / return 送宠到家"
    )
    shipping_address: Mapped[str | None] = mapped_column(String(255), comment="接送地址")
    shipping_slot: Mapped[str | None] = mapped_column(String(32), comment="上门时间段，如 10:00-12:00")
    shipping_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="接送费（分）")

    # 费用（全部分单位，整数计算）
    daily_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="日均费用（分）")
    subtotal_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="房费小计（分）")
    discount_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, comment="已应用折扣百分比（100=无折扣，90=9 折）"
    )
    extra_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="增值项（分）")
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="应付总额（分）")
    settle_note: Mapped[str | None] = mapped_column(String(255), comment="结算说明（提前接回 / 延期等）")

    # 合规与安全（下单快照，便于事后追溯当时的判定依据）
    vaccine_ok: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, comment="下单时疫苗是否完整：1 是"
    )
    vaccine_note: Mapped[str | None] = mapped_column(String(255), comment="疫苗校验说明")
    isolate_required: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, comment="需隔离观察（皮肤病史等）：1 是"
    )
    risk_level: Mapped[str | None] = mapped_column(String(16), comment="下单时风险等级快照")
    emergency_contact: Mapped[str | None] = mapped_column(String(50), comment="紧急联系人")
    emergency_phone_encrypted: Mapped[str | None] = mapped_column(String(255), comment="紧急联系电话（AES 密文）")
    medical_authorized: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, comment="授权就医：1 是"
    )
    terms_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, comment="条款确认时间")
    terms_ip: Mapped[str | None] = mapped_column(String(64), comment="条款确认 IP（留证）")

    staff_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="负责店员")
    checkin_at: Mapped[datetime | None] = mapped_column(DateTime, comment="实际入住时间")
    checkout_at: Mapped[datetime | None] = mapped_column(DateTime, comment="实际离店时间")
    checkin_note: Mapped[str | None] = mapped_column(String(255), comment="入住健康初检记录")
    checkout_note: Mapped[str | None] = mapped_column(String(255), comment="退房物品清点与消杀记录")
    terminate_reason: Mapped[str | None] = mapped_column(String(255), comment="异常终止原因（必填于终止类）")
    cancel_reason: Mapped[str | None] = mapped_column(String(255), comment="取消 / 爽约原因")
    extend_times: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="延期次数")
    idempotent_key: Mapped[str | None] = mapped_column(String(64), unique=True, comment="幂等键")
    remark: Mapped[str | None] = mapped_column(Text, comment="备注")


class BoardingCarePlan(Base, TimestampMixin):
    """照护计划条目：用药 / 喂食 / 遛放 / 禁忌。多条可增删，需店员操作的会进每日待办。"""

    __tablename__ = "boarding_care_plan"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="寄养订单 ID")
    item_type: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="medication 用药 / feeding 喂食 / walk 遛放 / taboo 禁忌"
    )
    content: Mapped[str] = mapped_column(String(255), nullable=False, comment="内容（药名剂量 / 要求）")
    frequency: Mapped[str | None] = mapped_column(String(64), comment="频次，如 每日 2 次")
    need_staff: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, comment="需店员操作：1 是")
    sort_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="排序")


class BoardingCareLog(Base, TimestampMixin):
    """每日照护日志 —— 寄养体验的核心，也是行业差评重灾区。异常记录会即时推送宠主与店长。"""

    __tablename__ = "boarding_care_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="寄养订单 ID")
    log_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="日志日期")
    eating: Mapped[str | None] = mapped_column(String(64), comment="进食：正常 / 偏少 / 拒食 + 份量")
    drinking: Mapped[str | None] = mapped_column(String(32), comment="饮水：正常 / 偏少 / 偏多")
    stool: Mapped[str | None] = mapped_column(String(64), comment="排便：次数与性状")
    spirit: Mapped[str | None] = mapped_column(String(32), comment="精神：活泼 / 正常 / 萎靡 / 焦躁")
    activity: Mapped[str | None] = mapped_column(String(64), comment="活动量：遛放次数与时长")
    abnormal: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, comment="是否异常：1 是（触发即时推送 + 店长关注）"
    )
    abnormal_note: Mapped[str | None] = mapped_column(String(255), comment="异常描述")
    photos: Mapped[str | None] = mapped_column(String(512), comment="照片地址，逗号分隔（每日至少 1 张）")
    sop_checked: Mapped[str | None] = mapped_column(String(255), comment="已完成的 SOP 检查项，逗号分隔")
    staff_id: Mapped[int | None] = mapped_column(BigInteger, comment="记录人")


class BoardingPickupTask(Base, TimestampMixin):
    """接送任务：待出发 → 已出发 → 已接到 → 已送达，含宠主签收。"""

    __tablename__ = "boarding_pickup_task"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="寄养订单 ID")
    task_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="pickup 上门接 / return 送宠到家")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True, comment="任务状态"
    )
    address: Mapped[str | None] = mapped_column(String(255), comment="接送地址")
    slot_time: Mapped[str | None] = mapped_column(String(32), comment="约定时间段")
    staff_id: Mapped[int | None] = mapped_column(BigInteger, comment="指派店员")
    fee_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="费用（分）")
    departed_at: Mapped[datetime | None] = mapped_column(DateTime, comment="出发时间")
    picked_at: Mapped[datetime | None] = mapped_column(DateTime, comment="接到时间")
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime, comment="送达时间")
    sign_off_by: Mapped[str | None] = mapped_column(String(50), comment="宠主签收人")
    remark: Mapped[str | None] = mapped_column(String(255), comment="备注")


class BoardingEarlyPickup(Base, TimestampMixin):
    """提前接回申请：宠主发起 → 店员 / 店长审核。

    V8.4.9 之前「提前接回」是店员直接推进状态（一句话就改），宠主完全不知情。
    现在改成申请制：宠主在订单详情提交期望日期与原因，门店审核通过后才执行状态流转，
    驳回要写意见 —— 谁提的、谁批的、为什么，全都留痕。
    """

    __tablename__ = "boarding_early_pickup"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="寄养订单 ID")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="申请宠主 ID")
    expect_pickup_date: Mapped[date] = mapped_column(Date, nullable=False, comment="期望接回日期")
    reason: Mapped[str | None] = mapped_column(String(255), comment="申请原因")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True,
        comment="pending 待审核 / approved 已通过 / rejected 已驳回",
    )
    review_note: Mapped[str | None] = mapped_column(String(255), comment="审核意见")
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, comment="审核人")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, comment="审核时间")
