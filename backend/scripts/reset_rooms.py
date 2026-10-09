"""重建演示宠舍：每类房型 10 间，清掉自动化用例造出来的测试房舍。

背景：冒烟 / 并发用例每次建「实景回归房舍 C7205」这类房间且从不回收，几个月下来
库里 90 多间房，宠主选房页一屏全是「实景回归房舍」，根本选不到正式房。

规则（幂等，可反复执行）：
- 目标：standard A101~A110、garden B201~B210、sunny C301~C310、vip V901~V910，共 40 间
- 目标集合内的房舍**保留原状**（不覆盖店员手工改过的系数 / 房态）
- 目标集合外的房舍：**没有寄养单引用才删**；有引用的跳过并打印（历史订单不能指向空房间）
- 被删房舍上挂着的摄像头一并清理（否则设备列表里会出现「房舍已不存在」的孤儿设备，
  店员端看着像装了摄像头、点进去却什么都推不了）

用法（backend 目录）：
    python scripts/reset_rooms.py --dry-run
    python scripts/reset_rooms.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from sqlalchemy import func, select  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402
from app.models import BoardingOrder, BoardingRoom, CameraDevice, CameraSession  # noqa: E402

# 房型模板：前缀（A1/B2/C3/V9）拼两位序号 → A101~A110 等
ROOM_SPECS = [
    {"room_type": "standard", "prefix": "A1", "name": "标准单间 A1{}",
     "species_limit": "all", "weight_limit": 10, "ratio_percent": 100,
     "facilities": "独立通风,24h监控"},
    {"room_type": "garden", "prefix": "B2", "name": "花园景房 B2{}",
     "species_limit": "dog", "weight_limit": 25, "ratio_percent": 120,
     "facilities": "户外活动区,恒温"},
    {"room_type": "sunny", "prefix": "C3", "name": "阳光房 C3{}",
     "species_limit": "cat", "weight_limit": 8, "ratio_percent": 130,
     "facilities": "观景窗,猫爬架"},
    {"room_type": "vip", "prefix": "V9", "name": "VIP 套房 V9{}",
     "species_limit": "all", "weight_limit": 40, "ratio_percent": 200,
     "facilities": "独立小院,专人看护,24h监控"},
]
PER_TYPE = 10


def target_rooms() -> list[dict]:
    """生成 40 间目标房舍（每类 10 间，房号 A101~A110 / B201~B210 / C301~C310 / V901~V910）。"""
    rooms: list[dict] = []
    for spec in ROOM_SPECS:
        for n in range(1, PER_TYPE + 1):
            rooms.append({
                "room_no": f"{spec['prefix']}{n:02d}",
                "room_type": spec["room_type"],
                "name": spec["name"].format(f"{n:02d}"),
                "species_limit": spec["species_limit"],
                "weight_limit": spec["weight_limit"],
                "ratio_percent": spec["ratio_percent"],
                "capacity": 1,
                "facilities": spec["facilities"],
            })
    return rooms


async def main() -> None:
    parser = argparse.ArgumentParser(description="重建演示宠舍（每类 10 间）")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    args = parser.parse_args()

    targets = target_rooms()
    target_nos = {r["room_no"] for r in targets}

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(BoardingRoom))).scalars().all()
        exist = {r.room_no: r for r in rows}
        print(f"当前房舍 {len(rows)} 间；目标 {len(targets)} 间（每类 {PER_TYPE} 间）")

        to_add = [r for r in targets if r["room_no"] not in exist]
        to_del = [r for r in rows if r.room_no not in target_nos]
        print(f"  需新增 {len(to_add)} 间：{', '.join(r['room_no'] for r in to_add) or '-'}")
        print(f"  待删除 {len(to_del)} 间（测试残留）")

        # 有订单引用的房舍不能删：备注里列出来
        used_ids = set()
        if to_del:
            ids = [r.id for r in to_del]
            used_ids = set(
                (await db.execute(
                    select(BoardingOrder.room_id).where(BoardingOrder.room_id.in_(ids)).distinct()
                )).scalars().all()
            )
            skipped = [r.room_no for r in to_del if r.id in used_ids]
            if skipped:
                print(f"  其中 {len(skipped)} 间有寄养单引用，将跳过：{', '.join(skipped[:10])}"
                      f"{' …' if len(skipped) > 10 else ''}")

        # 孤儿摄像头：房舍没了，设备还挂在旧 room_id 上（店员端看着像装了摄像头，
        # 点进去却什么都推不了）。每次都查，不只查本次删掉的房舍 ——
        # 历史上的孤儿不会因为这一次没删房就自动消失。
        # 只删「没有任何观看会话留痕」的（有留痕说明历史上真被看过，留着对账）。
        live_room_ids = set((await db.execute(select(BoardingRoom.id))).scalars().all())
        seen_ids = set((await db.execute(
            select(CameraSession.device_id).where(CameraSession.device_id.isnot(None)).distinct()
        )).scalars().all())
        orphan_cameras = 0
        if not args.dry_run:
            for dev in (await db.execute(select(CameraDevice))).scalars().all():
                if dev.room_id in live_room_ids or dev.id in seen_ids:
                    continue
                await db.delete(dev)
                orphan_cameras += 1

        if args.dry_run:
            print("\n[dry-run] 未写入数据库。")
            return

        for item in to_add:
            db.add(BoardingRoom(**item))
        removed = 0
        for room in to_del:
            if room.id in used_ids:
                continue
            await db.delete(room)
            removed += 1
        await db.commit()

        total = int(await db.scalar(select(func.count()).select_from(BoardingRoom)) or 0)
        by_type = (await db.execute(
            select(BoardingRoom.room_type, func.count()).group_by(BoardingRoom.room_type)
        )).all()
        print(f"\n完成：新增 {len(to_add)} 间、删除 {removed} 间，现有 {total} 间")
        if orphan_cameras:
            print(f"  同时清理孤儿摄像头 {orphan_cameras} 台")
        print("分布：" + "、".join(f"{t} {c} 间" for t, c in by_type))


if __name__ == "__main__":
    asyncio.run(main())
