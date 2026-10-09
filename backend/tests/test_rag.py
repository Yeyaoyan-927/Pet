"""RAG 检索用例（V8.4，LlamaIndex + Chroma）：切块、兜底、向量检索。

原则：**向量库与 embedding 都是外部依赖，任何一环不可用都不能让知识问答失败**，
所以既测正常路径，也测标签兜底。
"""

from __future__ import annotations

import math

import pytest

from app.config import settings
from app.database import AsyncSessionLocal
from app.rag import index as rag_mod
from app.services import knowledge_service


def test_split_sections_keeps_headings():
    """按 ## 切块：小节标题要保留，正文不能串到别的节里。"""
    content = "## 一、先看后洗\n必须检查皮肤。\n\n## 二、检查顺序\n按顺序看五个部位。"
    sections = rag_mod.split_sections(content)
    assert [s[0] for s in sections] == ["一、先看后洗", "二、检查顺序"]
    assert "检查皮肤" in sections[0][1] and "五个部位" in sections[1][1]
    assert rag_mod.split_sections("只有一段话") == [("", "只有一段话")]


def test_hash_vector_is_deterministic_and_normalized():
    """本地兜底向量必须可复现（否则查询与索引不在同一空间），且已归一化。"""
    a = rag_mod._hash_vector("皮肤病的狗怎么洗")
    b = rag_mod._hash_vector("皮肤病的狗怎么洗")
    assert a == b
    assert abs(math.sqrt(sum(v * v for v in a)) - 1.0) < 1e-6
    same = rag_mod._hash_vector("皮肤病的狗洗澡怎么洗")
    other = rag_mod._hash_vector("门店排班与员工业绩")
    dot = lambda x, y: sum(i * j for i, j in zip(x, y))  # noqa: E731
    assert dot(a, same) > dot(a, other)


def test_markdown_docs_loaded():
    """5 篇知识文档必须能被解析：标题不重复、正文与来源齐全。"""
    docs = knowledge_service.load_markdown_docs()
    assert len(docs) >= 5, f"应至少有 5 篇知识文档，实际 {len(docs)}"
    titles = [d["title"] for d in docs]
    assert len(titles) == len(set(titles))
    assert all(d["content"] and len(d["content"]) > 100 for d in docs)
    assert all(d["source"] for d in docs)


async def test_search_falls_back_to_labels_when_vector_unavailable(monkeypatch):
    """索引不可用时，必须回退标签匹配并给出结果（不是报错、不是空）。"""
    async def _no_vector(*_args, **_kwargs):
        return None

    monkeypatch.setattr(rag_mod.rag_index, "retrieve", _no_vector)
    async with AsyncSessionLocal() as db:
        items = await knowledge_service.search_by_query(db, "皮肤病的狗怎么洗", None, limit=3)
    assert items, "降级后仍应命中知识条目"
    assert any("皮肤" in i["title"] for i in items), [i["title"] for i in items]
    assert all(i["matched"] for i in items)


@pytest.mark.skipif(not settings.llm_available, reason="未配置 DASHSCOPE_API_KEY，向量检索不可用")
async def test_vector_search_hits_expected_doc():
    """正常路径：LlamaIndex + 百炼 embedding 应把「过敏用什么浴液」召回成分/过敏相关文档。"""
    async with AsyncSessionLocal() as db:
        if not await knowledge_service.ensure_index(db):
            pytest.skip("向量索引不可用（chromadb 或 embedding 初始化失败）")
        items = await knowledge_service.search_by_query(db, "我家狗对燕麦过敏，用什么浴液", None, limit=3)

    assert items, "向量检索应返回结果"
    assert any("成分" in i["title"] or "过敏" in i["title"] for i in items), [i["title"] for i in items]
    # 开启 rerank 时给「重排相关度」，关闭时给「向量相似度」，两者都算带依据
    assert any(m.startswith(("向量相似度", "重排相关度")) for i in items for m in i["matched"])


async def test_tool_degrades_instead_of_failing(monkeypatch):
    """向量链路抛异常时，search_knowledge 必须降级到标签检索，而不是让整条对话报错。"""
    from app.agent.tools.registry import TOOLS, ToolContext
    from app.models import User
    from sqlalchemy import select

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("chroma exploded")

    monkeypatch.setattr(knowledge_service, "search_by_query", _boom)
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == "demo"))).scalars().first()
        assert user is not None, "演示账号缺失，请先执行 scripts/init_db.py"
        result = await TOOLS["search_knowledge"]["handler"](
            ToolContext(db, user, None, "rag-fallback"), query="常见致敏成分的清单"
        )
    assert result["total"] >= 1, "异常时必须仍返回标签匹配结果"
    assert result["items"][0]["matched"], "降级结果同样要带依据"


def test_knowledge_question_routing_rule():
    """知识问答路由回归（V8.4.2）：三句曾分别误判为查档案 / 寒暄，必须路由到 search_knowledge。

    「应激反应的三个等级」曾被「应激」抢进查档案（店员画像没这工具 → 权限报错）；
    「安抚手法的步骤」「为什么必须先看后洗」曾落进寒暄。
    """
    from app.agent.react import AgentRunner

    runner = AgentRunner.__new__(AgentRunner)
    runner.user = type("U", (), {"role": "staff"})()
    for text in ("应激反应的三个等级", "安抚手法的步骤", "为什么必须先看后洗", "常见致敏成分的清单"):
        parsed = runner._interpret_by_rule(text)
        assert parsed["intent"] == "search_knowledge", f"{text} → {parsed['intent']}"
        assert parsed["slots"]["query"] == text, "query 必须带用户原话"

    # 动作意图不能被知识问答兜底抢走
    assert runner._interpret_by_rule("明天帮我约个洗澡")["intent"] == "create_appointment"
    # 领域档案查询不能被「应激 / 过敏」关键词抢走
    customer = AgentRunner.__new__(AgentRunner)
    customer.user = type("U", (), {"role": "customer"})()
    assert customer._interpret_by_rule("看看豆豆的应激记录")["intent"] == "query_pet_profile"


class _FakeNode:
    """检索结果节点替身：只需要 metadata / get_content / score 三个能力。"""

    def __init__(self, entry_id: int, score: float):
        self.metadata = {"entry_id": entry_id, "title": f"文档{entry_id}",
                         "section": "", "source": "test", "species": "all"}
        self._content = f"正文{entry_id}"
        self.score = score

    def get_content(self) -> str:
        return self._content


class _FakeIndex:
    def __init__(self, nodes):
        self._nodes = nodes

    def as_retriever(self, similarity_top_k: int = 6):
        nodes = self._nodes

        class _Retriever:
            def retrieve(self, _query):
                return nodes

        return _Retriever()


def test_low_relevance_chunks_are_filtered(monkeypatch):
    """低相关块必须被丢弃（V8.4.4）：否则答案里永远塞着不相干的「凑数」条目，
    用户看到的就是「不管问什么都返回同一批内容」。"""
    index = rag_mod.RagIndex()
    monkeypatch.setattr(index, "_load_index", lambda: _FakeIndex([_FakeNode(1, 0.9), _FakeNode(2, 0.9)]))
    monkeypatch.setattr(
        index, "_rerank",
        lambda _q, items, _n: [{**items[0], "rerank_score": 0.92}, {**items[1], "rerank_score": 0.2}],
    )
    hits = index.retrieve_blocking("随便问一句", 3, None)
    assert [h["entry_id"] for h in hits] == [1], "0.2 分的块应被过滤掉"


def test_all_low_scores_keep_best_one(monkeypatch):
    """全都不达标时至少留最高分那一条：宁可少，不能「问了没回应」。"""
    index = rag_mod.RagIndex()
    monkeypatch.setattr(index, "_load_index", lambda: _FakeIndex([_FakeNode(1, 0.9), _FakeNode(2, 0.9)]))
    monkeypatch.setattr(
        index, "_rerank",
        lambda _q, items, _n: [{**items[0], "rerank_score": 0.2}, {**items[1], "rerank_score": 0.1}],
    )
    hits = index.retrieve_blocking("随便问一句", 3, None)
    assert len(hits) == 1 and hits[0]["entry_id"] == 1


async def test_knowledge_answer_falls_back_when_llm_fails(monkeypatch):
    """模型不可用/报错时必须退回模板摘要：回答可以朴素，但不能没有回答。"""
    from app.agent import react as react_mod

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(react_mod.bailian_client, "chat_with_fallback", _boom)
    runner = react_mod.AgentRunner.__new__(react_mod.AgentRunner)
    items = [{
        "title": "应激反应分级与安抚流程", "section": "四、什么时候改用免水洗",
        "content": "符合以下任一条件时，建议与宠主沟通改为免水洗。",
        "source": "门店洗护安全手册", "matched": ["重排相关度 0.91"],
    }]
    text = await runner._compose_knowledge_answer("什么时候改用免水洗", items)
    assert "应激反应分级与安抚流程 · 四、什么时候改用免水洗" in text
    assert "依据：" in text


def test_refs_item_shape():
    """下发给前端折叠面板的片段结构：必须有标题/小节/来源，正文做截断。"""
    from app.agent.react import AgentRunner

    ref = AgentRunner._refs_item({
        "title": "洗护产品成分与过敏原排查", "section": "四、耳后小面积试洗",
        "content": "## 四、耳后小面积试洗\n" + "很长" * 300,
        "source": "门店洗护安全手册", "matched": ["重排相关度 0.93"],
    })
    assert ref["title"] and ref["section"] and ref["source"]
    assert ref["content"].startswith("四、耳后小面积试洗")
    assert len(ref["content"]) <= 260
    assert "0.93" in ref["matched"]


async def test_answer_knowledge_emits_refs_before_answer(monkeypatch):
    """知识问答必须「先发片段、再发回答」，前端才能把依据挂在气泡下方。"""
    from app.agent import react as react_mod

    runner = react_mod.AgentRunner.__new__(react_mod.AgentRunner)

    async def _fake_compose(*_args, **_kwargs):
        return "这是模型基于片段生成的话"

    async def _fake_answer(_session, text, **_kwargs):
        yield {"type": "answer", "delta": text}

    monkeypatch.setattr(runner, "_compose_knowledge_answer", _fake_compose)
    monkeypatch.setattr(runner, "_answer_and_save", _fake_answer)
    result = {"items": [{"title": "应激反应分级与安抚流程", "section": "四、什么时候改用免水洗",
                         "content": "正文", "source": "门店洗护安全手册", "matched": ["重排相关度 0.91"]}]}
    events = [e async for e in runner._answer_knowledge(None, {"query": "免水洗"}, result)]
    assert events[0]["type"] == "refs"
    assert events[0]["items"][0]["title"] == "应激反应分级与安抚流程"
    assert events[1]["type"] == "answer" and "模型" in events[1]["delta"]


async def test_answer_knowledge_empty_items_gives_hint(monkeypatch):
    """没检索到片段时给「问得更具体」的提示，不派发空 refs。"""
    from app.agent import react as react_mod

    runner = react_mod.AgentRunner.__new__(react_mod.AgentRunner)

    async def _fake_answer(_session, text, **_kwargs):
        yield {"type": "answer", "delta": text}

    monkeypatch.setattr(runner, "_answer_and_save", _fake_answer)
    events = [e async for e in runner._answer_knowledge(None, {}, {"items": []})]
    assert len(events) == 1 and events[0]["type"] == "answer"
    assert "知识库" in events[0]["delta"]


def test_chat_refs_rebuilt_from_tool_result():
    """历史回看：从 tool_result 还原片段；坏 JSON 不能让历史消息打不开。"""
    import json as _json

    from app.models import ChatMessage
    from app.services.chat_service import _refs_of

    msg = ChatMessage(role="assistant", tool_name="search_knowledge", tool_result=_json.dumps(
        {"items": [{"title": "用药与疫苗前后洗护间隔", "section": "一、三条时间红线",
                    "content": "## 一、三条时间红线\n正文", "source": "门店洗护安全手册",
                    "matched": ["重排相关度 0.87"]}]}, ensure_ascii=False))
    refs = _refs_of(msg)
    assert refs and refs[0]["section"] == "一、三条时间红线"
    assert refs[0]["content"].startswith("一、三条时间红线")

    broken = ChatMessage(role="assistant", tool_name="search_knowledge", tool_result="{bad json")
    assert _refs_of(broken) is None
    assert _refs_of(ChatMessage(role="user", tool_name="search_knowledge", tool_result="{}")) is None


async def test_write_intent_not_downgraded_to_smalltalk(monkeypatch):
    """写操作的规则命中不能被模型的 smalltalk 改判掉（否则「预约」变成寒暄，连确认都不给）。"""
    from sqlalchemy import select

    from app.agent import react as react_mod
    from app.agent.llm.client import LLMResult
    from app.models import ChatSession, User

    async def _fake_chat(*_args, **_kwargs):
        return LLMResult(ok=True, model="fake",
                         content='{"intent": "smalltalk", "reply": "你好呀"}')

    monkeypatch.setattr(react_mod.bailian_client, "chat_with_fallback", _fake_chat)
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == "demo"))).scalars().first()
        assert user is not None, "演示账号缺失，请先执行 scripts/init_db.py"
        session = (await db.execute(
            select(ChatSession).where(ChatSession.user_id == user.id)
            .order_by(ChatSession.id.desc())
        )).scalars().first()
        if session is None:
            # 清理演示数据后可能没有会话：自己造一个，别让用例变成 skip
            from app.services import chat_service

            session = await chat_service.create_session(db, user.id, "pytest 会话")
            await db.commit()
        runner = react_mod.AgentRunner(db, user, None)
        parsed = await runner._interpret(session, "帮我给豆豆预约 2026-10-22 11:00 洗澡")
    assert parsed["intent"] == "create_appointment", f"写操作被判成了 {parsed['intent']}"
