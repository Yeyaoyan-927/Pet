"""门店 RAG 知识库管理接口（只管文档治理，不做检索）。

权限差异：
- 店员：查看文档、可追溯切块、入库任务状态；
- 店长：包含店员权限，另可上传、删除文档和重建索引。

**检索不在这里**：RAG 的唯一对外入口是 Agent 在对话中调用的 `search_knowledge` 工具。
本模块不提供 `/search`，避免知识检索出现第二套入口与第二套权限口径。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps.auth import get_manager_user, get_staff_user
from app.models import User
from app.schemas.common import ok, page_data
from app.services import knowledge_service
from app.services import knowledge_ingest_service as ingest_service
from app.utils.exceptions import BizError

router = APIRouter(prefix="/knowledge", tags=["RAG 知识库"])

CATEGORY_LABEL = {
    "allergy": "过敏原",
    "skin": "皮肤病禁忌",
    "stress": "应激处置",
    "drug": "用药间隔",
    "senior": "老年宠物",
    "behavior": "行为训练",
    "nutrition": "营养喂养",
    "goods": "用品选购",
    "all": "通用规范",
}


@router.get("", summary="内置知识条目列表（店员 / 店长）")
async def list_knowledge(
    category: str | None = Query(None),
    _user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    items = await knowledge_service.list_entries(db, category=category)
    for item in items:
        item["category_label"] = CATEGORY_LABEL.get(item["category"], item["category"])
    return ok({"items": items, "total": len(items), "categories": CATEGORY_LABEL})


@router.get("/meta", summary="知识库统计、配置与当前角色权限")
async def knowledge_meta(
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    data = await ingest_service.stats(db)
    data["role"] = user.role
    data["can_manage"] = user.role == "manager"
    return ok(data)


@router.get("/documents", summary="文档列表（店员 / 店长）")
async def list_documents(
    keyword: str | None = Query(None, max_length=100),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await ingest_service.list_documents(
        db, keyword=keyword, status=status, page=page, size=size
    )
    return ok(page_data(items, total, page, size))


@router.get("/documents/{document_id}/chunks", summary="查看文档切块（店员 / 店长）")
async def list_document_chunks(
    document_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await ingest_service.list_chunks(
        db, document_id=document_id, page=page, size=size
    )
    return ok(page_data(items, total, page, size))


@router.post("/documents/upload", summary="上传并异步切块入库（仅店长）")
async def upload_documents(
    files: list[UploadFile] = File(..., description="1~N 个 PDF/Word/TXT/Markdown 文件"),
    strategy: str = Form(default=settings.KB_DEFAULT_CHUNK_STRATEGY),
    chunk_size: int = Form(default=settings.KB_DEFAULT_CHUNK_SIZE),
    chunk_overlap: int = Form(default=settings.KB_DEFAULT_CHUNK_OVERLAP),
    user: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    if not files:
        raise BizError("请至少选择一个文件")
    if len(files) > settings.KB_MAX_BATCH_FILES:
        raise BizError(f"单次最多上传 {settings.KB_MAX_BATCH_FILES} 个文件")
    chunk_config = ingest_service.validate_chunk_config(strategy, chunk_size, chunk_overlap)
    results: list[dict] = []
    task_ids: list[int] = []
    max_bytes = settings.KB_MAX_FILE_MB * 1024 * 1024
    for upload in files:
        try:
            # 只多读 1 字节即可判断超限，避免把任意大文件完整装进内存。
            data = await upload.read(max_bytes + 1)
            result = await ingest_service.create_document(
                db,
                filename=upload.filename or "",
                mime_type=upload.content_type,
                data=data,
                uploader_id=user.id,
                chunk_config=chunk_config,
            )
            results.append(result)
            if result["accepted"] and result["task"]:
                task_ids.append(result["task"]["id"])
        except BizError as exc:
            results.append({
                "accepted": False,
                "duplicate": False,
                "message": exc.message,
                "document": None,
                "task": None,
                "file_name": upload.filename,
            })
        finally:
            await upload.close()
    for task_id in task_ids:
        ingest_service.schedule_task(task_id)
    accepted = sum(1 for item in results if item["accepted"])
    duplicates = sum(1 for item in results if item.get("duplicate"))
    return ok({
        "items": results,
        "accepted": accepted,
        "duplicates": duplicates,
        "rejected": len(results) - accepted,
    }, message=f"已接收 {accepted} 个文件" if accepted else "没有文件进入处理队列")


@router.delete("/documents/{document_id}", summary="删除文档和切块并重建索引（仅店长）")
async def delete_document(
    document_id: int,
    user: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await ingest_service.delete_document(
        db, document_id=document_id, operator_id=user.id
    ), message="文档已删除，索引重建任务已排队")


@router.get("/tasks", summary="切块/索引任务列表（店员 / 店长）")
async def list_tasks(
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await ingest_service.list_tasks(db, status=status, page=page, size=size)
    return ok(page_data(items, total, page, size))


@router.get("/tasks/{task_id}", summary="查询单个任务进度（店员 / 店长）")
async def task_detail(
    task_id: int,
    _user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await ingest_service.get_task(db, task_id))


@router.post("/index/rebuild", summary="全量重建 RAG 索引（仅店长）")
async def rebuild_index(
    user: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(
        await ingest_service.create_rebuild_task(db, operator_id=user.id),
        message="索引重建任务已提交",
    )


# 说明：这里**没有** `POST /search`。
# RAG 的检索入口只有一个 —— Agent 在对话中调用的 `search_knowledge` 工具。
# 知识库页面只做文档治理（上传 / 切块 / 任务 / 删除 / 重建），
# 单独开一个检索接口会让「检索」出现第二套权限、分页与引用格式，收益只是同一批片段的另一种看法。
