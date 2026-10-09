"""知识库管理：上传校验、三种切块、异步任务与数据清理。"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, or_, select

from app.database import AsyncSessionLocal
from app.models import (
    KnowledgeDocument,
    KnowledgeIngestTask,
    OperationLog,
    User,
)
from app.schemas.knowledge import KnowledgeChunkConfig
from app.services import knowledge_ingest_service as ingest
from app.utils.exceptions import BizError
from app.rag.parser import ParsedBlock, chunk_blocks, parse_document, text_blocks


def test_upload_validation_and_chunk_config():
    config = ingest.validate_chunk_config("heading", 500, 50)
    assert config.strategy.value == "heading" and config.chunk_overlap == 50
    assert ingest.validate_file("规范.MD", "正文".encode()) == ("规范.MD", "md")
    with pytest.raises(BizError, match="格式不支持"):
        ingest.validate_file("恶意.exe", b"x")
    with pytest.raises(BizError, match="文件为空"):
        ingest.validate_file("空.txt", b"")
    with pytest.raises(BizError, match="重叠长度"):
        ingest.validate_chunk_config("fixed", 100, 100)


def test_three_chunk_strategies_keep_trace_metadata():
    blocks = [
        ParsedBlock("第一章 洗护规范", page_no=1, paragraph_no=1, heading="第一章 洗护规范", heading_level=1),
        ParsedBlock("皮肤检查。" * 25, page_no=1, paragraph_no=2, heading="第一章 洗护规范"),
        ParsedBlock("第二章 异常处理", page_no=2, paragraph_no=3, heading="第二章 异常处理", heading_level=1),
        ParsedBlock("发现异常立即停止。" * 20, page_no=2, paragraph_no=4, heading="第二章 异常处理"),
    ]
    for strategy in ("fixed", "paragraph", "heading"):
        chunks, text_length = chunk_blocks(
            blocks,
            original_name="门店规范.md",
            config=KnowledgeChunkConfig(strategy=strategy, chunk_size=100, chunk_overlap=20),
        )
        assert len(chunks) >= 2 and text_length > 200
        assert all(chunk["source_label"].startswith("门店规范.md · 第") for chunk in chunks)
        assert all(chunk["char_end"] > chunk["char_start"] for chunk in chunks)
    heading_chunks, _ = chunk_blocks(
        blocks,
        original_name="门店规范.md",
        config=KnowledgeChunkConfig(strategy="heading", chunk_size=400, chunk_overlap=20),
    )
    assert {chunk["section_title"] for chunk in heading_chunks} == {"第一章 洗护规范", "第二章 异常处理"}


def test_parse_txt_markdown_docx_and_empty_pdf(tmp_path: Path):
    txt = tmp_path / "规则.txt"
    txt.write_bytes("第一段\n\n第二段".encode("gb18030"))
    assert len(parse_document(txt, "txt", txt.name)) == 2

    md = tmp_path / "规则.md"
    md.write_text("# 洗护前\n\n检查皮肤\n\n## 洗护后\n\n留观十五分钟", encoding="utf-8")
    md_blocks = parse_document(md, "md", md.name)
    assert any(block.heading_level for block in md_blocks)
    assert text_blocks("一段\n\n二段", markdown=False)[1].paragraph_no == 2

    from docx import Document
    docx_path = tmp_path / "规则.docx"
    doc = Document()
    doc.add_heading("门店规范", level=1)
    doc.add_paragraph("洗护前先检查皮肤。")
    doc.save(docx_path)
    docx_blocks = parse_document(docx_path, "docx", docx_path.name)
    assert docx_blocks[0].heading == "门店规范" and docx_blocks[1].paragraph_no == 2

    from pypdf import PdfWriter
    pdf_path = tmp_path / "扫描件.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with pdf_path.open("wb") as stream:
        writer.write(stream)
    with pytest.raises(BizError, match="OCR"):
        parse_document(pdf_path, "pdf", pdf_path.name)

    with pytest.raises(BizError, match="不支持解析"):
        parse_document(txt, "rtf", txt.name)
    with pytest.raises(BizError, match="不存在"):
        parse_document(tmp_path / "missing.txt", "txt", "missing.txt")


async def test_document_ingest_duplicate_lists_delete_and_rebuild(monkeypatch):
    marker = uuid.uuid4().hex
    filename = f"pytest-{marker}.md"
    payload = (
        "# 洗护前检查\n\n先检查皮肤、耳道和指甲，确认没有红肿破损。\n\n"
        "## 异常处置\n\n发现持续颤抖或呼吸急促时立即停止洗护并通知宠主。"
    ).encode()
    reindex_calls: list[int] = []

    async def fake_reindex(db):
        reindex_calls.append(1)
        return {"space": "test", "entries": 1, "chunks": 2}

    monkeypatch.setattr(ingest.knowledge_service, "reindex", fake_reindex)
    monkeypatch.setattr(ingest, "schedule_task", lambda _task_id: None)

    document_id = 0
    ingest_task_id = 0
    rebuild_task_id = 0
    try:
        async with AsyncSessionLocal() as db:
            manager = (
                await db.execute(select(User).where(User.role == "manager").order_by(User.id))
            ).scalars().first()
            assert manager is not None
            result = await ingest.create_document(
                db,
                filename=filename,
                mime_type="text/markdown",
                data=payload,
                uploader_id=manager.id,
                chunk_config=KnowledgeChunkConfig(strategy="heading", chunk_size=100, chunk_overlap=10),
            )
            assert result["accepted"] and result["task"]["status"] == "pending"
            document_id = result["document"]["id"]
            ingest_task_id = result["task"]["id"]

            duplicate = await ingest.create_document(
                db,
                filename=f"copy-{filename}",
                mime_type="text/markdown",
                data=payload,
                uploader_id=manager.id,
                chunk_config=KnowledgeChunkConfig(strategy="fixed", chunk_size=200, chunk_overlap=0),
            )
            assert duplicate["duplicate"] and duplicate["document"]["id"] == document_id

        await ingest._run_task(ingest_task_id)
        assert reindex_calls == [1]

        async with AsyncSessionLocal() as db:
            document = await db.get(KnowledgeDocument, document_id)
            task = await db.get(KnowledgeIngestTask, ingest_task_id)
            assert document is not None and document.status == "completed" and document.total_chunks >= 2
            assert task is not None and task.status == "completed" and task.progress == 100

            docs, total = await ingest.list_documents(
                db, keyword=marker, status="completed", page=1, size=20
            )
            assert total == 1 and docs[0]["uploader_name"]
            chunks, chunk_total = await ingest.list_chunks(db, document_id=document_id, page=1, size=20)
            assert chunk_total == document.total_chunks
            assert chunks[0]["source_label"].startswith(filename)
            tasks, task_total = await ingest.list_tasks(db, status="completed", page=1, size=20)
            assert task_total >= 1 and any(row["id"] == ingest_task_id for row in tasks)
            assert (await ingest.get_task(db, ingest_task_id))["status_label"] == "完成"
            statistics = await ingest.stats(db)
            assert statistics["documents"] >= 1 and statistics["chunks"] >= chunk_total

            removed = await ingest.delete_document(db, document_id=document_id, operator_id=manager.id)
            rebuild_task_id = removed["rebuild_task"]["id"]
            assert removed["deleted_id"] == document_id

        await ingest._run_task(rebuild_task_id)
        assert reindex_calls == [1, 1]
        async with AsyncSessionLocal() as db:
            assert await db.get(KnowledgeDocument, document_id) is None
            assert (await ingest.get_task(db, rebuild_task_id))["status"] == "completed"
    finally:
        async with AsyncSessionLocal() as db:
            if ingest_task_id or rebuild_task_id:
                ids = [value for value in (ingest_task_id, rebuild_task_id) if value]
                await db.execute(delete(KnowledgeIngestTask).where(KnowledgeIngestTask.id.in_(ids)))
            if document_id:
                await db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id))
                await db.execute(delete(OperationLog).where(
                    OperationLog.module == "knowledge",
                    or_(
                        OperationLog.biz_id == document_id,
                        OperationLog.after_snapshot.like(f"%{rebuild_task_id}%") if rebuild_task_id else False,
                    ),
                ))
            await db.commit()


async def test_failed_task_and_restart_recovery(monkeypatch):
    marker = uuid.uuid4().hex
    task_id = 0
    document_id = 0
    scheduled: list[int] = []
    monkeypatch.setattr(ingest, "schedule_task", scheduled.append)
    try:
        async with AsyncSessionLocal() as db:
            manager = (
                await db.execute(select(User).where(User.role == "manager").order_by(User.id))
            ).scalars().first()
            assert manager is not None
            result = await ingest.create_document(
                db,
                filename=f"recover-{marker}.txt",
                mime_type="text/plain",
                data=b"recoverable text",
                uploader_id=manager.id,
                chunk_config=KnowledgeChunkConfig(strategy="fixed", chunk_size=100, chunk_overlap=0),
            )
            task_id = result["task"]["id"]
            document_id = result["document"]["id"]
            task = await db.get(KnowledgeIngestTask, task_id)
            task.status = "processing"
            task.progress = 40
            await db.commit()

        resumed = await ingest.resume_unfinished_tasks()
        assert resumed >= 1 and task_id in scheduled
        await ingest._set_failure(task_id, "模拟解析失败")
        async with AsyncSessionLocal() as db:
            task = await db.get(KnowledgeIngestTask, task_id)
            document = await db.get(KnowledgeDocument, document_id)
            assert task is not None and task.status == "failed" and "模拟" in (task.error_message or "")
            assert document is not None and document.status == "failed"
            path = Path(document.storage_path)
            await db.execute(delete(KnowledgeIngestTask).where(KnowledgeIngestTask.id == task_id))
            await db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id))
            await db.execute(delete(OperationLog).where(
                OperationLog.module == "knowledge", OperationLog.biz_id == document_id
            ))
            await db.commit()
            path.unlink(missing_ok=True)
    finally:
        if document_id:
            async with AsyncSessionLocal() as db:
                document = await db.get(KnowledgeDocument, document_id)
                if document:
                    Path(document.storage_path).unlink(missing_ok=True)
                    await db.delete(document)
                await db.execute(delete(KnowledgeIngestTask).where(KnowledgeIngestTask.id == task_id))
                await db.commit()
