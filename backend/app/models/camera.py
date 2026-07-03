"""宠物实景（V7.3）：设备 / 观看会话 / 抓拍。

**技术现实（必须写清楚，避免规划落空）**：
浏览器的 `getUserMedia` 只能打开「当前这台电脑」的摄像头，打不开门店的摄像头。
所以链路是：**门店端采集 → 后端转发 → 宠主端播放**，而不是「宠主端打开摄像头」。

简版实现（本版）：
- 门店端页面 `getUserMedia` 抓帧 → `POST /camera/frames/{token}` 上传 JPEG
- 后端**仅在内存缓存最新帧**（不落盘）→ 宠主端拉 `GET /camera/stream/{token}` 的 MJPEG 流
- `camera_device.provider_type` 预留 RTSP→HLS / 云直播，接真摄像头时业务代码零改动

隐私红线（`camera_session` 承载）：
只能看自己的在住宠物、凭证 5 分钟过期、单订单限 2 路、观看全留痕、画面带手机号后四位浮水印、默认不录制。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class CameraDevice(Base, TimestampMixin):
    """摄像头设备：绑定宠舍。`provider_type` 隔离采集方式的差异。"""

    __tablename__ = "camera_device"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="绑定的宠舍 ID")
    name: Mapped[str] = mapped_column(String(60), nullable=False, comment="设备名，如 花园景房 B201 摄像头")
    provider_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="local_webcam",
        comment="local_webcam 门店电脑采集 / rtsp_hls 网络摄像头（预留）/ cloud_live 云直播（预留）",
    )
    stream_url: Mapped[str | None] = mapped_column(String(255), comment="正式版 RTSP/HLS 地址（预留）")
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="offline", index=True, comment="online / offline / disabled"
    )
    enabled: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="1 启用")
    fps: Mapped[int] = mapped_column(Integer, nullable=False, default=5, comment="采集帧率")
    resolution: Mapped[str] = mapped_column(String(20), nullable=False, default="640x480", comment="分辨率")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, comment="最近心跳时间")
    remark: Mapped[str | None] = mapped_column(String(255), comment="备注")


class CameraSession(Base, TimestampMixin):
    """观看会话 = 观看留痕。`token` 是独立于 JWT 的短期凭证（防转发）。"""

    __tablename__ = "camera_session"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="寄养订单 ID")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="观看人（宠主）")
    device_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="设备 ID")
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="短期观看凭证")
    token_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="凭证过期时间")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, comment="开始观看时间")
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, comment="结束时间")
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="观看时长（秒）")
    frames: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="已转发帧数")
    ip: Mapped[str | None] = mapped_column(String(64), comment="来源 IP（留痕）")
    user_agent: Mapped[str | None] = mapped_column(String(255), comment="UA 摘要（留痕）")


class CameraSnapshot(Base, TimestampMixin):
    """一键抓拍：只存地址与元信息，图片走既有照片存储（本版存 URL）。"""

    __tablename__ = "camera_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="寄养订单 ID")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="抓拍人")
    device_id: Mapped[int | None] = mapped_column(BigInteger, comment="设备 ID")
    image_url: Mapped[str] = mapped_column(String(255), nullable=False, comment="图片地址")
    note: Mapped[str | None] = mapped_column(Text, comment="备注")
