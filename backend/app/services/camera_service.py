"""宠物实景业务服务（V7.3）。

链路（简版）：门店端 `getUserMedia` 抓帧 → `push_frame()` → 内存缓存最新帧
→ 宠主端 `stream()` 拉 MJPEG。**实时流默认不落盘**，后端只做转发。

隐私红线全部在这里落地：
- 只能看自己的、在住期间的寄养宠物；
- 只能看该宠物**所在宠舍**绑定的设备（不允许任选设备）；
- 短期凭证（默认 5 分钟，独立于 JWT，防转发）；
- 单订单并发观看上限（默认 2 路）；
- 观看时段限制；
- 每次观看都写 `camera_session` + 审计日志（谁、何时、看了多久）。
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    CAMERA_PROVIDER_LABEL,
    CAMERA_STATUS_LABEL,
    CAMERA_VIEWABLE_BOARDING_STATUS,
    MessageType,
    UserRole,
)
from app.models import (
    BoardingOrder,
    BoardingRoom,
    CameraDevice,
    CameraSession,
    CameraSnapshot,
    Pet,
    User,
)
from app.services import message_service, setting_service
from app.services.audit_service import write_log
from app.utils.datetime_util import gen_random_str, now
from app.utils.exceptions import BizError, ConflictError, NotFoundError, PermissionError_
from app.utils.logger import logger

# 内存最新帧：**寄养订单 id** -> (jpeg bytes, 时间戳)。进程内存储，多实例不共享（见 docs/09 限制说明）。
# 为什么按订单而不是按观看凭证：推流的是店员端的会话、拉流的是宠主端的会话，
# 两边 token 天然不同。早先按 token 存帧，生产者与消费者永远对不上，
# 宠主端一次都没拿到过画面（V8.2.1 定位到「点观看没画面」的真正原因）。
FRAME_HUB: dict[int, tuple[bytes, datetime]] = {}
# 帧 TTL：超过 10 秒没有新帧视为离线（避免播放器一直停在旧画面）
FRAME_TTL_SECONDS = 10


class FrameHub:
    """最小可用的单帧缓存（按寄养订单推一帧、拉多次）。"""

    @staticmethod
    def put(order_id: int, data: bytes) -> None:
        """写入某订单的最新一帧（只存内存，实时流不落盘）。"""
        FRAME_HUB[order_id] = (data, now())
        # 防内存无限增长：超过 500 个订单时清掉过期项
        if len(FRAME_HUB) > 500:
            deadline = now() - timedelta(seconds=FRAME_TTL_SECONDS * 6)
            for key in [k for k, (_, ts) in FRAME_HUB.items() if ts < deadline]:
                FRAME_HUB.pop(key, None)

    @staticmethod
    def get(order_id: int) -> bytes | None:
        """读取某订单的最新一帧，没有则返回 None（拉流端据此判断是否已开始推流）。"""
        item = FRAME_HUB.get(order_id)
        if item is None:
            return None
        data, ts = item
        if (now() - ts).total_seconds() > FRAME_TTL_SECONDS:
            return None  # 过期帧不给，避免误导
        return data

    @staticmethod
    def drop(order_id: int) -> None:
        """丢弃某订单的帧缓存（全部会话结束后释放内存）。"""
        FRAME_HUB.pop(order_id, None)


# ---------------------------------------------------------------- 设备
async def list_devices(db: AsyncSession) -> list[dict]:
    """设备列表（含所在房号），供店长巡检与采集页选择。"""
    rows = (await db.execute(select(CameraDevice).order_by(CameraDevice.id))).scalars().all()
    rooms = {r.id: r for r in (await db.execute(select(BoardingRoom))).scalars().all()}
    return [device_to_out(d, rooms.get(d.room_id)) for d in rows]


def device_to_out(device: CameraDevice, room=None) -> dict:
    """设备序列化：补房号、状态中文名与 provider 中文名。"""
    return {
        "id": device.id, "room_id": device.room_id,
        "room_no": getattr(room, "room_no", None),
        "name": device.name, "provider_type": device.provider_type,
        "provider_label": CAMERA_PROVIDER_LABEL.get(device.provider_type, device.provider_type),
        "status": device.status, "status_label": CAMERA_STATUS_LABEL.get(device.status, device.status),
        "enabled": device.enabled, "fps": device.fps, "resolution": device.resolution,
        "stream_url": device.stream_url,
        "last_heartbeat_at": device.last_heartbeat_at,
        "implemented": device.provider_type == "local_webcam",
    }


async def upsert_device(db: AsyncSession, payload, operator: User, request: Request | None = None) -> dict:
    """给宠舍绑定摄像头：**一个宠舍只允许一台**，重复提交按 room_id 更新而不是新增。"""
    room = (await db.execute(select(BoardingRoom).where(BoardingRoom.id == payload.room_id))).scalars().first()
    if room is None:
        raise NotFoundError("宠舍不存在")

    device = (await db.execute(
        select(CameraDevice).where(CameraDevice.room_id == payload.room_id)
    )).scalars().first()
    if device is None:
        device = CameraDevice(**payload.model_dump())
        db.add(device)
    else:
        for key, value in payload.model_dump().items():
            setattr(device, key, value)
    await db.flush()
    await write_log(db, module="camera", action="upsert_device", user_id=operator.id,
                    biz_id=device.id, after=payload.model_dump(), request=request)
    await db.commit()
    return device_to_out(device, room)


async def set_device_status(db: AsyncSession, device_id: int, status: str, operator: User,
                            request: Request | None = None) -> dict:
    """手动改设备状态（在线/离线/停用），非法值直接拒绝。"""
    if status not in {"online", "offline", "disabled"}:
        raise BizError("设备状态不合法")
    device = (await db.execute(select(CameraDevice).where(CameraDevice.id == device_id))).scalars().first()
    if device is None:
        raise NotFoundError("设备不存在")
    device.status = status
    if status != "disabled":
        device.enabled = 1 if status == "online" else device.enabled
    await write_log(db, module="camera", action=f"device_{status}", user_id=operator.id,
                    biz_id=device.id, after={"status": status}, request=request)
    await db.commit()
    return device_to_out(device)


async def heartbeat(db: AsyncSession, device_id: int) -> dict:
    """设备心跳（门店端采集页定时上报），用于在线率统计与离线判断。"""
    device = (await db.execute(select(CameraDevice).where(CameraDevice.id == device_id))).scalars().first()
    if device is None:
        raise NotFoundError("设备不存在")
    device.last_heartbeat_at = now()
    device.status = "online"
    await db.commit()
    return {"id": device.id, "status": device.status, "last_heartbeat_at": device.last_heartbeat_at}


# ---------------------------------------------------------------- 可观看列表
async def viewable_orders(db: AsyncSession, user: User) -> list[dict]:
    """当前可观看的在住寄养单（宠主只看自己的；店员/店长看全部）。"""
    cond = [BoardingOrder.status.in_(list(CAMERA_VIEWABLE_BOARDING_STATUS))]
    if user.role == UserRole.CUSTOMER.value:
        cond.append(BoardingOrder.user_id == user.id)
    orders = (await db.execute(select(BoardingOrder).where(*cond))).scalars().all()

    devices = {d.room_id: d for d in (await db.execute(select(CameraDevice))).scalars().all()}
    pets = {p.id: p for p in (await db.execute(
        select(Pet).where(Pet.id.in_([o.pet_id for o in orders]))
    )).scalars().all()} if orders else {}

    items = []
    for order in orders:
        device = devices.get(order.room_id)
        pet = pets.get(order.pet_id)
        reason = ""
        if device is None:
            reason = "该宠舍尚未安装摄像头"
        elif device.status == "disabled" or not device.enabled:
            reason = "该宠舍摄像头已停用"
        elif device.status != "online":
            reason = "该宠舍摄像头暂时离线，已通知店员"
        items.append({
            "order_id": order.id, "order_no": order.order_no,
            "pet_name": pet.name if pet else None, "pet_id": order.pet_id,
            "room_no": None, "room_id": order.room_id,
            "device_id": device.id if device else None,
            "provider_type": device.provider_type if device else None,
            "device_status": device.status if device else None,
            "can_watch": not reason,
            "reason": reason,
            "check_out_date": order.check_out_date,
        })
    return items


# ---------------------------------------------------------------- 观看凭证
async def issue_token(
    db: AsyncSession, order_id: int, user: User, request: Request | None = None
) -> dict:
    """签发观看凭证。这里的每一条校验都是隐私红线，缺一不可。"""
    order = (await db.execute(
        select(BoardingOrder).where(BoardingOrder.id == order_id)
    )).scalars().first()
    if order is None:
        raise NotFoundError("寄养订单不存在")

    # ① 只能看自己的
    if user.role == UserRole.CUSTOMER.value and order.user_id != user.id:
        raise PermissionError_("只能观看自己宠物的画面")

    # ② 只能在住期间看
    if order.status not in CAMERA_VIEWABLE_BOARDING_STATUS:
        raise BizError("该寄养单当前不在住，无法观看（离店后自动失效）")

    # ③ 只能看该宠物所在宠舍的设备
    device = (await db.execute(
        select(CameraDevice).where(CameraDevice.room_id == order.room_id)
    )).scalars().first()
    if device is None:
        raise NotFoundError("该宠舍尚未安装摄像头")
    if device.status == "disabled" or not device.enabled:
        raise BizError("该宠舍摄像头已停用")
    if device.status != "online":
        raise ConflictError("该宠舍摄像头暂时离线，已通知店员")

    # ④ 观看时段限制
    start_hour = await setting_service.get_int(db, "camera_view_start_hour")
    end_hour = await setting_service.get_int(db, "camera_view_end_hour")
    hour = now().hour
    if not start_hour <= hour < end_hour:
        raise BizError(f"当前不在可观看时段（{start_hour}:00 - {end_hour}:00），请稍后再看")

    # ⑤ 单订单并发观看上限
    limit = await setting_service.get_int(db, "camera_max_streams_per_order")
    # 注意：计数必须用 db.scalar() 取标量；db.execute() 返回的是 Result，
    # 直接 int(Result) 会抛 TypeError（本轮踩过）
    alive = int(await db.scalar(
        select(func.count()).select_from(CameraSession).where(
            CameraSession.order_id == order.id,
            CameraSession.token_expires_at > now(),
            CameraSession.ended_at.is_(None),
        )
    ) or 0)
    if alive >= limit:
        raise ConflictError(f"该订单同时最多 {limit} 路观看，请先关闭其他设备上的画面")

    ttl = await setting_service.get_int(db, "camera_token_ttl_seconds")
    token = gen_random_str(32)
    session = CameraSession(
        order_id=order.id, user_id=user.id, device_id=device.id, token=token,
        token_expires_at=now() + timedelta(seconds=ttl),
        started_at=now(), frames=0,
        ip=(request.client.host if request and request.client else None),
        user_agent=((request.headers.get("user-agent") or "")[:255] if request else None),
    )
    db.add(session)
    await db.flush()

    # 浮水印：手机号后四位（前端叠加），后端只提供内容
    from app.utils.crypto import decrypt_text

    phone = decrypt_text(user.phone_encrypted) or ""
    watermark = f"{phone[-4:] if len(phone) >= 4 else '****'} · {now().strftime('%m-%d %H:%M')}"

    await write_log(db, module="camera", action="watch_start", user_id=user.id,
                    biz_id=order.id, request=request, detail=f"device={device.id} session={session.id}")
    await db.commit()

    return {
        "session_id": session.id, "token": token, "expires_in": ttl,
        "stream_path": f"{settings.API_PREFIX}/camera/stream/{token}",
        "push_path": f"{settings.API_PREFIX}/camera/frames/{token}",
        "provider_type": device.provider_type,
        "fps": device.fps, "resolution": device.resolution,
        "watermark": watermark,
        "order_no": order.order_no, "pet_name": None,
        "device_id": device.id,
        # 前端据此决定播放方式：没有真实推流时后端返回单张演示画面，需要按帧轮询刷新
        "demo": FrameHub.get(order.id) is None and await setting_service.get_bool(
            db, "camera_demo_mode"
        ),
    }


async def _valid_session(db: AsyncSession, token: str) -> CameraSession:
    session = (await db.execute(
        select(CameraSession).where(CameraSession.token == token)
    )).scalars().first()
    if session is None:
        raise NotFoundError("观看凭证无效")
    if session.token_expires_at <= now():
        raise BizError("观看凭证已过期，请刷新页面重新获取")
    return session


async def push_frame(db: AsyncSession, token: str, data: bytes, operator: User) -> dict:
    """门店端推一帧（JPEG）。仅允许店员/店长，且凭证必须有效。

    帧按**寄养订单**存放：推流方是店员会话，观看方是宠主会话，token 不同但订单相同。
    """
    if operator.role == UserRole.CUSTOMER.value:
        raise PermissionError_("仅门店内部可以推送画面")
    if not data:
        raise BizError("帧数据为空")
    if len(data) > 2 * 1024 * 1024:
        raise BizError("单帧不能超过 2MB")
    session = await _valid_session(db, token)
    FrameHub.put(session.order_id, data)
    return {"ok": True, "bytes": len(data)}


# ---------------------------------------------------------------- 演示画面（无真实推流时兜底）
# 为什么需要：门店端没开采集 / 现场没有摄像头时，拉流会一直空转，
# 宠主端只能看到一个坏掉的 <img>（表现为「点了观看却没画面」）。
# 这里在无人推流时合成一张带时间戳的画面，保证「播放器 → 抓拍 → 相册」整条链路可演示；
# 画面左上角固定标注 DEMO，右下角带浮水印，不会被误认为真实监控。
_DEMO_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)
_DEMO_CACHE: dict[str, tuple[int, bytes]] = {}
# 演示帧的文字（宠物名 + 单号、浮水印）按会话缓存：轮询提到 5fps 后，
# 每帧都查两次库没必要，这类信息在观看期内不会变（V8.4.4 流畅度优化）
_DEMO_LABEL_CACHE: dict[int, tuple[float, tuple[str, str]]] = {}
_DEMO_LABEL_TTL = 60.0


def _demo_font(size: int):
    """按平台挑一个中文字体；找不到就退默认字体（只影响字形，不影响功能）。"""
    from PIL import ImageFont

    for path in _DEMO_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:  # pragma: no cover - 取决于运行机器
            continue
    return ImageFont.load_default()


async def demo_labels(db: AsyncSession, session: CameraSession) -> tuple[str, str]:
    """演示画面的文字：宠物名 + 单号，以及手机号后四位浮水印（按会话缓存 60 秒）。"""
    cached = _DEMO_LABEL_CACHE.get(session.id)
    if cached and (now().timestamp() - cached[0]) < _DEMO_LABEL_TTL:
        return cached[1]

    order = (await db.execute(
        select(BoardingOrder).where(BoardingOrder.id == session.order_id)
    )).scalars().first()
    pet = (await db.execute(
        select(Pet).where(Pet.id == order.pet_id)
    )).scalars().first() if order else None
    label = f"{pet.name} · {order.order_no}" if (pet and order) else "宠物实景"
    user = (await db.execute(select(User).where(User.id == session.user_id))).scalars().first()
    from app.utils.crypto import decrypt_text

    phone = decrypt_text(user.phone_encrypted) if user else ""
    watermark = f"{phone[-4:] if len(phone) >= 4 else '****'} · {now().strftime('%m-%d %H:%M')}"
    _DEMO_LABEL_CACHE[session.id] = (now().timestamp(), (label, watermark))
    # 只留最近的会话，避免长期运行无限增长
    if len(_DEMO_LABEL_CACHE) > 200:
        for key in sorted(_DEMO_LABEL_CACHE, key=lambda k: _DEMO_LABEL_CACHE[k][0])[:-100]:
            _DEMO_LABEL_CACHE.pop(key, None)
    return label, watermark


def render_demo_frame(label: str, watermark: str = "") -> bytes | None:
    """合成一张 640×360 的演示画面 JPEG；Pillow 不可用时返回 None（退化为原行为）。"""
    import io

    try:
        from PIL import Image, ImageDraw
    except Exception:  # pragma: no cover - 依赖缺失时不影响主链路
        return None

    stamp = now().strftime("%H:%M:%S")
    key = f"{label}|{watermark}|{stamp}"
    cached = _DEMO_CACHE.get(key)
    if cached is not None:
        return cached[1]

    width, height = 640, 360
    img = Image.new("RGB", (width, height), (26, 32, 42))
    draw = ImageDraw.Draw(img)
    # 背景网格：一眼能看出是「画面区域」，而不是白屏
    for x in range(0, width, 40):
        draw.line([(x, 0), (x, height)], fill=(34, 41, 53))
    for y in range(0, height, 40):
        draw.line([(0, y), (width, y)], fill=(34, 41, 53))

    small, middle, big = _demo_font(14), _demo_font(20), _demo_font(30)
    draw.rounded_rectangle([16, 16, 108, 44], radius=8, fill=(242, 166, 90))
    draw.text((26, 22), "DEMO", font=small, fill=(45, 32, 18))
    draw.text((116, 24), "演示画面 · 门店摄像头未接入", font=small, fill=(210, 218, 228))

    # 中间：宠物与订单
    label_text = label or "宠物实景"
    box = draw.textbbox((0, 0), label_text, font=big)
    draw.text(((width - (box[2] - box[0])) / 2, 150), label_text, font=big, fill=(238, 243, 249))

    tip = "播放 / 抓拍 / 相册链路正常，接入真实摄像头后自动切换为实时画面"
    box = draw.textbbox((0, 0), tip, font=small)
    draw.text(((width - (box[2] - box[0])) / 2, 200), tip, font=small, fill=(150, 162, 178))

    draw.text((24, height - 34), now().strftime("%Y-%m-%d %H:%M:%S"), font=middle, fill=(120, 132, 148))
    if watermark:
        box = draw.textbbox((0, 0), watermark, font=small)
        draw.text((width - 24 - (box[2] - box[0]), height - 30), watermark, font=small, fill=(190, 198, 210))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    data = buf.getvalue()
    _DEMO_CACHE[key] = (int(now().timestamp()), data)
    # 只留最近 2 秒的缓存，避免内存无限增长
    cutoff = int(now().timestamp()) - 2
    for k in [k for k, (ts, _) in _DEMO_CACHE.items() if ts < cutoff]:
        _DEMO_CACHE.pop(k, None)
    return data


async def mjpeg_stream(order_id: int, fps: int):
    """MJPEG 生成器：拉流端持续读取该订单的最新帧。

    注意：这里只读内存，不做数据库操作 —— 凭证校验在路由层完成，避免长连接占用事务。
    连续 6 秒没有新帧就结束，让前端拿到明确的「流结束」信号（转而去走演示画面 / 显示离线提示），
    而不是把连接一直挂着 —— 长连接不结束，调用方（包括自动化测试）会一直等下去。
    """
    interval = 1.0 / max(fps, 1)
    idle_rounds = 0
    while True:
        frame = FrameHub.get(order_id)
        if frame is None:
            idle_rounds += 1
            if idle_rounds > 30:
                return
        else:
            idle_rounds = 0
            yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                   + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
        await asyncio.sleep(interval)


async def end_session(db: AsyncSession, session_id: int, user: User) -> dict:
    """结束观看：写入结束时间与观看时长，释放该订单的并发名额。"""
    session = (await db.execute(
        select(CameraSession).where(CameraSession.id == session_id)
    )).scalars().first()
    if session is None:
        raise NotFoundError("观看会话不存在")
    if user.role == UserRole.CUSTOMER.value and session.user_id != user.id:
        raise PermissionError_("无权操作他人会话")
    if session.ended_at is None:
        session.ended_at = now()
        session.duration_seconds = max(int((session.ended_at - (session.started_at or session.ended_at)).total_seconds()), 0)
        # 帧是按订单共享的：只有该订单已经没有别的在看的会话，才清掉缓存，
        # 否则一个观看者点「结束观看」会把另一个人的画面也断掉。
        alive = int(await db.scalar(
            select(func.count()).select_from(CameraSession).where(
                CameraSession.order_id == session.order_id,
                CameraSession.id != session.id,
                CameraSession.ended_at.is_(None),
                CameraSession.token_expires_at > now(),
            )
        ) or 0)
        if alive == 0:
            FrameHub.drop(session.order_id)
        await write_log(db, module="camera", action="watch_end", user_id=user.id,
                        biz_id=session.order_id,
                        detail=f"session={session.id} 时长={session.duration_seconds}s")
    await db.commit()
    return {"id": session.id, "duration_seconds": session.duration_seconds}


# ---------------------------------------------------------------- 抓拍
async def add_snapshot(db: AsyncSession, user: User, payload, request: Request | None = None) -> dict:
    """把一张已经存在于静态目录的图片记入相册（供采集端上传后登记）。"""
    order = (await db.execute(
        select(BoardingOrder).where(BoardingOrder.id == payload.order_id)
    )).scalars().first()
    if order is None:
        raise NotFoundError("寄养订单不存在")
    if user.role == UserRole.CUSTOMER.value and order.user_id != user.id:
        raise PermissionError_("只能保存自己宠物的画面")

    snap = CameraSnapshot(order_id=order.id, user_id=user.id, image_url=payload.image_url,
                          note=payload.note)
    db.add(snap)
    await db.flush()
    await write_log(db, module="camera", action="snapshot", user_id=user.id,
                    biz_id=order.id, detail=payload.image_url[:120], request=request)
    await db.commit()
    return {"id": snap.id, "image_url": snap.image_url, "created_at": snap.created_at}


async def capture_snapshot(
    db: AsyncSession, token: str, user: User, note: str | None = None,
    request: Request | None = None,
) -> dict:
    """把当前帧落盘为一张图片并存入相册。

    **实时流不落盘、抓拍落盘** —— 这是规划里明确的存储策略：
    转发过程只在内存里过一帧，只有用户主动抓拍才写磁盘（便于留存与回看）。
    """
    import uuid
    from pathlib import Path

    session = await _valid_session(db, token)
    frame = FrameHub.get(session.order_id)
    if frame is None and await setting_service.get_bool(db, "camera_demo_mode"):
        # 演示模式：没有真实推流时用合成帧落盘，抓拍链路不至于整条不可用
        label, watermark = await demo_labels(db, session)
        frame = render_demo_frame(label, watermark)
    if frame is None:
        raise BizError("当前没有可抓拍的画面，请等画面加载后再试")
    if len(frame) > 2 * 1024 * 1024:
        raise BizError("画面过大，无法保存")

    snap_dir = Path("uploads/snapshots")
    snap_dir.mkdir(parents=True, exist_ok=True)
    filename = f"cam-{now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}.jpg"
    (snap_dir / filename).write_bytes(frame)

    snap = CameraSnapshot(
        order_id=session.order_id, user_id=user.id, device_id=session.device_id,
        image_url=f"/static/snapshots/{filename}", note=note,
    )
    db.add(snap)
    await db.flush()
    await write_log(db, module="camera", action="snapshot", user_id=user.id,
                    biz_id=session.order_id, detail=f"抓拍 {filename}", request=request)
    await db.commit()
    return {"id": snap.id, "image_url": snap.image_url, "created_at": snap.created_at}


async def list_snapshots(db: AsyncSession, user: User) -> list[dict]:
    """我的抓拍相册（仅本人可见）。"""
    cond = []
    if user.role == UserRole.CUSTOMER.value:
        cond.append(CameraSnapshot.user_id == user.id)
    rows = (await db.execute(
        select(CameraSnapshot).where(*cond).order_by(CameraSnapshot.id.desc()).limit(60)
    )).scalars().all()
    return [
        {"id": s.id, "order_id": s.order_id, "image_url": s.image_url,
         "note": s.note, "created_at": s.created_at}
        for s in rows
    ]


# ---------------------------------------------------------------- 店长看板
async def stats(db: AsyncSession, start: date, end: date) -> dict:
    """实景看板：观看次数/时长/独立观看者/抓拍数/设备在线率。"""
    sessions = (await db.execute(
        select(CameraSession).where(
            CameraSession.created_at >= datetime.combine(start, datetime.min.time()),
            CameraSession.created_at <= datetime.combine(end, datetime.max.time()),
        )
    )).scalars().all()
    devices = (await db.execute(select(CameraDevice))).scalars().all()
    snapshots = int(await db.scalar(
        select(func.count()).select_from(CameraSnapshot).where(
            CameraSnapshot.created_at >= datetime.combine(start, datetime.min.time()),
            CameraSnapshot.created_at <= datetime.combine(end, datetime.max.time()),
        )
    ) or 0)

    online = [d for d in devices if d.status == "online"]
    return {
        "range_start": str(start), "range_end": str(end),
        "watch_count": len(sessions),
        "total_seconds": sum(s.duration_seconds for s in sessions),
        "avg_seconds": round(sum(s.duration_seconds for s in sessions) / len(sessions), 1) if sessions else 0,
        "unique_viewers": len({s.user_id for s in sessions}),
        "snapshots": snapshots,
        "device_total": len(devices),
        "device_online": len(online),
        "online_rate": round(len(online) / len(devices) * 100, 1) if devices else 0.0,
        "offline_devices": [
            {"id": d.id, "name": d.name, "last_heartbeat_at": d.last_heartbeat_at}
            for d in devices if d.status != "online"
        ],
    }


async def offline_scan(db: AsyncSession) -> dict:
    """定时任务：心跳超时判离线并提醒店长（不做自动恢复，避免掩盖真实故障）。"""
    minutes = await setting_service.get_int(db, "camera_offline_minutes")
    deadline = now() - timedelta(minutes=minutes)
    devices = (await db.execute(select(CameraDevice).where(CameraDevice.enabled == 1))).scalars().all()

    marked = 0
    managers = (await db.execute(
        select(User).where(User.role == UserRole.MANAGER.value, User.deleted_at.is_(None))
    )).scalars().all()
    for device in devices:
        stale = device.last_heartbeat_at is None or device.last_heartbeat_at < deadline
        if device.status == "online" and stale:
            device.status = "offline"
            marked += 1
            for manager in managers:
                await message_service.create_message(
                    db, user_id=manager.id, title=f"摄像头离线：{device.name}",
                    content=f"{device.name} 超过 {minutes} 分钟没有心跳，请检查门店网络与采集页是否在推流。",
                    msg_type=MessageType.CAMERA_OFFLINE.value, biz_id=device.id,
                )
            logger.warning("camera_offline", extra={"extra_fields": {"device_id": device.id}})
    await db.commit()
    return {"checked": len(devices), "marked_offline": marked, "offline_minutes": minutes}
