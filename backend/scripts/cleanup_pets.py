"""清理演示账号下的重复测试宠物（默认只保留「豆豆」「咪咪」）。

背景：冒烟 / 并发 / 契约回归用例会在演示宠主名下反复建档（冒烟测试犬、无疫苗犬…），
`init_db --reset` 虽然会清，但日常跑冒烟不会重置库，几次下来演示列表就被测试残留淹了。

本脚本做三件事（都可 `--dry-run` 预演）：
1. **逻辑删除**多余的宠物（`deleted_at`），保留 `--keep` 指定的名字；
2. 这些宠物名下**未完结的寄养单**一并置为「已取消」—— 否则宠主端实景列表会继续出现
   「已删除宠物」的幽灵卡片（`viewable_orders` 不看 `pet.deleted_at`）；
3. 顺带清掉测试临时账号（`temp_*`）与名字命中测试模式的宠物，避免店员端在住列表被污染。

用法（backend 目录）：
    python scripts/cleanup_pets.py --dry-run          # 先看要删哪些
    python scripts/cleanup_pets.py                    # 真正执行
    python scripts/cleanup_pets.py --keep 豆豆,咪咪,旺财
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from sqlalchemy import delete, select  # noqa: E402

from app.constants import BoardingOrderStatus  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    BoardingOrder,
    CameraDevice,
    CameraSession,
    Pet,
    User,
    VaccineRecord,
)

# 寄养单的终态：不用再改
TERMINAL_BOARDING = {
    BoardingOrderStatus.COMPLETED.value,
    BoardingOrderStatus.CANCELLED.value,
    BoardingOrderStatus.NO_SHOW.value,
    BoardingOrderStatus.EARLY_PICKUP.value,
}

# 测试残留的命名特征（与 init_db 的清理口径保持一致）
TEST_NAME_PREFIXES = (
    "冒烟测试", "无疫苗", "并发回归", "回归测试", "契约测试", "边界犬", "并发犬",
    "v6race", "v6same", "v6sla", "v6churn", "v7board", "v7vac", "临时犬", "T", "寄养测试",
)

# 自动化用例创建的摄像头设备名（冒烟 / 压测），清理时直接删
TEST_DEVICE_NAMES = ("实景回归摄像头", "压测房 摄像头")


def _is_test_name(name: str) -> bool:
    return any(name.startswith(prefix) for prefix in TEST_NAME_PREFIXES)


async def main() -> None:
    parser = argparse.ArgumentParser(description="清理演示账号下的重复测试宠物")
    parser.add_argument("--username", default="demo", help="演示宠主账号（默认 demo）")
    parser.add_argument("--keep", default="豆豆,咪咪", help="要保留的宠物名，逗号分隔")
    parser.add_argument("--dry-run", action="store_true", help="只打印将处理的对象，不写库")
    parser.add_argument(
        "--with-test-devices", action="store_true", default=True,
        help="同时删除自动化用例创建的测试摄像头（默认开启）",
    )
    parser.add_argument(
        "--purge", action="store_true",
        help="把已逻辑删除的宠物及其疫苗记录**物理删除**（清空库时用，不可恢复）",
    )
    args = parser.parse_args()

    keep = {n.strip() for n in args.keep.split(",") if n.strip()}

    async with AsyncSessionLocal() as db:
        owner = (await db.execute(
            select(User).where(User.username == args.username)
        )).scalars().first()
        if owner is None:
            print(f"找不到账号 {args.username}，请先执行 scripts/init_db.py")
            return

        pets = (await db.execute(select(Pet).where(Pet.deleted_at.is_(None)))).scalars().all()
        owners = {
            u.id: u for u in (await db.execute(select(User))).scalars().all()
        }

        targets: list[Pet] = []
        for pet in pets:
            user = owners.get(pet.user_id)
            is_temp_user = bool(user and str(user.username).startswith("temp_"))
            is_demo_leftover = pet.user_id == owner.id and pet.name not in keep
            if is_temp_user or is_demo_leftover or _is_test_name(pet.name):
                targets.append(pet)

        if not targets:
            print("宠物已是干净的（无需清理）")
        else:
            print(f"演示账号 {args.username} 名下保留：{', '.join(sorted(keep))}")
            print(f"待清理 {len(targets)} 只：")
            by_name: dict[str, int] = {}
            for pet in targets:
                by_name[pet.name] = by_name.get(pet.name, 0) + 1
            for name, count in sorted(by_name.items(), key=lambda kv: -kv[1]):
                print(f"  - {name} × {count}")

        target_ids = [p.id for p in targets]
        orders = (await db.execute(
            select(BoardingOrder).where(BoardingOrder.pet_id.in_(target_ids))
        )).scalars().all() if target_ids else []
        active_orders = [o for o in orders if o.status not in TERMINAL_BOARDING]
        stale_devices = (await db.execute(
            select(CameraDevice).where(CameraDevice.name.in_(TEST_DEVICE_NAMES))
        )).scalars().all() if args.with_test_devices else []
        if target_ids:
            print(f"关联寄养单 {len(orders)} 张，其中未完结 {len(active_orders)} 张将置为「已取消」")
        if stale_devices:
            print(f"测试摄像头 {len(stale_devices)} 台将删除")

        if args.dry_run:
            print("\n[dry-run] 未写入数据库。去掉 --dry-run 即执行。")
            return

        stamp = datetime.now()
        cancelled = 0
        for order in active_orders:
            order.status = BoardingOrderStatus.CANCELLED.value
            order.cancel_reason = "演示数据清理：宠物已删除"
            cancelled += 1
            # 该单的在看会话一并结束，释放并发名额
            sessions = (await db.execute(
                select(CameraSession).where(
                    CameraSession.order_id == order.id, CameraSession.ended_at.is_(None)
                )
            )).scalars().all()
            for session in sessions:
                session.ended_at = stamp

        for pet in targets:
            pet.deleted_at = stamp

        await db.commit()
        print(f"\n完成：逻辑删除宠物 {len(targets)} 只，取消寄养单 {cancelled} 张")

        if args.with_test_devices:
            # 自动化用例每跑一次就建一台「实景回归摄像头」，从不回收；
            # 不清理的话店员端设备列表会被几十台离线设备占满，找不到真正要操作的那台。
            stale = (await db.execute(
                select(CameraDevice).where(CameraDevice.name.in_(TEST_DEVICE_NAMES))
            )).scalars().all()
            for device in stale:
                await db.delete(device)
            await db.commit()
            print(f"清理测试摄像头 {len(stale)} 台（保留门店真实设备）")

        if args.purge:
            # 已逻辑删除的宠物：演示库里只剩历史残影，物理删掉（连带疫苗记录）。
            # 保留 --keep 指定的名字 —— 万一演示宠物被误删过，还能靠 init_db 恢复。
            ghosts = (await db.execute(
                select(Pet).where(Pet.deleted_at.is_not(None), Pet.name.not_in(list(keep)))
            )).scalars().all()
            ghost_ids = [p.id for p in ghosts]
            if ghost_ids:
                await db.execute(delete(VaccineRecord).where(VaccineRecord.pet_id.in_(ghost_ids)))
                await db.execute(delete(Pet).where(Pet.id.in_(ghost_ids)))
                await db.commit()
            print(f"物理删除已逻辑删除的宠物 {len(ghost_ids)} 只（含疫苗记录）")

        left = (await db.execute(
            select(Pet).where(Pet.user_id == owner.id, Pet.deleted_at.is_(None))
        )).scalars().all()
        print(f"演示账号当前可见宠物：{len(left)} 只 —— {', '.join(p.name for p in left)}")


if __name__ == "__main__":
    asyncio.run(main())
