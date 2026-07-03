"""站内消息 Schema。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str | None = None
    msg_type: str
    msg_type_label: str | None = None
    biz_id: int | None = None
    is_read: int = 0
    read_at: datetime | None = None
    created_at: datetime | None = None


class UnreadCountOut(BaseModel):
    unread: int = 0
