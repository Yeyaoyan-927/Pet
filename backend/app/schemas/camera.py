"""宠物实景请求模型（V7.3）。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class CameraDeviceIn(BaseModel):
    room_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=60)
    provider_type: str = Field(default="local_webcam", description="local_webcam / rtsp_hls / cloud_live")
    stream_url: str | None = Field(default=None, max_length=255, description="RTSP/HLS 地址（正式版预留）")
    fps: int = Field(default=5, ge=1, le=15)
    resolution: str = Field(default="640x480", max_length=20)

    @field_validator("provider_type")
    @classmethod
    def check_provider(cls, v: str) -> str:
        if v not in {"local_webcam", "rtsp_hls", "cloud_live"}:
            raise ValueError("采集方式必须是 local_webcam / rtsp_hls / cloud_live")
        return v


class CameraSessionIn(BaseModel):
    order_id: int = Field(gt=0, description="寄养订单 ID")


class SnapshotIn(BaseModel):
    order_id: int = Field(gt=0)
    image_url: str = Field(min_length=1, max_length=255, description="抓拍图片地址")
    note: str | None = Field(default=None, max_length=255)
