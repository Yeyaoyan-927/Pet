"""RAG 知识库文档管理：上传校验、解析切块、异步入库与任务状态。

边界：
- 店长写操作由 router 的 RBAC 守卫控制；本服务只负责业务事务；
- 原始文件存放在非静态目录，不能绕过鉴权直接下载；
- 解析任务使用进程内 asyncio worker，数据库任务表负责进度与重启恢复。
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    KNOWLEDGE_CHUNK_STRATEGY_LABEL,
    KNOWLEDGE_DOCUMENT_STATUS_LABEL,
    KNOWLEDGE_TASK_STATUS_LABEL,
    KnowledgeDocumentStatus,
    KnowledgeTaskStatus,
    KnowledgeTaskType,
)
from app.database import AsyncSessionLocal
from app.models import KnowledgeChunk, KnowledgeDocument, KnowledgeIngestTask, User
from app.rag.parser import chunk_blocks, parse_document
from app.schemas.knowledge import KnowledgeChunkConfig
from app.services import knowledge_service
from app.services.audit_service import write_log
from app.utils.datetime_util import now
from app.utils.exceptions import BizError, ConflictError, NotFoundError
from app.utils.logger import logger

_UPLOAD_ROOT = Path(settings.KB_UPLOAD_DIR).resolve()
_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
_TASK_SEMAPHORE = asyncio.Semaphore(max(1, settings.KB_MAX_CONCURRENT_TASKS))
_INDEX_LOCK = asyncio.Lock()
_RUNNING_TASKS: set[asyncio.Task] = set()


def _safe_name(filename: str) -> str:
    name = Path(filename or "").name.strip()
    if not name or name in {".", ".."}:
        raise BizError("文件名无效，请重新选择文件")
    return name[:255]


def validate_chunk_config(strategy: str, chunk_size: int, chunk_overlap: int) -> KnowledgeChunkConfig:
    try:
        return KnowledgeChunkConfig(
            strategy=strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    except ValueError as exc:
        detail = exc.errors()[0].get("msg") if hasattr(exc, "errors") and exc.errors() else str(exc)
        raise BizError(str(detail).replace("Value error, ", "")) from exc


def validate_file(filename: str, data: bytes) -> tuple[str, str]:
    safe_name = _safe_name(filename)
    ext = Path(safe_name).suffix.lower().lstrip(".")
    if ext not in settings.knowledge_allowed_extensions:
        allowed = "、".join(sorted(settings.knowledge_allowed_extensions))
        raise BizError(f"{safe_name}：格式不支持，仅允许 {allowed}")
    if not data:
        raise BizError(f"{safe_name}：文件为空，未创建入库任务")
    max_bytes = settings.KB_MAX_FILE_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise BizError(f"{safe_name}：文件大小 {len(data) / 1024 / 1024:.1f}MB，超过 {settings.KB_MAX_FILE_MB}MB 上限")
    return safe_name, ext


async def create_document(
    db: AsyncSession,
    *,
    filename: str,
    mime_type: str | None,
    data: bytes,
    uploader_id: int,
    chunk_config: KnowledgeChunkConfig,
) -> dict:
    """保存单个文件并创建入库任务。重复文件不重复写磁盘，返回 existing_document。"""
    safe_name, ext = validate_file(filename, data)
    digest = hashlib.sha256(data).hexdigest()
    existing = (
        await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.sha256 == digest))
    ).scalars().first()
    if existing is not None:
        return {
            "accepted": False,
            "duplicate": True,
            "message": f"与知识库中的「{existing.original_name}」内容重复",
            "document": document_to_dict(existing),
            "task": None,
        }

    stored_name = f"{uuid.uuid4().hex}.{ext}"
    storage_path = _UPLOAD_ROOT / stored_name
    await asyncio.to_thread(storage_path.write_bytes, data)

    document = KnowledgeDocument(
        original_name=safe_name,
        stored_name=stored_name,
        file_ext=ext,
        mime_type=(mime_type or "")[:120] or None,
        size_bytes=len(data),
        sha256=digest,
        storage_path=str(storage_path),
        uploaded_by=uploader_id,
        status=KnowledgeDocumentStatus.PENDING.value,
        chunk_strategy=chunk_config.strategy.value,
        chunk_size=chunk_config.chunk_size,
        chunk_overlap=chunk_config.chunk_overlap,
    )
    db.add(document)
    try:
        await db.flush()
        task = KnowledgeIngestTask(
            document_id=document.id,
            document_name=document.original_name,
            task_type=KnowledgeTaskType.INGEST.value,
            status=KnowledgeTaskStatus.PENDING.value,
            progress=0,
            message="文件已接收，等待解析",
            created_by=uploader_id,
        )
        db.add(task)
        await db.flush()
        await write_log(
            db,
            module="knowledge",
            action="upload",
            user_id=uploader_id,
            staff_id=uploader_id,
            biz_id=document.id,
            after={"file": safe_name, "size": len(data), "task_id": task.id},
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        storage_path.unlink(missing_ok=True)
        existing = (
            await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.sha256 == digest))
        ).scalars().first()
        if existing is not None:
            return {
                "accepted": False,
                "duplicate": True,
                "message": f"与知识库中的「{existing.original_name}」内容重复",
                "document": document_to_dict(existing),
                "task": None,
            }
        raise
    except Exception:
        await db.rollback()
        storage_path.unlink(missing_ok=True)
        raise

    return {
        "accepted": True,
        "duplicate": False,
        "message": "上传成功，已进入处理队列",
        "document": document_to_dict(document),
        "task": task_to_dict(task),
    }


def schedule_task(task_id: int) -> None:
    """登记后台协程并持有强引用，避免协程被垃圾回收。"""
    task = asyncio.create_task(_run_task_guarded(task_id), name=f"kb-task-{task_id}")
    _RUNNING_TASKS.add(task)
    task.add_done_callback(_RUNNING_TASKS.discard)


async def _set_failure(task_id: int, message: str) -> None:
    async with AsyncSessionLocal() as db:
        task = await db.get(KnowledgeIngestTask, task_id)
        if task is None:
            return
        task.status = KnowledgeTaskStatus.FAILED.value
        task.progress = min(task.progress, 99)
        task.message = "处理失败"
        task.error_message = message[:2000]
        task.finished_at = now()
        if task.document_id:
            document = await db.get(KnowledgeDocument, task.document_id)
            if document is not None:
                document.status = KnowledgeDocumentStatus.FAILED.value
                document.error_message = message[:2000]
        await write_log(
            db,
            module="knowledge",
            action=f"{task.task_type}_failed",
            user_id=task.created_by,
            staff_id=task.created_by,
            biz_id=task.document_id,
            status=0,
            detail=message[:255],
        )
        await db.commit()


async def _run_task_guarded(task_id: int) -> None:
    async with _TASK_SEMAPHORE:
        try:
            await _run_task(task_id)
        except Exception as exc:  # 后台协程绝不能把异常静默丢到 event loop
            logger.error("knowledge_task_failed", extra={"extra_fields": {
                "task_id": task_id, "error": str(exc)[:300],
            }})
            await _set_failure(task_id, str(exc) or exc.__class__.__name__)


async def _run_task(task_id: int) -> None:
    async with AsyncSessionLocal() as db:
        task = await db.get(KnowledgeIngestTask, task_id)
        if task is None or task.status == KnowledgeTaskStatus.COMPLETED.value:
            return
        task.status = KnowledgeTaskStatus.PROCESSING.value
        task.progress = 5
        task.message = "任务已启动"
        task.error_message = None
        task.started_at = now()
        await db.commit()

        if task.task_type == KnowledgeTaskType.REBUILD.value:
            task.progress = 30
            task.message = "正在重建向量索引"
            await db.commit()
            async with _INDEX_LOCK:
                result = await knowledge_service.reindex(db)
            task.progress = 100
            task.status = KnowledgeTaskStatus.COMPLETED.value
            task.message = f"索引已重建：{result.get('entries', 0)} 条来源 / {result.get('chunks', 0)} 个向量块"
            task.finished_at = now()
            await write_log(
                db, module="knowledge", action="rebuild_completed",
                user_id=task.created_by, staff_id=task.created_by,
                after=result,
            )
            await db.commit()
            return

        document = await db.get(KnowledgeDocument, task.document_id)
        if document is None:
            raise NotFoundError("入库任务对应的文档已被删除")
        document.status = KnowledgeDocumentStatus.PROCESSING.value
        document.error_message = None
        task.progress = 15
        task.message = "正在解析文档"
        await db.commit()

        blocks = await asyncio.to_thread(
            parse_document, Path(document.storage_path), document.file_ext, document.original_name
        )
        task.progress = 45
        task.message = "正在按配置切块"
        await db.commit()
        config = KnowledgeChunkConfig(
            strategy=document.chunk_strategy,
            chunk_size=document.chunk_size,
            chunk_overlap=document.chunk_overlap,
        )
        chunks, text_length = await asyncio.to_thread(
            chunk_blocks, blocks, original_name=document.original_name, config=config
        )

        await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
        db.add_all(KnowledgeChunk(document_id=document.id, **chunk) for chunk in chunks)
        document.text_length = text_length
        document.total_chunks = len(chunks)
        # 先标记 completed 并提交，reindex 才能从独立查询中看见这些新块；
        # 索引失败时统一异常处理会把文档改回 failed，店长可随后手工重建。
        document.status = KnowledgeDocumentStatus.COMPLETED.value
        task.progress = 75
        task.message = f"已生成 {len(chunks)} 个文本块，正在写入向量索引"
        await db.commit()

        async with _INDEX_LOCK:
            result = await knowledge_service.reindex(db)
        document.status = KnowledgeDocumentStatus.COMPLETED.value
        task.status = KnowledgeTaskStatus.COMPLETED.value
        task.progress = 100
        task.message = f"处理完成，共 {len(chunks)} 个文本块"
        task.finished_at = now()
        await write_log(
            db,
            module="knowledge",
            action="ingest_completed",
            user_id=task.created_by,
            staff_id=task.created_by,
            biz_id=document.id,
            after={"chunks": len(chunks), "text_length": text_length, "index": result},
        )
        await db.commit()


async def resume_unfinished_tasks() -> int:
    """应用重启后恢复未完成任务。文件和配置已落库，可安全重跑。"""
    async with AsyncSessionLocal() as db:
        tasks = (
            await db.execute(select(KnowledgeIngestTask).where(
                KnowledgeIngestTask.status.in_([
                    KnowledgeTaskStatus.PENDING.value,
                    KnowledgeTaskStatus.PROCESSING.value,
                ])
            ))
        ).scalars().all()
        for task in tasks:
            task.status = KnowledgeTaskStatus.PENDING.value
            task.progress = 0
            task.message = "服务重启，任务已重新排队"
            task.started_at = None
        await db.commit()
    for task in tasks:
        schedule_task(task.id)
    return len(tasks)


def document_to_dict(document: KnowledgeDocument, uploader_name: str | None = None) -> dict:
    return {
        "id": document.id,
        "original_name": document.original_name,
        "file_ext": document.file_ext,
        "mime_type": document.mime_type,
        "size_bytes": document.size_bytes,
        "sha256": document.sha256,
        "uploaded_by": document.uploaded_by,
        "uploader_name": uploader_name,
        "status": document.status,
        "status_label": KNOWLEDGE_DOCUMENT_STATUS_LABEL.get(document.status, document.status),
        "chunk_strategy": document.chunk_strategy,
        "chunk_strategy_label": KNOWLEDGE_CHUNK_STRATEGY_LABEL.get(
            document.chunk_strategy, document.chunk_strategy
        ),
        "chunk_size": document.chunk_size,
        "chunk_overlap": document.chunk_overlap,
        "text_length": document.text_length,
        "total_chunks": document.total_chunks,
        "error_message": document.error_message,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }


def chunk_to_dict(chunk: KnowledgeChunk) -> dict:
    return {
        "id": chunk.id,
        "document_id": chunk.document_id,
        "chunk_index": chunk.chunk_index,
        "section_title": chunk.section_title,
        "content": chunk.content,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "paragraph_start": chunk.paragraph_start,
        "paragraph_end": chunk.paragraph_end,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "source_label": chunk.source_label,
        "created_at": chunk.created_at,
    }


def task_to_dict(task: KnowledgeIngestTask) -> dict:
    return {
        "id": task.id,
        "document_id": task.document_id,
        "document_name": task.document_name,
        "task_type": task.task_type,
        "status": task.status,
        "status_label": KNOWLEDGE_TASK_STATUS_LABEL.get(task.status, task.status),
        "progress": task.progress,
        "message": task.message,
        "error_message": task.error_message,
        "created_by": task.created_by,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


async def list_documents(
    db: AsyncSession, *, keyword: str | None, status: str | None, page: int, size: int
) -> tuple[list[dict], int]:
    cond = []
    if keyword:
        cond.append(KnowledgeDocument.original_name.like(f"%{keyword.strip()}%"))
    if status:
        cond.append(KnowledgeDocument.status == status)
    total = int(await db.scalar(select(func.count()).select_from(KnowledgeDocument).where(*cond)) or 0)
    rows = (
        await db.execute(
            select(KnowledgeDocument).where(*cond).order_by(KnowledgeDocument.id.desc())
            .offset((page - 1) * size).limit(size)
        )
    ).scalars().all()
    uploader_ids = {row.uploaded_by for row in rows}
    users = (
        await db.execute(select(User.id, User.real_name, User.username).where(User.id.in_(uploader_ids)))
    ).all() if uploader_ids else []
    name_map = {row.id: row.real_name or row.username for row in users}
    return [document_to_dict(row, name_map.get(row.uploaded_by)) for row in rows], total


async def list_chunks(
    db: AsyncSession, *, document_id: int, page: int, size: int
) -> tuple[list[dict], int]:
    if await db.get(KnowledgeDocument, document_id) is None:
        raise NotFoundError("知识文档不存在")
    cond = [KnowledgeChunk.document_id == document_id]
    total = int(await db.scalar(select(func.count()).select_from(KnowledgeChunk).where(*cond)) or 0)
    rows = (
        await db.execute(
            select(KnowledgeChunk).where(*cond).order_by(KnowledgeChunk.chunk_index)
            .offset((page - 1) * size).limit(size)
        )
    ).scalars().all()
    return [chunk_to_dict(row) for row in rows], total


async def list_tasks(
    db: AsyncSession, *, status: str | None, page: int, size: int
) -> tuple[list[dict], int]:
    cond = [KnowledgeIngestTask.status == status] if status else []
    total = int(await db.scalar(select(func.count()).select_from(KnowledgeIngestTask).where(*cond)) or 0)
    rows = (
        await db.execute(
            select(KnowledgeIngestTask).where(*cond).order_by(KnowledgeIngestTask.id.desc())
            .offset((page - 1) * size).limit(size)
        )
    ).scalars().all()
    return [task_to_dict(row) for row in rows], total


async def get_task(db: AsyncSession, task_id: int) -> dict:
    task = await db.get(KnowledgeIngestTask, task_id)
    if task is None:
        raise NotFoundError("知识库任务不存在")
    return task_to_dict(task)


async def create_rebuild_task(db: AsyncSession, *, operator_id: int) -> dict:
    running = (
        await db.execute(select(KnowledgeIngestTask).where(
            KnowledgeIngestTask.task_type == KnowledgeTaskType.REBUILD.value,
            KnowledgeIngestTask.status.in_([
                KnowledgeTaskStatus.PENDING.value,
                KnowledgeTaskStatus.PROCESSING.value,
            ]),
        ).order_by(KnowledgeIngestTask.id.desc()))
    ).scalars().first()
    if running is not None:
        raise ConflictError(f"已有索引重建任务 #{running.id} 正在执行，请勿重复提交")
    task = KnowledgeIngestTask(
        document_name="全部知识来源",
        task_type=KnowledgeTaskType.REBUILD.value,
        status=KnowledgeTaskStatus.PENDING.value,
        progress=0,
        message="等待重建索引",
        created_by=operator_id,
    )
    db.add(task)
    await db.flush()
    await write_log(
        db, module="knowledge", action="rebuild_requested",
        user_id=operator_id, staff_id=operator_id, after={"task_id": task.id},
    )
    await db.commit()
    schedule_task(task.id)
    return task_to_dict(task)


async def delete_document(db: AsyncSession, *, document_id: int, operator_id: int) -> dict:
    document = await db.get(KnowledgeDocument, document_id)
    if document is None:
        raise NotFoundError("知识文档不存在或已删除")
    running = (
        await db.execute(select(KnowledgeIngestTask.id).where(
            KnowledgeIngestTask.document_id == document_id,
            KnowledgeIngestTask.status.in_([
                KnowledgeTaskStatus.PENDING.value,
                KnowledgeTaskStatus.PROCESSING.value,
            ]),
        ))
    ).scalar_one_or_none()
    if running is not None:
        raise ConflictError(f"文档任务 #{running} 仍在处理，请完成后再删除")
    before = document_to_dict(document)
    storage_path = Path(document.storage_path)
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
    await db.delete(document)
    await write_log(
        db, module="knowledge", action="delete",
        user_id=operator_id, staff_id=operator_id, biz_id=document_id, before=before,
    )
    await db.commit()
    await asyncio.to_thread(storage_path.unlink, missing_ok=True)
    rebuild = await create_rebuild_task(db, operator_id=operator_id)
    return {"deleted_id": document_id, "rebuild_task": rebuild}


async def stats(db: AsyncSession) -> dict:
    document_total = int(await db.scalar(select(func.count()).select_from(KnowledgeDocument)) or 0)
    chunk_total = int(await db.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0)
    failed = int(await db.scalar(
        select(func.count()).select_from(KnowledgeDocument)
        .where(KnowledgeDocument.status == KnowledgeDocumentStatus.FAILED.value)
    ) or 0)
    processing = int(await db.scalar(
        select(func.count()).select_from(KnowledgeIngestTask)
        .where(KnowledgeIngestTask.status.in_([
            KnowledgeTaskStatus.PENDING.value,
            KnowledgeTaskStatus.PROCESSING.value,
        ]))
    ) or 0)
    from app.rag.index import rag_index
    return {
        "documents": document_total,
        "chunks": chunk_total,
        "failed_documents": failed,
        "active_tasks": processing,
        "index": rag_index.stats_blocking(),
        "limits": {
            "max_file_mb": settings.KB_MAX_FILE_MB,
            "max_batch_files": settings.KB_MAX_BATCH_FILES,
            "allowed_extensions": sorted(settings.knowledge_allowed_extensions),
            "default_strategy": settings.KB_DEFAULT_CHUNK_STRATEGY,
            "default_chunk_size": settings.KB_DEFAULT_CHUNK_SIZE,
            "default_chunk_overlap": settings.KB_DEFAULT_CHUNK_OVERLAP,
            "min_chunk_size": settings.KB_MIN_CHUNK_SIZE,
            "max_chunk_size": settings.KB_MAX_CHUNK_SIZE,
            "max_chunk_overlap": settings.KB_MAX_CHUNK_OVERLAP,
        },
        "permissions": {
            "staff": ["view", "search", "view_chunks", "view_tasks"],
            "manager": ["view", "search", "view_chunks", "view_tasks", "upload", "delete", "rebuild"],
        },
    }
