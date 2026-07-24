"""审计日志服务：所有写操作必须落库。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OperationLog
from app.utils.logger import logger


def _dump(data: Any) -> str | None:
    if data is None:
        return None
    try:
        text = json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(data)
    return text[:60000]


async def write_log(
    db: AsyncSession,
    *,
    module: str,
    action: str,
    user_id: int | None = None,
    staff_id: int | None = None,
    biz_id: int | None = None,
    before: Any = None,
    after: Any = None,
    request: Request | None = None,
    status: int = 1,
    detail: str | None = None,
) -> None:
    """写入一条审计日志。**只 flush 不 commit**：与业务数据处于同一事务，

        业务回滚时审计也回滚，避免「操作失败但日志显示成功」。
    """
    ip = None
    user_agent = None
    if request is not None:
        ip = request.client.host if request.client else None
        user_agent = (request.headers.get("user-agent") or "")[:255]
    db.add(
        OperationLog(
            user_id=user_id,
            staff_id=staff_id,
            module=module,
            action=action,
            biz_id=biz_id,
            before_snapshot=_dump(before),
            after_snapshot=_dump(after),
            ip=ip,
            user_agent=user_agent,
            status=status,
            detail=detail,
        )
    )
    logger.info(
        "audit",
        extra={"extra_fields": {"module": module, "action": action, "biz_id": biz_id, "status": status,
                                "operator": user_id or staff_id}},
    )


async def list_logs(
    db: AsyncSession, *, module: str | None = None, page: int = 1, size: int = 20
) -> tuple[list[dict], int]:
    """审计日志分页查询（过滤下推到 SQL）。"""
    from sqlalchemy import func, select

    from app.models import OperationLog

    cond = []
    if module:
        cond.append(OperationLog.module == module)
    total = int(await db.scalar(select(func.count()).select_from(OperationLog).where(*cond)) or 0)
    rows = (
        await db.execute(
            select(OperationLog).where(*cond).order_by(OperationLog.id.desc())
            .offset((page - 1) * size).limit(size)
        )
    ).scalars().all()
    items = [
        {
            "id": r.id,
            "module": r.module,
            "action": r.action,
            "user_id": r.user_id,
            "staff_id": r.staff_id,
            "biz_id": r.biz_id,
            "ip": r.ip,
            "status": r.status,
            "detail": r.detail,
            "created_at": r.created_at,
        }
        for r in rows
    ]
    return items, total
