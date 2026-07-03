"""报表统计 Schema。"""
from __future__ import annotations

from pydantic import BaseModel


class TrendPoint(BaseModel):
    label: str
    value: float


class StaffWorkload(BaseModel):
    staff_id: int
    staff_name: str
    finished_count: int


class ChurnPet(BaseModel):
    pet_id: int
    pet_name: str
    owner_name: str | None = None
    last_wash_date: str | None = None
    idle_days: int | None = None


class ReportSummaryOut(BaseModel):
    range_start: str
    range_end: str
    total_orders: int          # 已确认及以上状态订单
    completed_orders: int      # 已完成
    cancelled_orders: int
    no_show_orders: int
    no_show_rate: float        # 爽约订单 / 已确认订单总数
    repurchase_rate: float     # 同宠物历史至少 2 次已完成洗护
    service_ratio: list[TrendPoint]
    status_distribution: list[TrendPoint]
    daily_trend: list[TrendPoint]
    peak_hours: list[TrendPoint]
    staff_workload: list[StaffWorkload]
    churn_pets: list[ChurnPet]
    risk_high_count: int
