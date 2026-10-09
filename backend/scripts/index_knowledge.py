"""构建 RAG 索引：把知识条目（内置种子 + `data/knowledge/*.md`）写入 MySQL 并重建向量索引。

用法（backend 目录）：
    python scripts/index_knowledge.py            # 增量：补齐缺失知识 + 全量重建索引
    python scripts/index_knowledge.py --check    # 只看索引概况，不写库

幂等：知识按标题判重、markdown 以文件为准更新，索引全量重建（LlamaIndex + Chroma）。
"""
from __future__ import annotations

import asyncio
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app.database import AsyncSessionLocal  # noqa: E402
from app.services import knowledge_service  # noqa: E402
from app.rag.index import rag_index  # noqa: E402


async def main() -> None:
    if "--check" in sys.argv:
        print(f"向量索引：{await asyncio.to_thread(rag_index.stats_blocking)}")
        return

    async with AsyncSessionLocal() as db:
        added = await knowledge_service.seed_defaults(db)
        await db.commit()
        docs = knowledge_service.load_markdown_docs()
        result = await knowledge_service.reindex(db)

    print(f"知识文档：{len(docs)} 篇（目录 {knowledge_service.DOC_DIR}）")
    print(f"本次新增知识条目：{added} 条")
    print(f"索引结果：{result}")


if __name__ == "__main__":
    asyncio.run(main())
