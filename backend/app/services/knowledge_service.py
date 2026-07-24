"""洗护安全知识库检索服务（RAG 里的「R」）。

检索策略（零外部依赖、结果可解释）：
1. 规则引擎命中的 `risk_key` 与知识条目的 `tags` 匹配（权重最高）；
2. 宠物档案派生关键词（物种、过敏原原文、皮肤病史原文）与 `keywords` / 正文匹配；
3. 按物种过滤（dog / cat / all），命中权重排序取 top-k。

**为什么这一版不上向量检索**：
- 免费额度模型下 embedding 调用会额外消耗额度，还会多一个链路失败点（而风险报告是下单主链路）；
- 本阶段知识量级只有数十条，标签匹配的召回已经足够，且**可解释**（能明确告诉店员「依据哪一条知识」）。

**向量检索位已预留**：只需替换 `search()` 内部实现，调用方（风险报告 / LLM 提示词）无需改动。
"""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import KnowledgeDocumentStatus
from app.models import KnowledgeChunk, KnowledgeDocument, KnowledgeEntry, Pet
from app.utils.logger import logger

# 知识文档目录：`data/knowledge/*.md`（带 front matter 的门店规范，可直接编辑后重新索引）
DOC_DIR = Path(__file__).resolve().parents[2] / "data" / "knowledge"

# 知识条目：门店自行维护的洗护安全常识。source 标注来源类型，便于追溯与替换。
SEED_KNOWLEDGE: list[dict] = [
    {
        "category": "allergy", "title": "洗护前必须核对产品成分表",
        "tags": "allergy", "keywords": "过敏,过敏原,成分,燕麦,香精,羊毛脂",
        "species": "all", "source": "门店洗护安全规范（自建）",
        "content": "档案标记过敏史的宠物，洗护前须逐项核对浴液、护毛素、香波的成分表，"
                   "命中已知过敏原的产品一律停用并更换为低敏配方；不确定时先用清水洗护。"
                   "洗护后 24 小时内观察皮肤是否出现红斑、丘疹、瘙痒加剧，异常即记录并告知宠主。",
    },
    {
        "category": "allergy", "title": "常见致敏成分与替代方案",
        "tags": "allergy", "keywords": "香精,色素,羊毛脂,茶树油,燕麦,防腐剂,低敏",
        "species": "all", "source": "宠物洗护产品常识（自建整理）",
        "content": "常见致敏成分：人工香精、合成色素、羊毛脂、茶树精油、部分防腐剂（MIT/CMIT）。"
                   "过敏体质建议改用无香精、无色素、单一表活的低敏配方，并做耳后小面积试洗。",
    },
    {
        "category": "skin", "title": "皮肤病宠物必须独立工具并消毒",
        "tags": "skin_disease", "keywords": "皮肤病,真菌,螨虫,传染,消毒,隔离",
        "species": "all", "source": "门店消毒与隔离规范（自建）",
        "content": "疑似传染性皮肤病（真菌、螨虫）的宠物使用专用工具，不得与其他宠物混用；"
                   "洗护结束后对浴缸、毛巾、吹水机头做消毒，毛巾一次性或单独高温处理，"
                   "并安排为当日最后一个洗护时段，避免交叉感染。",
    },
    {
        "category": "skin", "title": "病灶部位洗护手法",
        "tags": "skin_disease", "keywords": "病灶,结痂,破损,红肿,药浴",
        "species": "all", "source": "门店洗护操作规范（自建）",
        "content": "避开破损、结痂、红肿部位搓洗与吹风直吹；水温控制在 37-38℃，"
                   "先冲洗身体后洗头部，防止药液流入眼耳。如有医嘱药浴，按医嘱浓度与浸泡时长执行，"
                   "不得自行加倍浓度。",
    },
    {
        "category": "stress", "title": "应激反应识别与即时处置",
        "tags": "stress_high,stress_mid", "keywords": "应激,颤抖,哈气,僵直,应激等级",
        "species": "all", "source": "宠物行为学常识（自建整理）",
        "content": "出现持续颤抖、张嘴哈气、身体僵直、瞳孔放大、试图攀爬逃逸即视为应激反应。"
                   "立即停止操作，移至安静环境安抚 5-10 分钟；缓解后缩短单次洗护时长或改为分次完成，"
                   "必要时改用免水洗方案，并同步告知宠主。",
    },
    {
        "category": "stress", "title": "吹风环节降应激手法",
        "tags": "stress_high,stress_mid", "keywords": "吹风,噪音,风量,温度,分次",
        "species": "all", "source": "门店洗护操作规范（自建）",
        "content": "吹风是最易引发应激的环节：先调低风量与温度，从背部远距离开始，"
                   "让宠物逐步适应后再靠近；禁止对头面部直吹。应激等级为「重」的宠物，"
                   "建议安排安静时段并全程轻声安抚，单次吹风不超过 15 分钟。",
    },
    {
        "category": "senior", "title": "老年宠物洗护要点",
        "tags": "senior_pet", "keywords": "老年,8岁,关节,心脏,水温",
        "species": "all", "source": "老年宠物护理常识（自建整理）",
        "content": "8 岁以上宠物：降低水温与吹风温度，减少站立时间（可垫防滑垫或半程休息），"
                   "避免过度拉伸关节；全程观察呼吸频率，出现喘促、舌色发绀立即停止并联系宠主。",
    },
    {
        "category": "behavior", "title": "超小与超大体型保定要求",
        "tags": "low_weight", "keywords": "体重,超小,超大,保定,浴缸,防滑",
        "species": "all", "source": "门店操作安全规范（自建）",
        "content": "体重小于 1kg 的宠物使用小号浴缸与专用保定带，水温 38℃ 左右，全程不得离手；"
                   "体重大于 60kg 的宠物需两人协作，使用防滑垫与加宽保定带，避免腰背拉伤。",
    },
    {
        "category": "behavior", "title": "攻击倾向宠物的安全操作",
        "tags": "aggressive", "keywords": "攻击,咬,双人,嘴套,伊丽莎白圈",
        "species": "all", "source": "门店操作安全规范（自建）",
        "content": "有攻击倾向标记的宠物必须两人配合操作，佩戴伊丽莎白圈与防咬嘴套，"
                   "先用毛巾做「无接触」安定法再入水；主人不在场时不得单独操作，"
                   "操作完成后向宠主说明并记录配合度。",
    },
    {
        "category": "behavior", "title": "未绝育宠物的生理期避让",
        "tags": "not_sterilized", "keywords": "未绝育,发情,生理期,交配",
        "species": "all", "source": "门店营业规范（自建）",
        "content": "未绝育宠物建议预约前确认是否处于发情期：母犬母猫发情期不建议安排洗护，"
                   "或与其它宠物物理隔离并单独时段操作；公犬发情期易躁动，需增加安抚与保定。",
    },
    {
        "category": "drug", "title": "用药与疫苗前后洗护间隔",
        "tags": "allergy,skin_disease", "keywords": "用药,驱虫,疫苗,间隔,外用",
        "species": "all", "source": "宠物用药常识（自建整理）",
        "content": "外滴类驱虫药使用后 48 小时内不建议洗澡，以免影响药效；"
                   "疫苗接种后 7 天内避免洗护。如宠主已自行用药，先确认药物名称与使用时间，"
                   "记录到洗护记录中，药浴不得与外用驱虫药叠加使用。",
    },
    {
        "category": "all", "title": "洗护后异常观察与留观",
        "tags": "", "keywords": "异常,留观,红斑,呕吐,告知",
        "species": "all", "source": "门店服务规范（自建）",
        "content": "洗护完成后留观 15 分钟：观察皮肤是否出现红斑、抓挠加剧，是否出现呕吐、呼吸急促；"
                   "异常情况立即拍照留档并通过站内信告知宠主，同时在洗护记录中登记，"
                   "不得以「洗后正常反应」搪塞。",
    },
]


def _tags_of(entry: KnowledgeEntry) -> list[str]:
    """把知识条目的标签字段解析成集合（检索权重用）。


    """
    return [t.strip() for t in (entry.tags or "").split(",") if t.strip()]


def _keywords_of(entry: KnowledgeEntry) -> list[str]:
    """把宠物档案里的过敏史/皮肤病等文本切成关键词，用于宽松匹配。


    """
    return [k.strip() for k in (entry.keywords or "").split(",") if k.strip()]


def _pet_keywords(pet: Pet) -> list[str]:
    """从宠物档案派生检索关键词（过敏原与皮肤病是自由文本，需按字切分匹配）。"""
    words: list[str] = []
    for text in (pet.allergy or "", pet.skin_disease or ""):
        for chunk in text.replace("，", ",").replace("、", ",").split(","):
            chunk = chunk.strip()
            if len(chunk) >= 2:
                words.append(chunk)
    return words


def _clean_md_body(text: str) -> str:
    """压掉 markdown 噪音，但**保留 `## ` 小节标记** —— 检索要按小节切块，标记丢了就没法分块。"""
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if re.match(r"^#\s", line):          # 一级标题与 front matter 重复，丢掉
            continue
        line = line.replace("**", "").replace("`", "").rstrip()
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def load_markdown_docs() -> list[dict]:
    """解析 `data/knowledge/*.md`（front matter + 正文），作为知识条目来源之一。

    文档就是「知识」，用 markdown 存是为了让运营能直接改文字、走 git 审阅；
    正文不分块——门店规范一篇就是一个语义单元，切成碎片反而丢上下文。
    """
    docs: list[dict] = []
    if not DOC_DIR.exists():
        return docs
    for path in sorted(DOC_DIR.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta: dict[str, str] = {}
        body = raw
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) == 3:
                for line in parts[1].strip().splitlines():
                    if ":" in line:
                        key, value = line.split(":", 1)
                        meta[key.strip()] = value.strip()
                body = parts[2]
        docs.append({
            "title": meta.get("title") or path.stem,
            "category": meta.get("category") or "all",
            "content": _clean_md_body(body),
            "tags": meta.get("tags") or "",
            "keywords": meta.get("keywords") or "",
            "species": meta.get("species") or "all",
            "source": meta.get("source") or f"门店知识文档（{path.name}）",
        })
    return docs


async def _entry_rows(db: AsyncSession) -> list[dict]:
    """取全部启用知识来源：内置条目 + 已完成的上传文档切块。"""
    entries = (
        await db.execute(select(KnowledgeEntry).where(KnowledgeEntry.enabled == 1))
    ).scalars().all()
    rows = [
        {
            "entry_id": row.id,
            "chunk_id": 0,
            "title": row.title,
            "content": row.content,
            "category": row.category,
            "species": row.species,
            "source": row.source or "",
            "section": "",
            "pre_chunked": False,
        }
        for row in entries
    ]
    uploaded = (
        await db.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeDocument.status == KnowledgeDocumentStatus.COMPLETED.value)
            .order_by(KnowledgeDocument.id, KnowledgeChunk.chunk_index)
        )
    ).all()
    rows.extend(
        {
            "entry_id": 0,
            "chunk_id": chunk.id,
            "title": document.original_name,
            "content": chunk.content,
            "category": "uploaded",
            "species": "all",
            "source": chunk.source_label,
            "section": chunk.section_title or "",
            "pre_chunked": True,
        }
        for chunk, document in uploaded
    )
    return rows


async def reindex(db: AsyncSession) -> dict:
    """全量重建向量索引；上传文档已经切好的块不会被二次切分。"""
    from app.rag.index import rag_index

    return await rag_index.ensure_index(await _entry_rows(db), force=True)


async def ensure_index(db: AsyncSession) -> bool:
    """索引条目数与库内不一致时重建；embedding 全不可用时返回 False（上层走标签兜底）。"""
    from app.rag.index import rag_index

    try:
        rows = await _entry_rows(db)
    except Exception:
        return False
    result = await rag_index.ensure_index(rows)
    return bool(result.get("space"))


async def _load_entries(db: AsyncSession, species: str | None) -> list[KnowledgeEntry]:
    """按物种取候选条目：宠物物种 + 通用（`all`）；没有宠物时三角色都算候选。"""
    allowed = [species, "all"] if species else ["cat", "dog", "all"]
    return (
        await db.execute(
            select(KnowledgeEntry).where(
                KnowledgeEntry.enabled == 1,
                KnowledgeEntry.species.in_(allowed),
            )
        )
    ).scalars().all()


def _score_entries(
    rows: list[KnowledgeEntry], *, risk_keys: list[str], archive_words: list[str],
    query_text: str = "", limit: int = 3,
) -> list[dict]:
    """统一的打分排序（风险链路与 Agent 检索共用，避免两套召回口径不一致）。

    权重：风险项命中标签 3 / 条目标签外的问题词命中 2 / 档案关键词命中 2 / 标题命中 3；
    无标签的通用规范作为兜底（权重 1）。每条结果都带 `matched`，保证「为什么是这条」可解释。
    """
    scored: list[tuple[int, KnowledgeEntry, list[str]]] = []
    for entry in rows:
        score = 0
        reasons: list[str] = []

        tags = _tags_of(entry)
        hit_tags = [k for k in risk_keys if k and k in tags]
        if hit_tags:
            score += 3 * len(hit_tags)
            reasons.extend(f"风险项 {k}" for k in hit_tags)

        keywords = _keywords_of(entry)
        body = f"{entry.title}{entry.content}"

        matched_archive = [w for w in archive_words if w in keywords or w in body]
        if matched_archive:
            score += 2 * len(matched_archive)
            reasons.extend(f"档案关键词「{w}」" for w in matched_archive[:2])

        # Agent 检索：用条目自己的词表反向匹配用户问题（中文不做分词，避免引入依赖与误切）
        if query_text:
            matched_query = [k for k in keywords if k in query_text]
            if matched_query:
                score += 2 * len(matched_query)
                reasons.extend(f"问题关键词「{k}」" for k in matched_query[:2])
            if entry.title in query_text or query_text in entry.title:
                score += 3
                reasons.append("标题匹配")

        # 无档案依据但属于基础安全规范（tags 为空）的条目，作为兜底提示
        if not tags and not keywords:
            score += 1

        if score > 0:
            scored.append((score, entry, reasons))

    scored.sort(key=lambda x: (-x[0], x[1].id))
    return [
        {
            "id": e.id,
            "category": e.category,
            "title": e.title,
            "content": e.content,
            "source": e.source,
            "matched": reasons or ["通用安全规范"],
        }
        for _, e, reasons in scored[:limit]
    ]


async def search(
    db: AsyncSession, pet: Pet, risk_items: list[dict] | None = None, *, limit: int = 3
) -> list[dict]:
    """按风险命中项 + 档案关键词检索知识条目，返回 top-k（可解释：带 matched 命中原因）。"""
    rows = await _load_entries(db, pet.species)
    if not rows:
        return []
    return _score_entries(
        rows,
        risk_keys=[str(i.get("key") or "") for i in (risk_items or [])],
        archive_words=_pet_keywords(pet),
        limit=limit,
    )


async def search_by_query(
    db: AsyncSession, query: str, pet: Pet | None = None, *, limit: int = 3
) -> list[dict]:
    """按用户问题检索知识条目（Agent 的 RAG 入口）。

    检索顺序：**Chroma 向量检索** → 标签/关键词打分兜底。
    向量库或 embedding 不可用时自动落到标签检索，保证「问一句规范」不会因为外部依赖报错。
    """
    query_text = (query or "").strip()
    species = pet.species if pet else None

    hits = await _vector_search(db, query_text, species, limit)
    if hits is not None:
        return hits

    rows = await _load_entries(db, species)
    if not rows:
        return []
    return _score_entries(
        rows,
        risk_keys=[],
        archive_words=_pet_keywords(pet) if pet else [],
        query_text=query_text,
        limit=limit,
    )


async def search_by_text(
    db: AsyncSession, query: str, pet: Pet | None = None, *, limit: int = 3
) -> list[dict]:
    """纯标签/关键词检索（完全不碰向量库与 embedding）。

    用途：向量链路任何一环异常时兜底 —— 宁可给「通用规范」，也不能让整条对话报错。
    """
    rows = await _load_entries(db, pet.species if pet else None)
    if not rows:
        return []
    return _score_entries(
        rows,
        risk_keys=[],
        archive_words=_pet_keywords(pet) if pet else [],
        query_text=(query or "").strip(),
        limit=limit,
    )


async def _vector_search(
    db: AsyncSession, query_text: str, species: str | None, limit: int
) -> list[dict] | None:
    """LlamaIndex 向量检索（+ 可选 rerank）；返回 None 表示「不可用，请走标签兜底」。"""
    from app.rag.index import rag_index

    if not query_text:
        return None

    # 检索前先对一次「索引 vs 知识库」：条目数变了就重建。
    # 没有这一步时，新增 markdown 文档后只要进程里还有旧索引，就永远只召回旧内容 ——
    # 表现正是「不管问什么都返回同一批结果」（V8.4.4 实测）。
    try:
        rows_now = await _entry_rows(db)
        await rag_index.ensure_index(rows_now)
    except Exception as exc:  # 建索引失败不阻塞检索，先用现有索引
        logger.warning("rag_index_check_failed", extra={"extra_fields": {"error": str(exc)[:160]}})

    hits = await rag_index.retrieve(query_text, top_k=limit, species=species)
    if hits is None:
        return None
    if not hits:
        # 索引可用却没有近邻：正常情况下 Chroma 总会返回最近的若干块，走到这里多半是
        # 元数据 / 空间异常或物种过滤全灭 —— 当作「向量不可用」退回标签兜底，
        # 给次优但相关的结果，好过空手让用户以为「知识库没实现」（V8.4.2 实测踩过）。
        return None

    entry_ids = {h["entry_id"] for h in hits if h.get("entry_id")}
    chunk_ids = {h["chunk_id"] for h in hits if h.get("chunk_id")}
    if not entry_ids and not chunk_ids:
        return []
    entry_rows = (
        await db.execute(
            select(KnowledgeEntry).where(
                KnowledgeEntry.id.in_(entry_ids), KnowledgeEntry.enabled == 1
            )
        )
    ).scalars().all() if entry_ids else []
    alive_entries = {row.id: row for row in entry_rows}
    chunk_rows = (
        await db.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(
                KnowledgeChunk.id.in_(chunk_ids),
                KnowledgeDocument.status == KnowledgeDocumentStatus.COMPLETED.value,
            )
        )
    ).all() if chunk_ids else []
    alive_chunks = {chunk.id: (chunk, document) for chunk, document in chunk_rows}

    results: list[dict] = []
    for hit in hits:
        if hit.get("rerank_score") is not None:
            reason = f"重排相关度 {hit['rerank_score']:.2f}"
        else:
            reason = f"向量相似度 {float(hit.get('score') or 0):.2f}"
        chunk_pair = alive_chunks.get(hit.get("chunk_id") or 0)
        if chunk_pair is not None:
            chunk, document = chunk_pair
            results.append({
                "id": chunk.id,
                "chunk_id": chunk.id,
                "document_id": document.id,
                "category": "uploaded",
                "title": document.original_name,
                "section": hit.get("section") or chunk.section_title or "",
                "content": hit.get("content") or chunk.content,
                "source": hit.get("source") or chunk.source_label,
                "matched": [reason],
            })
        else:
            entry = alive_entries.get(hit.get("entry_id") or 0)
            if entry is None:
                continue
            results.append({
                "id": entry.id,
                "category": entry.category,
                "title": entry.title,
                # 命中的是哪一小节 —— 同一篇文档可能被问不同小节，展示时必须让用户看出来
                "section": hit.get("section") or "",
                # 命中段落即回答依据：LlamaIndex 返回的是切块后的 node 文本
                "content": hit.get("content") or entry.content,
                "source": hit.get("source") or entry.source,
                "matched": [reason],
            })
        if len(results) >= limit:
            break
    return results


async def list_entries(db: AsyncSession, *, category: str | None = None) -> list[dict]:
    """知识库分页列表（店员/店长可读，用于查看系统给出的规范依据）。"""
    cond = [KnowledgeEntry.enabled == 1]
    if category:
        cond.append(KnowledgeEntry.category == category)
    rows = (
        await db.execute(select(KnowledgeEntry).where(*cond).order_by(KnowledgeEntry.id))
    ).scalars().all()
    return [
        {"id": r.id, "category": r.category, "title": r.title, "content": r.content,
         "tags": r.tags, "keywords": r.keywords, "species": r.species, "source": r.source}
        for r in rows
    ]


async def seed_defaults(db: AsyncSession) -> int:
    """灌入知识（幂等），返回新增条数。

    - 代码内置条目：只补缺失（避免覆盖门店在库里做的调整）；
    - markdown 文档：**以文件为准更新正文**（文档在 git 里，改完重跑脚本就该生效）。
    """
    rows = (await db.execute(select(KnowledgeEntry))).scalars().all()
    by_title = {r.title: r for r in rows}
    added = 0

    for item in SEED_KNOWLEDGE:
        if item["title"] in by_title:
            continue
        db.add(KnowledgeEntry(**item))
        by_title[item["title"]] = item  # type: ignore[assignment]
        added += 1

    for doc in load_markdown_docs():
        row = by_title.get(doc["title"])
        if isinstance(row, KnowledgeEntry):
            changed = any(
                getattr(row, field) != doc[field]
                for field in ("content", "category", "tags", "keywords", "species", "source")
            )
            if changed:
                for field in ("content", "category", "tags", "keywords", "species", "source"):
                    setattr(row, field, doc[field])
        else:
            entry = KnowledgeEntry(**doc)
            db.add(entry)
            by_title[doc["title"]] = entry  # type: ignore[assignment]
            added += 1

    await db.flush()
    return added
