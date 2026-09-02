"""LlamaIndex 版 RAG 索引（V8.4，参照 RAG 参考项目的写法，只保留基础 RAG）。

写法对齐参考项目（`RAG知识库聊天系统/app/services/rag_service.py`）：
    Settings.embed_model = DashScopeEmbedding(...)
    SentenceSplitter(chunk_size=500, chunk_overlap=50) → VectorStoreIndex(nodes, storage_context=...)
    ChromaVectorStore(chroma_collection=col) 作为持久化后端

**刻意只做基础 RAG**：不做 HyDE、不做 BM25+RRF 混合、不做 CRAG/GraphRAG。
门店知识只有十几篇，向量召回 + 可选 rerank 已经够用，链路越短越不容易坏。

与参考项目不同的三点（都是本项目铁律要求的）：
1. **embedding 三级降级**：`text-embedding-v4` → `qwen3.7-text-embedding` → 本地哈希向量；
   最终兜底是标签打分，保证「AI 挂了也能答规范」。
2. **空间隔离**：collection 名带 embedding 模型后缀，不同模型的向量永不混查。
3. **同步 API 包 to_thread**：LlamaIndex / Chroma 都是同步阻塞调用，不能直接卡在事件循环里。
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import re
import threading
from typing import Any

import chromadb
import httpx
from llama_index.core import Document, StorageContext, VectorStoreIndex
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode
from llama_index.embeddings.dashscope import DashScopeEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

from app.config import settings
from app.utils.logger import logger

# 本地哈希向量维度；切块参数统一由 settings.KB_* 管理
HASH_DIM = 256

# 相关度下限：低于这个分数的块不展示。
# 起因（V8.4.4）：问「什么时候改用免水洗」时，0.42 分的「常见致敏成分」也被塞进结果，
# 用户看到的是「每次都是同样几条」——宁可只给 1-2 条真正对口的，也不要凑数。
# rerank 分与向量相似度尺度不同，分别设阈值。
MIN_RERANK_SCORE = 0.45
MIN_VECTOR_SCORE = 0.30


def split_sections(content: str) -> list[tuple[str, str]]:
    """按 `## ` 切成「小节标题 + 正文」，没有小节时整篇算一块。"""
    sections: list[tuple[str, str]] = []
    title, buf = "", []
    for line in (content or "").splitlines():
        if line.startswith("## "):
            if "".join(buf).strip():
                sections.append((title, "\n".join(buf).strip()))
            title, buf = line[3:].strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        sections.append((title, "\n".join(buf).strip()))
    return sections or [("", (content or "").strip())]


# ---------------------------------------------------------------- 本地哈希向量（兜底）
def _hash_vector(text: str) -> list[float]:
    """确定性哈希向量：中文按 2/3-gram 累加。embedding 接口不可用时保证仍能按字面检索。"""
    lowered = (text or "").lower()
    tokens = [t for t in re.split(r"[^\w\u4e00-\u9fa5]+", lowered) if t]
    grams: list[str] = list(tokens)
    for token in tokens:
        if re.fullmatch(r"[\u4e00-\u9fa5]+", token):
            for n in (2, 3):
                grams.extend(token[i:i + n] for i in range(len(token) - n + 1))
    vec = [0.0] * HASH_DIM
    for gram in grams:
        digest = hashlib.md5(gram.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % HASH_DIM
        vec[idx] += 1.0 if digest[4] % 2 == 0 else -1.0
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


class HashEmbedding(BaseEmbedding):
    """离线兜底 embedding：零依赖、可复现，只有字面相似度，不具备语义能力。"""

    dim: int = HASH_DIM

    def _get_query_embedding(self, query: str) -> list[float]:
        return _hash_vector(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:  # pragma: no cover
        return _hash_vector(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return _hash_vector(text)

    async def _aget_text_embedding(self, text: str) -> list[float]:  # pragma: no cover
        return _hash_vector(text)


# ---------------------------------------------------------------- 索引
class RagIndex:
    """知识库向量索引：建索引 + 检索（+ 可选 rerank）。"""

    def __init__(self) -> None:
        self._index: VectorStoreIndex | None = None
        self._embed_model: BaseEmbedding | None = None
        self._space: str = ""
        self._entries: int = -1
        self._resolved: tuple[BaseEmbedding, str] | None = None
        self._lock = threading.Lock()

    # ---------- embedding 选择 ----------
    def _resolve_embed_model(self) -> tuple[BaseEmbedding, str]:
        """按「主 → 备 → 本地哈希」选一个真正能用的 embedding，并返回空间名。

        结果在进程内缓存：每次检索都探测一遍会把首字节延迟拉到 6 秒（实测）。
        """
        if self._resolved is not None:
            return self._resolved
        if settings.llm_available:
            candidates = [settings.EMBED_MODEL, *settings.embed_fallback_models]
            for model_name in candidates:
                try:
                    model = DashScopeEmbedding(
                        model_name=model_name,
                        api_key=settings.DASHSCOPE_API_KEY,
                        # 百炼 embedding 单次最多 10 条，超了会返回全 None（不是报错，更坑）
                        embed_batch_size=10,
                        timeout=settings.EMBED_TIMEOUT_SECONDS,
                    )
                    model.get_text_embedding("探测")  # 真实探一次，别把坏模型写进索引
                    self._resolved = (model, model_name)
                    return self._resolved
                except Exception as exc:
                    logger.warning("rag_embed_unavailable", extra={"extra_fields": {
                        "model": model_name, "error": str(exc)[:120]}})
        self._resolved = (HashEmbedding(), "hash-v1")
        return self._resolved

    @staticmethod
    def _collection_name(space: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", space).strip("_").lower()
        return f"knowledge_{slug}"

    # ---------- 建索引（同步）----------
    def _build_index(self, rows: list[dict]) -> dict:
        embed_model, space = self._resolve_embed_model()
        client = chromadb.PersistentClient(path=settings.CHROMA_DIR)
        name = self._collection_name(space)

        excluded_embed = [
            "entry_id", "chunk_id", "title", "section", "category", "species", "source",
        ]

        def metadata(row: dict, section: str) -> dict:
            return {
                "entry_id": int(row.get("entry_id") or 0),
                "chunk_id": int(row.get("chunk_id") or 0),
                "title": row["title"],
                "section": section,
                "category": row.get("category") or "",
                "species": row.get("species") or "all",
                "source": row.get("source") or "",
            }

        documents = [
            Document(
                text=f"{row['title']}\n{section}\n{body}" if section else f"{row['title']}\n{body}",
                metadata=metadata(row, section),
                # 元数据只做过滤/回显，不参与向量化（否则相似度被标题词稀释）
                excluded_embed_metadata_keys=excluded_embed,
                excluded_llm_metadata_keys=["entry_id", "chunk_id", "category", "species"],
            )
            for row in rows
            if not row.get("pre_chunked")
            for section, body in split_sections(row["content"])
        ]
        splitter = SentenceSplitter(
            chunk_size=settings.KB_DEFAULT_CHUNK_SIZE,
            chunk_overlap=settings.KB_DEFAULT_CHUNK_OVERLAP,
        )
        nodes = splitter.get_nodes_from_documents(documents)
        # 上传文档已经按店长指定策略切好，不能再用默认 500/50 二次切碎。
        for row in rows:
            if not row.get("pre_chunked"):
                continue
            section = row.get("section") or ""
            body = row.get("content") or ""
            text = f"{row['title']}\n{section}\n{body}" if section else f"{row['title']}\n{body}"
            nodes.append(TextNode(
                text=text,
                metadata=metadata(row, section),
                excluded_embed_metadata_keys=excluded_embed,
                excluded_llm_metadata_keys=["entry_id", "chunk_id", "category", "species"],
            ))

        try:
            client.delete_collection(name)  # 全量重建：维度/切块规则变化时避免脏数据
        except Exception:
            pass
        collection = client.create_collection(
            name=name,
            # entries / chunks 写进 collection 元数据：检索前据此判断「索引是否跟得上知识库」，
            # 否则新增知识文档后，只要进程里还有旧索引，就会一直只召回旧内容（V8.4.4 实测）。
            metadata={"hnsw:space": "cosine", "entries": len(rows), "chunks": len(nodes)},
        )
        vector_store = ChromaVectorStore(chroma_collection=collection)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex(nodes, storage_context=storage_context, embed_model=embed_model)

        with self._lock:
            self._index = index
            self._embed_model = embed_model
            self._space = space
            self._entries = len(rows)
        logger.info("rag_index_built", extra={"extra_fields": {
            "space": space, "entries": len(rows), "chunks": len(nodes)}})
        return {"space": space, "entries": len(rows), "chunks": len(nodes)}

    def _load_index(self) -> VectorStoreIndex | None:
        """取已有索引（进程内缓存）；缓存为空时按当前空间构造一个只读句柄。"""
        with self._lock:
            if self._index is not None:
                return self._index
        embed_model, space = self._resolve_embed_model()
        try:
            client = chromadb.PersistentClient(path=settings.CHROMA_DIR)
            collection = client.get_collection(self._collection_name(space))
        except Exception:
            return None
        if collection.count() == 0:
            return None
        index = VectorStoreIndex.from_vector_store(
            ChromaVectorStore(chroma_collection=collection), embed_model=embed_model
        )
        # 从 collection 元数据恢复「建索引时的知识条目数」：否则进程重启后 entries 未知，
        # 索引是否与知识库同步就无从判断（新增文档后可能一直用旧索引）。
        try:
            built_entries = int((collection.metadata or {}).get("entries", -1))
        except (TypeError, ValueError):
            built_entries = -1
        with self._lock:
            self._index = index
            self._embed_model = embed_model
            self._space = space
            self._entries = built_entries
        return index

    # ---------- 对外：建索引 ----------
    def ensure_index_blocking(self, rows: list[dict], *, force: bool = False) -> dict:
        if not force:
            if self._index is None:
                self._load_index()  # 先从磁盘恢复索引与「建索引时的条目数」
            with self._lock:
                up_to_date = self._index is not None and self._entries == len(rows)
            if up_to_date:
                return {"space": self._space, "entries": self._entries, "chunks": -1}
        return self._build_index(rows)

    async def ensure_index(self, rows: list[dict], *, force: bool = False) -> dict:
        return await asyncio.to_thread(self.ensure_index_blocking, rows, force=force)

    # ---------- rerank ----------
    def _rerank(self, query: str, items: list[dict], top_n: int) -> list[dict]:
        """召回后重排；任何失败都保持原顺序（rerank 是加分项，不是依赖）。"""
        if not (settings.RERANK_ENABLED and settings.llm_available and len(items) > 1):
            return items[:top_n]
        try:
            resp = httpx.post(
                settings.RERANK_URL,
                headers={"Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}"},
                json={
                    "model": settings.RERANK_MODEL,
                    "input": {"query": query,
                              "documents": [f"{i['title']}\n{i['content']}" for i in items]},
                    "parameters": {"return_documents": False, "top_n": top_n},
                },
                timeout=settings.RERANK_TIMEOUT_SECONDS,
            )
            if resp.status_code != 200:
                logger.warning("rag_rerank_failed", extra={"extra_fields": {
                    "status": resp.status_code, "body": resp.text[:120]}})
                return items[:top_n]
            ranked = (resp.json().get("output") or {}).get("results") or []
            ordered: list[dict] = []
            for hit in ranked:
                idx = hit.get("index")
                if isinstance(idx, int) and 0 <= idx < len(items):
                    item = dict(items[idx])
                    item["rerank_score"] = round(float(hit.get("relevance_score") or 0), 4)
                    ordered.append(item)
            return ordered[:top_n] or items[:top_n]
        except Exception as exc:  # pragma: no cover - 网络异常
            logger.warning("rag_rerank_error", extra={"extra_fields": {"error": str(exc)[:120]}})
            return items[:top_n]

    # ---------- 对外：检索 ----------
    def retrieve_blocking(self, query: str, top_k: int, species: str | None) -> list[dict] | None:
        """返回 None 表示「索引不可用」，由调用方降级到标签匹配。"""
        index = self._load_index()
        if index is None:
            return None
        try:
            nodes = index.as_retriever(similarity_top_k=max(top_k * 3, 6)).retrieve(query)
        except Exception as exc:
            logger.warning("rag_retrieve_failed", extra={"extra_fields": {"error": str(exc)[:160]}})
            return None

        hits: list[dict] = []
        for node in nodes:
            meta = node.metadata or {}
            entry_id = meta.get("entry_id")
            chunk_id = meta.get("chunk_id")
            if not isinstance(entry_id, int):
                entry_id = 0
            if not isinstance(chunk_id, int):
                chunk_id = 0
            if not entry_id and not chunk_id:
                continue
            if species and (meta.get("species") or "all") not in (species, "all"):
                continue
            title = meta.get("title") or ""
            section = meta.get("section") or ""
            # 切块文本以「标题（+ 小节名）」开头，回答里标题已单列，这里剥掉避免重复
            lines = node.get_content().split("\n")
            if lines and lines[0].strip() == title:
                lines = lines[1:]
            if lines and section and lines[0].strip() == section:
                lines = lines[1:]
            hits.append({
                "entry_id": entry_id,
                "chunk_id": chunk_id,
                "title": title,
                "section": section,
                "source": meta.get("source") or "",
                "content": "\n".join(lines).strip(),
                "score": round(float(node.score or 0), 4),
            })
        if not hits:
            return []

        # 同一篇文档可能有多块命中：先让所有块参与 rerank，再按条目去重保留最高分那块，
        # 否则「耳后试洗」可能命中正确的文档、却把同一篇里不相关的那一段带回去。
        ranked = self._rerank(query, hits, max(top_k * 2, 4))

        # 相关度下限：低分块只会在答案里制造「每次都是这几条」的噪音，直接丢掉；
        # 全都被过滤时至少留最高分那一条，保证「问了就有回应」。
        kept: list[dict] = []
        for item in ranked:
            if item.get("rerank_score") is not None:
                if float(item["rerank_score"]) >= MIN_RERANK_SCORE:
                    kept.append(item)
            elif float(item.get("score") or 0) >= MIN_VECTOR_SCORE:
                kept.append(item)
        if not kept and ranked:
            kept = ranked[:1]

        results: list[dict] = []
        seen: set[tuple[str, int]] = set()
        for item in kept:
            key = ("chunk", item.get("chunk_id") or 0) if item.get("chunk_id") else (
                "entry", item.get("entry_id") or 0
            )
            if key in seen:
                continue
            seen.add(key)
            results.append(item)
            if len(results) >= top_k:
                break
        return results

    async def retrieve(self, query: str, *, top_k: int = 3,
                       species: str | None = None) -> list[dict] | None:
        return await asyncio.to_thread(self.retrieve_blocking, query, top_k, species)

    # ---------- 对外：状态 ----------
    def stats_blocking(self) -> dict[str, Any]:
        with self._lock:
            if self._index is None:
                return {"ok": False, "space": "", "entries": 0}
            return {"ok": True, "space": self._space, "entries": self._entries}


rag_index = RagIndex()
