"""实景服务层用例（V8）：设备心跳、观看凭证红线、推帧、抓拍、看板。

重点是**隐私红线**：只能看自己的、且在住的订单；凭证有时效；
单订单并发路数受限。这些规则一旦回退就是事故，必须在服务层锁死。
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import (
    BoardingCareLog,
    BoardingCarePlan,
    BoardingOrder,
    BoardingPickupTask,
    BoardingRoom,
    CameraDevice,
    CameraSession,
    CameraSnapshot,
    Pet,
    User,
    VaccineRecord,
)
from app.schemas.boarding import BoardingOrderCreate
from app.schemas.camera import CameraDeviceIn, SnapshotIn
from app.services import boarding_service, camera_service
from app.utils.exceptions import BizError, NotFoundError
from tests.conftest import rand_tag

DAYS = 300
_SYSTEM_OPERATOR: User | None = None  # 用例内注入，供配置变更留痕


async def _demo(username: str) -> User:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalars().first()
    assert user is not None, "演示账号缺失，请先执行 scripts/init_db.py"
    return user


async def _pet(owner_id: int) -> int:
    tag = rand_tag("v8c")
    async with AsyncSessionLocal() as db:
        pet = Pet(user_id=owner_id, name=f"{tag}犬", species="dog", gender="male",
                  weight=8.0, sterilized=1)
        db.add(pet)
        await db.flush()
        db.add(VaccineRecord(pet_id=pet.id, record_type="vaccine", name="狂犬疫苗",
                             record_date=date.today(),
                             next_date=date.today() + timedelta(days=DAYS + 60)))
        await db.commit()
        return pet.id


async def _room() -> int:
    tag = rand_tag("v8cr")
    async with AsyncSessionLocal() as db:
        room = BoardingRoom(room_no=tag, room_type="standard", name=f"{tag}房",
                            species_limit="all", weight_limit=50, ratio_percent=100,
                            capacity=1, status="idle")
        db.add(room)
        await db.commit()
        return room.id


async def _checked_in_order(owner: User, pet_id: int, room_id: int) -> int:
    """直接造一张「已入住」订单（跳过状态机流程，聚焦实景逻辑）。"""
    async with AsyncSessionLocal() as db:
        cin = date.today() + timedelta(days=DAYS)
        order = await boarding_service.create_order(db, owner, BoardingOrderCreate(
            pet_id=pet_id, room_id=room_id, check_in_date=cin, check_out_date=cin + timedelta(days=3),
            terms_confirmed=True, idempotent_key=rand_tag("idem"),
        ))
        for target in ("confirmed", "waiting_checkin", "checked_in"):
            await boarding_service.change_status(db, order, target, owner)
        return order.id


async def _bind_device(room_id: int, staff: User) -> int:
    """给房舍绑摄像头并上报心跳（凭证签发要求设备在线）。"""
    async with AsyncSessionLocal() as db:
        device = await camera_service.upsert_device(db, CameraDeviceIn(
            room_id=room_id, name="回归摄像头", provider_type="local_webcam",
            fps=5, resolution="640x480",
        ), staff)
        await camera_service.heartbeat(db, device["id"])
        return device["id"]


async def _open_view_window() -> tuple[str, str]:
    from app.services import setting_service

    async with AsyncSessionLocal() as db:
        original = (await setting_service.get_value(db, "camera_view_start_hour"),
                    await setting_service.get_value(db, "camera_view_end_hour"))
        await setting_service.update_setting(db, "camera_view_start_hour", "0", _SYSTEM_OPERATOR)
        await setting_service.update_setting(db, "camera_view_end_hour", "24", _SYSTEM_OPERATOR)
        # update_setting 只写不提交（提交由调用方负责），这里必须显式 commit
        await db.commit()
    return original


async def _restore_view_window(original: tuple[str, str]) -> None:
    from app.services import setting_service

    async with AsyncSessionLocal() as db:
        await setting_service.update_setting(db, "camera_view_start_hour", original[0], _SYSTEM_OPERATOR)
        await setting_service.update_setting(db, "camera_view_end_hour", original[1], _SYSTEM_OPERATOR)
        await db.commit()


async def _cleanup(pet_ids: list[int], room_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        orders = (await db.execute(
            select(BoardingOrder.id).where(BoardingOrder.pet_id.in_(pet_ids))
        )).scalars().all() if pet_ids else []
        if orders:
            for model in (CameraSnapshot, CameraSession):
                await db.execute(delete(model).where(model.order_id.in_(orders)))
            for model in (BoardingPickupTask, BoardingCareLog, BoardingCarePlan):
                await db.execute(delete(model).where(model.order_id.in_(orders)))
            await db.execute(delete(BoardingOrder).where(BoardingOrder.id.in_(orders)))
        if pet_ids:
            await db.execute(delete(VaccineRecord).where(VaccineRecord.pet_id.in_(pet_ids)))
            await db.execute(delete(Pet).where(Pet.id.in_(pet_ids)))
        if room_ids:
            await db.execute(delete(CameraDevice).where(CameraDevice.room_id.in_(room_ids)))
            await db.execute(delete(BoardingRoom).where(BoardingRoom.id.in_(room_ids)))
        await db.commit()


async def test_device_lifecycle_and_offline_scan():
    """设备：绑定 / 心跳转在线 / 停用 / 心跳超时判离线并提醒店长。"""
    staff = await _demo("staff1")
    room_id = await _room()
    try:
        async with AsyncSessionLocal() as db:
            device = await camera_service.upsert_device(db, CameraDeviceIn(
                room_id=room_id, name="回归摄像头", provider_type="local_webcam",
                fps=5, resolution="640x480",
            ), staff)
            assert device["status"] in ("offline", "online")

            beat = await camera_service.heartbeat(db, device["id"])
            assert beat["status"] == "online"

            # 同一房舍重复绑定应更新而不是新增
            again = await camera_service.upsert_device(db, CameraDeviceIn(
                room_id=room_id, name="回归摄像头改", provider_type="local_webcam",
                fps=3, resolution="320x240",
            ), staff)
            assert again["id"] == device["id"] and again["fps"] == 3

            # 心跳时间推到很久以前 → 巡检判离线
            await db.execute(update(CameraDevice).where(CameraDevice.id == device["id"])
                             .values(last_heartbeat_at=datetime.now() - timedelta(hours=3)))
            await db.commit()
            scan = await camera_service.offline_scan(db)
            assert scan["marked_offline"] >= 1

            off = await camera_service.set_device_status(db, device["id"], "disabled", staff)
            assert off["status"] == "disabled"

            with pytest.raises(BizError):
                await camera_service.set_device_status(db, device["id"], "不存在的状态", staff)
            with pytest.raises(NotFoundError):
                await camera_service.heartbeat(db, 99999999)
    finally:
        await _cleanup([], [room_id])


@pytest.fixture(autouse=True)
async def _open_window():
    """所有实景用例统一把观看时段放开 0-24 点，避免用例结果依赖运行时刻。"""
    global _SYSTEM_OPERATOR
    _SYSTEM_OPERATOR = await _demo("staff1")
    original = await _open_view_window()
    yield
    await _restore_view_window(original)


async def _set_max_streams(value: str) -> str:
    from app.services import setting_service

    async with AsyncSessionLocal() as db:
        original = await setting_service.get_value(db, "camera_max_streams_per_order")
        await setting_service.update_setting(db, "camera_max_streams_per_order", value, _SYSTEM_OPERATOR)
        await db.commit()
    return original


async def test_issue_token_guards():
    """凭证红线：没入住不给看；他人订单不给看；并发路数受限。"""
    owner = await _demo("demo")
    other = await _demo("liu")
    pet_id = await _pet(owner.id)
    room_id = await _room()
    try:
        await _bind_device(room_id, _SYSTEM_OPERATOR)
        async with AsyncSessionLocal() as db:
            # 未入住 → 不可观看
            cin = date.today() + timedelta(days=DAYS)
            draft = await boarding_service.create_order(db, owner, BoardingOrderCreate(
                pet_id=pet_id, room_id=room_id, check_in_date=cin,
                check_out_date=cin + timedelta(days=2),
                terms_confirmed=True, idempotent_key=rand_tag("idem"),
            ))
            with pytest.raises(BizError):
                await camera_service.issue_token(db, draft.id, owner)

            for target in ("confirmed", "waiting_checkin", "checked_in"):
                await boarding_service.change_status(db, draft, target, owner)

            # 别人看不了
            with pytest.raises(BizError):
                await camera_service.issue_token(db, draft.id, other)

            original_limit = await _set_max_streams("1")
            await db.commit()   # 结束当前事务：配置由其他连接写入，快照读看不到新值（同 E-25）
            try:
                first = await camera_service.issue_token(db, draft.id, owner)
                assert len(first["token"]) >= 16 and first["expires_in"] > 0 and first["watermark"]
                with pytest.raises(BizError):
                    await camera_service.issue_token(db, draft.id, owner)
                await camera_service.end_session(db, first["session_id"], owner)
            finally:
                await _set_max_streams(original_limit)
                await db.commit()
    finally:
        await _cleanup([pet_id], [room_id])


async def test_push_frame_end_session_and_free_slot():
    """推帧 → 结束会话记录时长 → 释放并发名额。"""
    owner = await _demo("demo")
    pet_id = await _pet(owner.id)
    room_id = await _room()
    try:
        await _bind_device(room_id, _SYSTEM_OPERATOR)
        order_id = await _checked_in_order(owner, pet_id, room_id)
        async with AsyncSessionLocal() as db:
            token_info = await camera_service.issue_token(db, order_id, owner)

            payload = b"\xff\xd8\xff\xe0" + b"0" * 64 + b"\xff\xd9"
            # 推帧只允许门店内部：宠主端只能看、不能推
            with pytest.raises(BizError):
                await camera_service.push_frame(db, token_info["token"], payload, owner)
            pushed = await camera_service.push_frame(db, token_info["token"], payload, _SYSTEM_OPERATOR)
            assert pushed["bytes"] == len(payload)

            with pytest.raises(BizError):
                await camera_service.push_frame(db, "不存在的token", payload, owner)

            ended = await camera_service.end_session(db, token_info["session_id"], owner)
            assert "duration_seconds" in ended and ended["duration_seconds"] >= 0

            again = await camera_service.issue_token(db, order_id, owner)
            assert again["session_id"] != token_info["session_id"]
            await camera_service.end_session(db, again["session_id"], owner)
    finally:
        await _cleanup([pet_id], [room_id])


async def test_snapshot_and_stats():
    """抓拍：无画面时拒绝；相册可读；看板口径齐全。"""
    owner = await _demo("demo")
    pet_id = await _pet(owner.id)
    room_id = await _room()
    try:
        await _bind_device(room_id, _SYSTEM_OPERATOR)
        order_id = await _checked_in_order(owner, pet_id, room_id)
        async with AsyncSessionLocal() as db:
            with pytest.raises(BizError):
                await camera_service.capture_snapshot(db, "无画面的token", owner)

            snap = await camera_service.add_snapshot(db, owner, SnapshotIn(
                order_id=order_id, image_url="/static/snapshots/demo.jpg", note="回归抓拍",
            ))
            assert snap["id"]
            album = await camera_service.list_snapshots(db, owner)
            assert any(s["id"] == snap["id"] for s in album)

            data = await camera_service.stats(db, date.today() - timedelta(days=90),
                                              date.today() + timedelta(days=30))
            for key in ("watch_count", "total_seconds", "unique_viewers", "snapshots",
                        "device_total", "device_online", "online_rate"):
                assert key in data
    finally:
        await _cleanup([pet_id], [room_id])


async def test_viewable_orders_only_own():
    """可观看列表：只包含自己的、且在住的寄养单。"""
    owner = await _demo("demo")
    pet_id = await _pet(owner.id)
    room_id = await _room()
    try:
        await _bind_device(room_id, _SYSTEM_OPERATOR)
        order_id = await _checked_in_order(owner, pet_id, room_id)
        async with AsyncSessionLocal() as db:
            mine = await camera_service.viewable_orders(db, owner)
            assert any(x["order_id"] == order_id for x in mine)

            other = await _demo("liu")
            theirs = await camera_service.viewable_orders(db, other)
            assert all(x["order_id"] != order_id for x in theirs)
    finally:
        await _cleanup([pet_id], [room_id])


async def test_frame_hub_is_shared_by_order():
    """帧缓存在**订单**维度共享：店员推流与宠主拉流用的是不同 token（回归：宠主端永远没画面）。"""
    order_id = random.randint(100000, 999999)  # 帧缓存 key 是订单 id（整数）
    camera_service.FRAME_HUB.clear()
    camera_service.FrameHub.put(order_id, b"jpeg-bytes")
    assert camera_service.FrameHub.get(order_id) == b"jpeg-bytes"
    # 别的订单拿不到这一帧
    assert camera_service.FrameHub.get(order_id + 1) is None
    camera_service.FrameHub.drop(order_id)
    assert camera_service.FrameHub.get(order_id) is None


async def test_demo_frame_renderable():
    """没有真实推流时，演示模式必须能产出一张可用画面（回归：点了观看却一片空白）。"""
    data = camera_service.render_demo_frame("豆豆 · BG20261019", "1234 · 10-19 20:00")
    if data is None:
        pytest.skip("当前环境未安装 Pillow，演示帧不可用")
    assert data[:2] == b"\xff\xd8", "应产出合法 JPEG"
    assert len(data) > 2000
