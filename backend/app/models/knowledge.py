"""洗护安全知识库：RAG 检索的知识条目。

合规边界：知识条目由门店自行维护（可基于公开的宠物洗护常识整理），
不抓取、不镜像第三方受版权保护的内容；检索结果只作为「风险提示依据」展示，
不构成医疗诊断，风险报告固定附带免责声明。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KnowledgeEntry(Base, TimestampMixin):
    __tablename__ = "knowledge_entry"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        comment="分类：allergy 过敏原 / skin 皮肤病 / stress 应激 / drug 用药 / senior 老年 / behavior 行为",
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False, comment="知识标题")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="知识正文（洗护注意事项）")
    tags: Mapped[str | None] = mapped_column(
        String(255), comment="检索标签，逗号分隔；与规则引擎的 risk_key、宠物档案字段名对齐"
    )
    keywords: Mapped[str | None] = mapped_column(String(255), comment="补充关键词，逗号分隔")
    species: Mapped[str] = mapped_column(String(16), nullable=False, default="all", comment="dog / cat / all")
    source: Mapped[str | None] = mapped_column(String(120), comment="来源说明（便于门店追溯与替换）")
    enabled: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="1 启用")


class KnowledgeDocument(Base, TimestampMixin):
    """门店上传的原始知识文档；文件只通过鉴权接口访问，不暴露到静态目录。"""

    __tablename__ = "knowledge_document"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="用户上传时的文件名")
    stored_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, comment="磁盘存储文件名")
    file_ext: Mapped[str] = mapped_column(String(16), nullable=False, index=True, comment="小写扩展名")
    mime_type: Mapped[str | None] = mapped_column(String(120), comment="上传 MIME")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="文件字节数")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, comment="文件内容哈希，重复识别")
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="受保护的本地存储路径")
    uploaded_by: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="上传店长 ID")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True,
                                        comment="pending/processing/completed/failed")
    chunk_strategy: Mapped[str] = mapped_column(String(20), nullable=False, comment="fixed/paragraph/heading")
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, comment="目标块大小（字符）")
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="相邻块重叠字符数")
    text_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="解析出的文本字符数")
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="切块总数")
    error_message: Mapped[str | None] = mapped_column(Text, comment="最近一次失败原因")


class KnowledgeChunk(Base, TimestampMixin):
    """已经切好的知识片段；保留页码、段落和字符区间用于回答溯源。"""

    __tablename__ = "knowledge_chunk"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunk_document_index"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="来源文档 ID")
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="文档内从 0 开始的块序号")
    section_title: Mapped[str | None] = mapped_column(String(255), comment="标题切分时命中的小节标题")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="切块正文")
    page_start: Mapped[int | None] = mapped_column(Integer, comment="起始页码（从 1 开始）")
    page_end: Mapped[int | None] = mapped_column(Integer, comment="结束页码（从 1 开始）")
    paragraph_start: Mapped[int | None] = mapped_column(Integer, comment="起始段落位置（从 1 开始）")
    paragraph_end: Mapped[int | None] = mapped_column(Integer, comment="结束段落位置（从 1 开始）")
    char_start: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="解析正文起始字符")
    char_end: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="解析正文结束字符")
    source_label: Mapped[str] = mapped_column(String(500), nullable=False, comment="文件 + 页码/段落追溯文案")


class KnowledgeIngestTask(Base, TimestampMixin):
    """文档入库或全量重建索引任务，前端轮询此表查看进度。"""

    __tablename__ = "knowledge_ingest_task"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="入库任务对应文档；重建任务为空")
    document_name: Mapped[str | None] = mapped_column(String(255), comment="任务列表快照名，删文档后仍可追溯")
    task_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment="ingest/rebuild")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True,
                                        comment="pending/processing/completed/failed")
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, comment="0~100")
    message: Mapped[str | None] = mapped_column(String(255), comment="当前阶段说明")
    error_message: Mapped[str | None] = mapped_column(Text, comment="失败原因")
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="发起店长 ID")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, comment="结束时间")
