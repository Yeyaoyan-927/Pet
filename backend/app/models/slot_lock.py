"""时段锁行表：给「日期 + 时段」这一稀缺资源一个可加行锁的实体。

为什么需要它：
- 预约创建是 check-then-act（先 count 校验容量，再 insert），两个并发请求会同时通过校验，
  最终写入超额订单（超卖）。
- 解决方案对比：
  · MySQL `GET_LOCK()`：连接级命名锁，需要显式释放，忘记释放会占满连接；
  · Redis 分布式锁：引入新中间件，本地开发与交付成本高；
  · **锁行表 + `SELECT ... FOR UPDATE`**：锁随事务提交/回滚自动释放，跨数据库通用，零新依赖。

用法：写入前先 `INSERT ... ON DUPLICATE KEY UPDATE` 保证锁行存在，再 `FOR UPDATE` 锁住该行，
释放前完成容量校验与插入 —— 并发请求会被串行化到同一事务边界内。
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SlotLock(Base, TimestampMixin):
    __tablename__ = "slot_lock"
    __table_args__ = (
        UniqueConstraint("appoint_date", "slot_time", name="uk_slot_lock_date_time"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    appoint_date: Mapped[date] = mapped_column(Date, nullable=False, comment="预约日期")
    slot_time: Mapped[str] = mapped_column(String(5), nullable=False, comment="时段 HH:00")
