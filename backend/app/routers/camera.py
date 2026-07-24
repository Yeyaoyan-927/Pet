"""宠物实景接口（V7.3）。

注意 `GET /camera/stream/{token}` **不使用 JWT**：`<img>` 标签无法携带 Authorization 头，
所以用**短期独立凭证**（默认 5 分钟）走路径鉴权 —— 这也正是「凭证与 JWT 分离、防转发」的设计目的。
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import CAMERA_PROVIDER_LABEL, CAMERA_STATUS_LABEL, UserRole
from app.database import get_db
from app.deps.auth import get_current_user, get_manager_user, get_staff_user
from app.models import User
from app.schemas.camera import CameraDeviceIn, CameraSessionIn, SnapshotIn
from app.schemas.common import ok
from app.services import camera_service, setting_service
from app.utils.exceptions import BizError, NotFoundError

router = APIRouter(prefix="/camera", tags=["宠物实景"])


@router.get("/meta", summary="实景字典与隐私说明")
async def meta(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """实景字典与隐私说明。"""
    return ok({
        "providers": CAMERA_PROVIDER_LABEL,
        "device_status": CAMERA_STATUS_LABEL,
        "rules": {
            "token_ttl_seconds": await setting_service.get_int(db, "camera_token_ttl_seconds"),
            "max_streams_per_order": await setting_service.get_int(db, "camera_max_streams_per_order"),
            "view_start_hour": await setting_service.get_int(db, "camera_view_start_hour"),
            "view_end_hour": await setting_service.get_int(db, "camera_view_end_hour"),
            "fps": await setting_service.get_int(db, "camera_frame_fps"),
            "snapshot_retention_days": await setting_service.get_int(db, "camera_snapshot_retention_days"),
        },
        "privacy": (
            "画面仅你本人可见；观看凭证 5 分钟有效；单订单最多 2 路同时观看；"
            "画面带手机号后四位浮水印；每次观看都会留痕；实时流默认不录制。"
        ),
    })


@router.get("/live", summary="可观看的在住宠物（含不可观看原因）")
async def live(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """可观看的在住宠物（含不可观看原因）。"""
    return ok(await camera_service.viewable_orders(db, user))


@router.post("/sessions", summary="获取观看凭证（隐私红线全部在此校验）")
async def create_session(
    payload: CameraSessionIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取观看凭证（隐私红线全部在此校验）。"""
    data = await camera_service.issue_token(db, payload.order_id, user, request)
    return ok(data, "已获取观看凭证（5 分钟内有效）")


@router.get("/stream/{token}", summary="MJPEG 实时画面（短期凭证鉴权，无需 JWT）")
async def stream(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """MJPEG 实时画面（短期凭证鉴权，无需 JWT）。

    两条返回路径：
    1. 门店端正在推流 → MJPEG 多帧流（`<img>` 直接播放）；
    2. 没人推流且开启演示模式 → **单张 JPEG**，前端按帧轮询刷新。
       为什么演示模式不走 MJPEG：无源的多帧流只能靠超时结束，调用方（含自动化测试）
       会一直等一个不会结束的响应；单帧 + 轮询既不会挂住连接，也不会出现空白画面。
    """
    # 先做一次凭证校验（含过期），再交给生成器只读内存，避免长连接占用事务
    session = await camera_service._valid_session(db, token)
    fps = await setting_service.get_int(db, "camera_frame_fps")

    if camera_service.FrameHub.get(session.order_id) is None and await setting_service.get_bool(
        db, "camera_demo_mode"
    ):
        label, watermark = await camera_service.demo_labels(db, session)
        demo = camera_service.render_demo_frame(label, watermark)
        if demo is not None:
            return Response(content=demo, media_type="image/jpeg",
                            headers={"Cache-Control": "no-store"})

    return StreamingResponse(
        camera_service.mjpeg_stream(session.order_id, fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/frame/{token}", summary="当前单帧（真实帧优先，无推流时回演示帧）")
async def single_frame(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """单帧轮询端点：宠主端每 800ms 拉一次，`X-Frame-Mode` 标记 live / demo。

    为什么宠主端不再走 MJPEG：播放模式若在签发凭证那一刻一次性判定，
    店员「后开推流」时宠主端会永远停在演示画面；MJPEG 空转 6 秒结束又会把
    播放器打成错误态。单帧轮询天然自适应 —— 真实帧一到，下一次轮询就是实时画面，
    演示标签也随 `X-Frame-Mode` 自动消失。
    """
    session = await camera_service._valid_session(db, token)
    frame = camera_service.FrameHub.get(session.order_id)
    if frame is not None:
        return Response(content=frame, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store", "X-Frame-Mode": "live"})
    if await setting_service.get_bool(db, "camera_demo_mode"):
        label, watermark = await camera_service.demo_labels(db, session)
        demo = camera_service.render_demo_frame(label, watermark)
        if demo is not None:
            return Response(content=demo, media_type="image/jpeg",
                            headers={"Cache-Control": "no-store", "X-Frame-Mode": "demo"})
    # 没有真实帧且演示模式关闭：204 让前端保持「等待门店推流」状态
    return Response(status_code=204)


@router.post("/frames/{token}", summary="门店端推送一帧画面（店员 / 店长）")
async def push_frame(
    token: str,
    request: Request,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """门店端推送一帧画面（店员 / 店长）。"""
    raw = await request.body()
    if not raw:
        raise BizError("请求体为空，需上传 JPEG 二进制")
    return ok(await camera_service.push_frame(db, token, raw, staff), "已转发")


@router.post("/sessions/{session_id}/end", summary="结束观看（记录时长）")
async def end_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """结束观看（记录时长）。"""
    return ok(await camera_service.end_session(db, session_id, user), "已结束观看")


# ---------------------------------------------------------------- 设备
@router.get("/devices", summary="设备列表（店员 / 店长）")
async def devices(
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """设备列表（店员 / 店长）。"""
    return ok(await camera_service.list_devices(db))


@router.post("/devices", summary="新增 / 更新设备（仅店长）")
async def upsert_device(
    payload: CameraDeviceIn,
    request: Request,
    manager: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    """新增 / 更新设备（仅店长）。"""
    data = await camera_service.upsert_device(db, payload, manager, request)
    return ok(data, "设备已保存")


@router.patch("/devices/{device_id}/status", summary="启停设备（店员 / 店长：关闭摄像头）")
async def device_status(
    device_id: int,
    payload: dict,
    request: Request,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """启停设备（店员 / 店长）。

    店员也能「关闭摄像头」：现场发现问题（设备被挪动、宠物在治疗、隐私要求）时，
    等店长到场处理不现实；停用会立即写审计日志（`device_disabled`），可追溯。
    """
    status = str((payload or {}).get("status") or "")
    return ok(await camera_service.set_device_status(db, device_id, status, staff, request), "设备状态已更新")


@router.post("/devices/{device_id}/heartbeat", summary="设备心跳（门店采集页）")
async def device_heartbeat(
    device_id: int,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """设备心跳（门店采集页）。"""
    return ok(await camera_service.heartbeat(db, device_id))


# ---------------------------------------------------------------- 抓拍与看板
@router.post("/snapshots", summary="一键抓拍（存入我的相册）")
async def add_snapshot(
    payload: SnapshotIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """一键抓拍（存入我的相册）。"""
    return ok(await camera_service.add_snapshot(db, user, payload, request), "已存入相册")


@router.post("/snapshots/{token}", summary="一键抓拍（把当前画面落盘存入相册）")
async def capture_snapshot(
    token: str,
    request: Request,
    note: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """一键抓拍（把当前画面落盘存入相册）。"""
    return ok(await camera_service.capture_snapshot(db, token, user, note, request), "已存入相册")


@router.get("/snapshots", summary="我的相册")
async def snapshots(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """我的相册。"""
    return ok(await camera_service.list_snapshots(db, user))


@router.get("/stats", summary="实景看板（仅店长：观看量 / 设备在线率 / 抓拍）")
async def stats(
    start: date = Query(...),
    end: date = Query(...),
    manager: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    """实景看板（仅店长：观看量 / 设备在线率 / 抓拍）。"""
    return ok(await camera_service.stats(db, start, end))
