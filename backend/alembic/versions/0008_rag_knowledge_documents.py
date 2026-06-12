"""0008 RAG knowledge document ingestion

店长上传文档，异步解析切块；店员只读查看与检索。

Revision ID: b7e49a31c2d8
Revises: 8c1d2e4f6a90
Create Date: 2026-10-24 09:20:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e49a31c2d8"
down_revision: str | None = "8c1d2e4f6a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_document",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False, comment="用户上传时的文件名"),
        sa.Column("stored_name", sa.String(length=80), nullable=False, comment="磁盘存储文件名"),
        sa.Column("file_ext", sa.String(length=16), nullable=False, comment="小写扩展名"),
        sa.Column("mime_type", sa.String(length=120), nullable=True, comment="上传 MIME"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, comment="文件字节数"),
        sa.Column("sha256", sa.String(length=64), nullable=False, comment="文件内容哈希，重复识别"),
        sa.Column("storage_path", sa.String(length=500), nullable=False, comment="受保护的本地存储路径"),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=False, comment="上传店长 ID"),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False,
                  comment="pending/processing/completed/failed"),
        sa.Column("chunk_strategy", sa.String(length=20), nullable=False, comment="fixed/paragraph/heading"),
        sa.Column("chunk_size", sa.Integer(), nullable=False, comment="目标块大小（字符）"),
        sa.Column("chunk_overlap", sa.Integer(), server_default="0", nullable=False,
                  comment="相邻块重叠字符数"),
        sa.Column("text_length", sa.Integer(), server_default="0", nullable=False,
                  comment="解析出的文本字符数"),
        sa.Column("total_chunks", sa.Integer(), server_default="0", nullable=False, comment="切块总数"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="最近一次失败原因"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256", name="uq_knowledge_document_sha256"),
        sa.UniqueConstraint("stored_name", name="uq_knowledge_document_stored_name"),
        comment="RAG 原始知识文档",
    )
    op.create_index("ix_knowledge_document_file_ext", "knowledge_document", ["file_ext"])
    op.create_index("ix_knowledge_document_uploaded_by", "knowledge_document", ["uploaded_by"])
    op.create_index("ix_knowledge_document_status", "knowledge_document", ["status"])

    op.create_table(
        "knowledge_chunk",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False, comment="来源文档 ID"),
        sa.Column("chunk_index", sa.Integer(), nullable=False, comment="文档内从 0 开始的块序号"),
        sa.Column("section_title", sa.String(length=255), nullable=True, comment="小节标题"),
        sa.Column("content", sa.Text(), nullable=False, comment="切块正文"),
        sa.Column("page_start", sa.Integer(), nullable=True, comment="起始页码"),
        sa.Column("page_end", sa.Integer(), nullable=True, comment="结束页码"),
        sa.Column("paragraph_start", sa.Integer(), nullable=True, comment="起始段落位置"),
        sa.Column("paragraph_end", sa.Integer(), nullable=True, comment="结束段落位置"),
        sa.Column("char_start", sa.Integer(), server_default="0", nullable=False, comment="正文起始字符"),
        sa.Column("char_end", sa.Integer(), server_default="0", nullable=False, comment="正文结束字符"),
        sa.Column("source_label", sa.String(length=500), nullable=False, comment="文件 + 位置追溯文案"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunk_document_index"),
        comment="RAG 文档切块",
    )
    op.create_index("ix_knowledge_chunk_document_id", "knowledge_chunk", ["document_id"])

    op.create_table(
        "knowledge_ingest_task",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=True, comment="入库任务文档 ID；重建为空"),
        sa.Column("document_name", sa.String(length=255), nullable=True, comment="文档名快照"),
        sa.Column("task_type", sa.String(length=20), nullable=False, comment="ingest/rebuild"),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False,
                  comment="pending/processing/completed/failed"),
        sa.Column("progress", sa.SmallInteger(), server_default="0", nullable=False, comment="0~100"),
        sa.Column("message", sa.String(length=255), nullable=True, comment="当前阶段说明"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="失败原因"),
        sa.Column("created_by", sa.BigInteger(), nullable=False, comment="发起店长 ID"),
        sa.Column("started_at", sa.DateTime(), nullable=True, comment="开始时间"),
        sa.Column("finished_at", sa.DateTime(), nullable=True, comment="结束时间"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="RAG 入库/重建异步任务",
    )
    op.create_index("ix_knowledge_ingest_task_document_id", "knowledge_ingest_task", ["document_id"])
    op.create_index("ix_knowledge_ingest_task_task_type", "knowledge_ingest_task", ["task_type"])
    op.create_index("ix_knowledge_ingest_task_status", "knowledge_ingest_task", ["status"])
    op.create_index("ix_knowledge_ingest_task_created_by", "knowledge_ingest_task", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_ingest_task_created_by", table_name="knowledge_ingest_task")
    op.drop_index("ix_knowledge_ingest_task_status", table_name="knowledge_ingest_task")
    op.drop_index("ix_knowledge_ingest_task_task_type", table_name="knowledge_ingest_task")
    op.drop_index("ix_knowledge_ingest_task_document_id", table_name="knowledge_ingest_task")
    op.drop_table("knowledge_ingest_task")
    op.drop_index("ix_knowledge_chunk_document_id", table_name="knowledge_chunk")
    op.drop_table("knowledge_chunk")
    op.drop_index("ix_knowledge_document_status", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_uploaded_by", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_file_ext", table_name="knowledge_document")
    op.drop_table("knowledge_document")
