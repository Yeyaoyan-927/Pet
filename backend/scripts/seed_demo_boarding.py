"""准备一条「演示用」在住寄养单：让宠物实景 / AI 实景随时有东西可演示。

为什么需要：清空测试数据后，寄养单为 0，宠主端点开「宠物实景」永远是空列表，
AI 说「看看宠物状态」也只能回「没有寄养中的宠物」——验收时看起来像功能坏了。

本脚本（幂等）：
1. 若演示账号已有在住（checked_in / waiting_pickup）的寄养单 → 只补设备与心跳就退出；
2. 否则给「豆豆」开一笔今天入住的寄养单（标准单间，2 晚），推进到「寄养中」；
3. 保证该房舍有**在线摄像头**（没有就装一台）——否则宠主端会显示「尚未安装摄像头」，
   实景这一块在验收时看起来就是坏的。

用法（backend 目录）：
    python scripts/seed_demo_boarding.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from sqlalchemy import select  # noqa: E402

from app.constants import BoardingOrderStatus  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models import BoardingOrder, BoardingRoom, CameraDevice, Pet, User  # noqa: E402
from app.schemas.boarding import BoardingOrderCreate  # noqa: E402
from app.services import boarding_service  # noqa: E402
from app.utils.datetime_util import now  # noqa: E402


async def ensure_camera(db, room: BoardingRoom) -> CameraDevice:
    """保证房舍有一台「在线且启用」的摄像头。

    为什么不是「只挑有摄像头的房」：房态天天在变，能被订到的那间恰好没装摄像头是常态，
    光靠选房保证不了演示可用。装一台是演示数据的一部分，与业务代码无关。
    """
    device = (await db.execute(
        select(CameraDevice).where(CameraDevice.room_id == room.id)
    )).scalars().first()
    if device is None:
        device = CameraDevice(
            room_id=room.id, name=f"{room.name} 摄像头",
            provider_type="local_webcam", status="online",
        )
        db.add(device)
    device.status = "online"
    device.enabled = 1
    device.last_heartbeat_at = now()
    await db.commit()
    return device


async def main() -> None:
    async with AsyncSessionLocal() as db:
        owner = (await db.execute(select(User).where(User.username == "demo"))).scalars().first()
        staff = (await db.execute(select(User).where(User.username == "staff1"))).scalars().first()
        if owner is None or staff is None:
            print("缺少演示账号（demo / staff1），请先执行 scripts/init_db.py")
            return
        pet = (await db.execute(
            select(Pet).where(Pet.user_id == owner.id, Pet.name == "豆豆", Pet.deleted_at.is_(None))
        )).scalars().first()
        if pet is None:
            print("找不到演示宠物「豆豆」，请先执行 scripts/init_db.py")
            return

        live_status = {BoardingOrderStatus.CHECKED_IN.value, BoardingOrderStatus.WAITING_PICKUP.value}
        existing = (await db.execute(
            select(BoardingOrder).where(
                BoardingOrder.user_id == owner.id, BoardingOrder.status.in_(live_status)
            )
        )).scalars().first()
        if existing is not None:
            room = await db.get(BoardingRoom, existing.room_id)
            if room is not None:
                await ensure_camera(db, room)
            print(f"已有在住寄养单 {existing.order_no}（{existing.status}），已确认摄像头在线，直接可用")
            return

        # 选一间「能装下这只宠物」的空闲房：体重与物种都要满足；
        # 优先挑**已装摄像头**的房（否则演示实景会显示「尚未安装摄像头」）
        weight = float(pet.weight or 0)
        candidates = (await db.execute(
            select(BoardingRoom).where(BoardingRoom.status == "idle")
        )).scalars().all()
        device_rooms = {
            d.room_id for d in (await db.execute(select(CameraDevice))).scalars().all()
        }
        fits = [
            r for r in candidates
            if (r.weight_limit is None or r.weight_limit >= weight)
            and r.species_limit in ("all", pet.species)
        ]
        if not fits:
            print(f"没有能容纳 {pet.name}（{weight}kg）的空闲房舍，请先启用合适的房型")
            return
        room = min(fits, key=lambda r: (
            0 if r.id in device_rooms else 1,          # 有摄像头的优先
            r.ratio_percent, r.room_no,
        ))

        check_in = date.today()
        order = await boarding_service.create_order(db, owner, BoardingOrderCreate(
            pet_id=pet.id, room_id=room.id,
            check_in_date=check_in, check_out_date=check_in + timedelta(days=2),
            feeding_plan="standard", terms_confirmed=True,
            idempotent_key=f"demo-live-{check_in.isoformat()}",
        ))
        for target in (BoardingOrderStatus.CONFIRMED.value,
                       BoardingOrderStatus.WAITING_CHECKIN.value,
                       BoardingOrderStatus.CHECKED_IN.value):
            await boarding_service.change_status(db, order, target, staff,
                                                 reason="演示数据：自动办理入住")

        await ensure_camera(db, room)
        print(f"已创建演示在住寄养单：{order.order_no}｜{pet.name}｜{room.room_no}｜"
              f"{check_in} → {check_in + timedelta(days=2)}")


if __name__ == "__main__":
    asyncio.run(main())
