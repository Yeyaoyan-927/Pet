"""清理三端「测试产生的流水数据」：消息中心 / 预约 / 寄养 / 用品订单 / 宠物实景 / AI 聊天。

背景：冒烟、并发、浏览器回归每跑一轮就往这些表里写一批数据（消息 2000+、预约 200+、
寄养单 60+…），演示时列表全是「冒烟测试犬 / PG2026…」的残留。

**只删流水，不动配置与主数据**：
- 保留：账号、宠物（已单独清理）、房型/房舍、摄像头设备、商品与 SKU、知识库、门店配置
- 保留：`operation_log`（审计日志）与 `task_run`（任务执行记录）—— 审计默认不删，
  确有需要加 `--with-audit`（会一并清掉任务执行记录）
- 保留：RAG 上传的知识文档（是店长维护的知识资产，不是流水），
  需要连上传文档 / 切块 / 入库任务一起清时显式加 `--only knowledge`

用法（backend 目录）：
    python scripts/cleanup_business.py --dry-run        # 先看要删多少
    python scripts/cleanup_business.py                  # 执行（物理删除）
    python scripts/cleanup_business.py --only messages,chat
    python scripts/cleanup_business.py --only knowledge # 只清 RAG 上传文档（含磁盘文件）
    python scripts/cleanup_business.py --with-audit     # 连审计日志一起清

注意：清 knowledge 只会删库记录与 `data/knowledge_uploads` 下的文件，
**不会自动重建向量索引**（重建要调 embedding 接口，批处理脚本不默认调外部 API）——
清完请在店长端「RAG 知识库 → 重建索引」，或重启服务触发索引新鲜度自检。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from sqlalchemy import delete, func, select  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Appointment,
    BoardingCareLog,
    BoardingCarePlan,
    BoardingEarlyPickup,
    BoardingOrder,
    BoardingPickupTask,
    CameraSession,
    CameraSnapshot,
    CartItem,
    ChatMessage,
    ChatSession,
    GoodsOrder,
    GoodsOrderItem,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeIngestTask,
    Message,
    OperationLog,
    RiskReport,
    TaskRun,
    WashRecord,
)

# 分组 → (中文名, 子表在前, 主表在后)
GROUPS: dict[str, tuple[str, tuple]] = {
    "messages": ("消息中心", (Message,)),
    "appointments": ("预约（含洗护记录 / 风险报告）", (RiskReport, WashRecord, Appointment)),
    "boarding": ("寄养（含照护日志 / 照护计划 / 接送任务 / 提前接回申请）",
                 (BoardingCareLog, BoardingCarePlan, BoardingPickupTask,
                  BoardingEarlyPickup, BoardingOrder)),
    "orders": ("用品订单（含订单明细 / 购物车）", (GoodsOrderItem, CartItem, GoodsOrder)),
    "camera": ("宠物实景（观看会话 / 抓拍）", (CameraSnapshot, CameraSession)),
    "chat": ("AI 聊天（会话 / 消息）", (ChatMessage, ChatSession)),
    # RAG 上传文档属于知识资产而非流水，默认不清（见模块 docstring）
    "knowledge": ("RAG 上传知识文档（入库任务 / 切块 / 文档）",
                  (KnowledgeIngestTask, KnowledgeChunk, KnowledgeDocument)),
}
# 默认全清的分组：不含 knowledge，避免手一抖把店长维护的知识库清掉
ALL_GROUPS = ("messages", "appointments", "boarding", "orders", "camera", "chat")


async def main() -> None:
    parser = argparse.ArgumentParser(description="清理测试流水数据（默认 6 组全清）")
    parser.add_argument("--only", default=",".join(ALL_GROUPS),
                        help=f"只清指定分组，逗号分隔；可选：{', '.join(ALL_GROUPS)}")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不删除")
    parser.add_argument("--with-audit", action="store_true",
                        help="同时清空审计日志与任务执行记录（默认保留）")
    args = parser.parse_args()

    selected = [g.strip() for g in args.only.split(",") if g.strip()]
    unknown = [g for g in selected if g not in GROUPS]
    if unknown:
        print(f"未知分组：{unknown}；可选：{', '.join(ALL_GROUPS)}")
        return

    plan: list[tuple[str, str, object]] = []
    for key in selected:
        label, models = GROUPS[key]
        for model in models:
            plan.append((label, model.__tablename__, model))
    if args.with_audit:
        plan.append(("审计与任务执行", "operation_log", OperationLog))
        plan.append(("审计与任务执行", "task_run", TaskRun))

    async with AsyncSessionLocal() as db:
        print("=== 待清理清单 ===")
        total = 0
        counts: list[tuple[str, str, object, int]] = []
        for label, table, model in plan:
            n = int(await db.scalar(select(func.count()).select_from(model)) or 0)
            counts.append((label, table, model, n))
            total += n
            print(f"  {label:24s} {table:22s} {n:>6d} 条")
        print(f"  合计 {total} 条")

        if args.dry_run:
            print("\n[dry-run] 未删除任何数据。去掉 --dry-run 即执行。")
            return
        if total == 0:
            print("\n没有需要清理的数据。")
            return

        print("\n=== 开始清理 ===")
        # 清 knowledge 时同步删磁盘文件：只删库里记录过的路径，避免留下孤儿文件
        stored_paths: list[str] = []
        if "knowledge" in selected:
            stored_paths = [
                p for (p,) in (await db.execute(select(KnowledgeDocument.storage_path))).all() if p
            ]
        for label, table, model, n in counts:
            if n == 0:
                continue
            await db.execute(delete(model))
            print(f"  已清空 {label} → {table}（{n} 条）")
        await db.commit()

        if stored_paths:
            removed = 0
            for rel in stored_paths:
                # storage_path 落库时是绝对路径；为兼容历史相对路径做一次兜底拼接
                abs_path = rel if os.path.isabs(rel) else os.path.join(BASE_DIR, rel)
                try:
                    if os.path.exists(abs_path):
                        os.remove(abs_path)
                        removed += 1
                except OSError as exc:
                    print(f"  [warn] 删除上传文件失败 {rel}：{exc}")
            print(f"  已删除上传文件 {removed}/{len(stored_paths)} 个")
        print("\n完成。")

        # 复核：清理后各表应为 0
        left = 0
        for _, _, model in plan:
            left += int(await db.scalar(select(func.count()).select_from(model)) or 0)
        print(f"复核：所选分组剩余 {left} 条（应为 0）")
        if "knowledge" in selected:
            print("提示：向量索引未重建，请在店长端「RAG 知识库 → 重建索引」。")


if __name__ == "__main__":
    asyncio.run(main())
