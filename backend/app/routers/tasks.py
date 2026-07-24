"""定时任务运维接口：查看任务清单与执行状态、手动触发（均为店长权限）。

调度器本身在进程内按配置间隔自动运行；本接口用于**运维可见性**与**手动补跑**，
两者调用的是同一个 `run_job()`，因此手动触发同样受「行锁互斥 + 执行记录 + 审计」约束。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.deps.auth import get_manager_user
from app.models import TaskRun, User
from app.schemas.common import ok
from app.services.audit_service import write_log
from app.tasks import JOBS, job_manifest, run_job, scheduler

router = APIRouter(prefix="/tasks", tags=["定时任务"])


@router.get("/lock-status", summary="[运维] 会话级并发锁状态（仅店长）")
async def lock_status(manager: User = Depends(get_manager_user)):
    """[运维] 会话级并发锁状态（仅店长）。"""
    from app.services import session_lock

    return ok({"lock": session_lock.snapshot(),
               "enabled": settings.CHAT_SESSION_LOCK_ENABLED,
               "wait_seconds": settings.CHAT_SESSION_LOCK_WAIT_SECONDS})


@router.get("", summary="任务清单与最近执行状态（店长）")
async def list_tasks(user: User = Depends(get_manager_user), db: AsyncSession = Depends(get_db)):
    """任务清单与最近执行状态（店长）。"""
    rows = {
        r.name: r
        for r in (await db.execute(select(TaskRun))).scalars().all()
    }
    items = []
    for meta in job_manifest():
        row = rows.get(meta["name"])
        items.append({
            **meta,
            "last_status": row.last_status if row else "pending",
            "last_started_at": row.last_started_at if row else None,
            "last_finished_at": row.last_finished_at if row else None,
            "last_summary": row.last_summary if row else None,
            "last_trigger": row.last_trigger if row else None,
            "run_count": int(row.run_count) if row else 0,
        })
    return ok({
        "scheduler": {
            "enabled": bool(scheduler.running),
            "started_at": scheduler.started_at,
            "tick_count": scheduler.tick_count,
            "note": "进程内置调度器；多实例部署时由 task_run 行锁保证同一任务不会被重复执行",
        },
        "items": items,
    })


@router.post("/{name}/run", summary="手动触发任务（店长）")
async def run_task(
    name: str,
    request: Request,
    user: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    """手动触发任务（店长）。"""
    if name not in JOBS:
        from app.utils.exceptions import NotFoundError

        raise NotFoundError(f"任务不存在：{name}（可选：{'、'.join(JOBS)}）")

    result = await run_job(db, name, trigger="manual")
    await write_log(db, module="task", action=f"run_{name}", user_id=user.id,
                    detail=f"手动触发：{result.get('status')}｜{result.get('summary', '')[:120]}",
                    request=request)
    await db.commit()
    return ok(result, f"任务 {JOBS[name]['label']} 执行完成")
