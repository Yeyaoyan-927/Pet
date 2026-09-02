"""RAG 能力包：文档解析切块（`parser`）+ 向量索引与检索（`index`）。

分层约定：
- 本包只放**可复用的 RAG 组件**（解析、切块、向量索引、召回），不碰数据库事务与权限；
- 业务编排（权限校验 / 事务 / 任务状态 / 审计）留在 `app.services`，
  由 `knowledge_service`、`knowledge_ingest_service` 调用本包；
- 路由与模型仍在 `app.routers.knowledge`、`app.models.knowledge`。

`index` 会拉起 llama_index / chromadb（较重且有外部依赖），所以这里走惰性导出：
`from app.rag.index import rag_index` 与 `from app.rag import rag_index` 都可用，
但只导入 `parser` 时不会连带加载向量栈。
"""
from __future__ import annotations

from typing import Any

from app.rag.parser import (  # noqa: F401
    ParsedBlock,
    chunk_blocks,
    parse_document,
    text_blocks,
)

__all__ = [
    "ParsedBlock",
    "chunk_blocks",
    "parse_document",
    "text_blocks",
    "RagIndex",
    "rag_index",
]


def __getattr__(name: str) -> Any:
    """惰性导出向量索引对象，避免 import app.rag 就加载 llama_index。"""
    if name == "RagIndex":
        from app.rag.index import RagIndex

        return RagIndex
    if name == "rag_index":
        from app.rag.index import rag_index

        return rag_index
    raise AttributeError(f"module 'app.rag' has no attribute {name!r}")
