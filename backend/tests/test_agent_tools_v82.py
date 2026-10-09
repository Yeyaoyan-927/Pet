"""V8.2 新增的宠主 Agent 能力用例：建档案 / 寄养 / 用品加购与下单 / 实景跳转。

这些用例直接调工具处理函数（不走 LLM），因此不消耗模型额度、也不会因模型波动而失败；
LLM 只负责「选对工具」，工具本身的行为必须是确定的。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import delete, select

from app.agent.react import AgentRunner
from app.agent.tools.registry import TOOLS, ToolContext
from app.database import AsyncSessionLocal
from app.models import (
    BoardingCareLog,
    BoardingCarePlan,
    BoardingOrder,
    BoardingPickupTask,
    CartItem,
    GoodsOrder,
    GoodsOrderItem,
    Pet,
    User,
    VaccineRecord,
)
from app.utils.exceptions import BizError
from tests.conftest import rand_tag

DAYS = 120


async def _user(username: str = "demo") -> User:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalars().first()
    assert user is not None, "演示账号缺失，请先执行 scripts/init_db.py"
    return user


async def _ctx(username: str = "demo") -> ToolContext:
    user = await _user(username)
    db = AsyncSessionLocal()
    session = await db.__aenter__()
    return ToolContext(session, user, None, rand_tag("v82"))


async def _close(ctx: ToolContext) -> None:
    await ctx.db.rollback()
    await ctx.db.close()


async def _cleanup(pet_ids: list[int]) -> None:
    if not pet_ids:
        return
    async with AsyncSessionLocal() as db:
        orders = (await db.execute(
            select(BoardingOrder.id).where(BoardingOrder.pet_id.in_(pet_ids))
        )).scalars().all()
        if orders:
            await db.execute(delete(BoardingPickupTask).where(BoardingPickupTask.order_id.in_(orders)))
            await db.execute(delete(BoardingCareLog).where(BoardingCareLog.order_id.in_(orders)))
            await db.execute(delete(BoardingCarePlan).where(BoardingCarePlan.order_id.in_(orders)))
            await db.execute(delete(BoardingOrder).where(BoardingOrder.id.in_(orders)))
        await db.execute(delete(VaccineRecord).where(VaccineRecord.pet_id.in_(pet_ids)))
        await db.execute(delete(Pet).where(Pet.id.in_(pet_ids)))
        await db.commit()


async def test_create_pet_profile_only_needs_name():
    """只要一个名字就能建档案，其余字段可后补。"""
    ctx = await _ctx()
    name = rand_tag("v82犬")
    try:
        result = await TOOLS["create_pet_profile"]["handler"](
            ctx, name=name, species="dog", weight=6.5, allergy="鸡肉"
        )
        assert result["id"] and result["name"] == name
        assert result["weight"] == 6.5 and result["allergy"] == "鸡肉"

        # 中文物种 / 性别也能正确归一
        other = rand_tag("v82猫")
        res2 = await TOOLS["create_pet_profile"]["handler"](ctx, name=other, species="猫", gender="母")
        pet = (await ctx.db.execute(select(Pet).where(Pet.id == res2["id"]))).scalars().first()
        assert pet.species == "cat" and pet.gender == "female"
    finally:
        ids = []
        for n in (name, locals().get("other")):
            if n:
                async with AsyncSessionLocal() as db:
                    pid = (await db.execute(select(Pet.id).where(Pet.name == n))).scalars().first()
                    if pid:
                        ids.append(pid)
        await _close(ctx)
        await _cleanup(ids)


async def test_boarding_options_and_order_rules():
    """寄养：查资格可用；没疫苗的宠物下单被拦（错误信息要能指导用户）。"""
    ctx = await _ctx()
    name = rand_tag("v82寄养犬")
    ci = date.today() + timedelta(days=DAYS)
    co = ci + timedelta(days=3)
    try:
        created = await TOOLS["create_pet_profile"]["handler"](ctx, name=name, species="dog", weight=7.0)

        options = await TOOLS["query_boarding_options"]["handler"](
            ctx, pet_name=name, check_in=ci.isoformat(), check_out=co.isoformat()
        )
        assert options["eligibility"]["ok"] is False
        assert name in options["eligibility"]["message"], "拒绝原因要带上宠物名字"
        assert options["rooms"], "房型列表不应为空"

        with pytest.raises(BizError) as exc:
            await TOOLS["create_boarding_order"]["handler"](
                ctx, pet_name=name, check_in=ci.isoformat(), check_out=co.isoformat()
            )
        assert "疫苗" in exc.value.message
    finally:
        await _close(ctx)
        async with AsyncSessionLocal() as db:
            pid = (await db.execute(select(Pet.id).where(Pet.name == name))).scalars().first()
        await _cleanup([pid] if pid else [])
        assert created["id"]


async def test_boarding_order_happy_path(monkeypatch):
    """有疫苗的演示宠物：下单成功，房号与费用回填。"""
    ctx = await _ctx()
    ci = date.today() + timedelta(days=DAYS)
    co = ci + timedelta(days=3)
    order_no = None
    try:
        result = await TOOLS["create_boarding_order"]["handler"](
            ctx, pet_name="豆豆", check_in=ci.isoformat(), check_out=co.isoformat()
        )
        order_no = result["order_no"]
        assert order_no.startswith("BG")
        assert result["nights"] == 3 and result["total_amount"] > 0
        assert result["room_no"] and result["status"] == "pending"
    finally:
        await _close(ctx)
        if order_no:
            async with AsyncSessionLocal() as db:
                order = (await db.execute(
                    select(BoardingOrder).where(BoardingOrder.order_no == order_no)
                )).scalars().first()
                if order:
                    for model in (BoardingPickupTask, BoardingCareLog, BoardingCarePlan):
                        await db.execute(delete(model).where(model.order_id == order.id))
                    await db.execute(delete(BoardingOrder).where(BoardingOrder.id == order.id))
                    await db.commit()


async def test_goods_cart_and_order():
    """用品：加购 → 提交订单 → 订单与核销码生成；空购物车提交被拒。"""
    ctx = await _ctx()
    order_no = None
    try:
        # 清空购物车，保证起点干净
        cart = await TOOLS["query_goods"]["handler"](ctx, keyword="洗护")
        assert cart["items"], "演示商品应包含洗护类"
        product = cart["items"][0]["name"]

        added = await TOOLS["add_goods_to_cart"]["handler"](ctx, product_name=product, quantity=2)
        assert added["quantity"] == 2 and added["cart_count"] >= 2

        ordered = await TOOLS["submit_goods_order"]["handler"](ctx, pickup_method="self")
        order_no = ordered["order_no"]
        assert ordered["order_no"].startswith("GD")
        assert ordered["item_count"] >= 2 and ordered["total_amount"] > 0
        assert len(ordered["pickup_code"]) == 8

        # 购物车已清空 → 再提交必须被拒
        with pytest.raises(BizError):
            await TOOLS["submit_goods_order"]["handler"](ctx, pickup_method="self")
    finally:
        await _close(ctx)
        if order_no:
            async with AsyncSessionLocal() as db:
                order = (await db.execute(
                    select(GoodsOrder).where(GoodsOrder.order_no == order_no)
                )).scalars().first()
                if order:
                    await db.execute(delete(GoodsOrderItem).where(GoodsOrderItem.order_id == order.id))
                    await db.execute(delete(GoodsOrder).where(GoodsOrder.id == order.id))
                    await db.commit()
            async with AsyncSessionLocal() as db:
                await db.execute(delete(CartItem))
                await db.commit()


async def test_open_camera_intent_rule():
    """「看看宠物状态」必须识别为 open_camera，而不是宠物档案查询。"""
    user = await _user()
    async with AsyncSessionLocal() as db:
        runner = AgentRunner(db, user, None)
        for text in ("帮我看看宠物的状态", "我想看实景", "打开摄像头看看", "豆豆在干嘛呀"):
            intent = runner._interpret_by_rule(text)["intent"]
            assert intent == "open_camera", f"{text} → {intent}"
        # 员工说「看实景」不该触发宠主跳转
        staff = await _user("staff1")
        runner_staff = AgentRunner(db, staff, None)
        assert runner_staff._interpret_by_rule("看看实景")["intent"] != "open_camera"


# ---------------------------------------------------------------- V8.2.1 回归用例
def test_rule_extracts_pet_profile_slots():
    """建档案的口语槽位必须抽准（回归：用户说「母」曾因未抽取 → 落库成「公」）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.user = type("U", (), {"role": "customer"})()
    parsed = runner._interpret_by_rule("帮我建个档案，叫咪咪，母猫，3岁，体重4.5kg，对鱼肉过敏")
    assert parsed["intent"] == "create_pet_profile"
    slots = parsed["slots"]
    assert slots["name"] == "咪咪"
    assert slots["species"] == "cat"
    assert slots["gender"] == "female", "性别必须被抽取，否则工具会写成默认的公"
    assert slots["weight"] == 4.5
    assert slots["birthday"], "「3 岁」应换算成生日"
    assert slots["allergy"] == "鱼肉"

    male = runner._interpret_by_rule("给我家狗建个档：豆豆，公，金毛，2岁")["slots"]
    assert male["name"] == "豆豆" and male["gender"] == "male" and male["breed"] == "金毛"


@pytest.mark.parametrize(
    "raw,expect",
    [
        ("母", "female"), ("雌", "female"), ("female", "female"), ("妹妹", "female"),
        ("女孩", "female"), ("母猫", "female"),
        ("公", "male"), ("雄", "male"), ("male", "male"), ("弟弟", "male"), ("男孩", "male"),
        (None, None), ("", None), ("不知道", None),
    ],
)
def test_normalize_gender(raw, expect):
    """口语性别归一：认不出就返回 None，绝不静默回落成 male。"""
    from app.agent.tools.registry import normalize_gender

    assert normalize_gender(raw) == expect


async def test_search_products_tolerates_missing_parentheses():
    """商品名缺括号 / 带动词前缀也要能搜到（回归：「成猫全价主粮（三文鱼）」搜不到）。"""
    from app.agent.tools.registry import search_products

    async with AsyncSessionLocal() as db:
        for keyword in ("成猫全价主粮（三文鱼）", "成猫全价主粮三文鱼", "帮我买成猫全价主粮（三文鱼）"):
            items, _used = await search_products(db, keyword)
            assert items, f"{keyword} 应能命中商品"
            assert items[0]["name"] == "成猫全价主粮（三文鱼）"

        empty, _ = await search_products(db, "完全不存在的商品XYZ")
        assert empty == []


async def test_rule_extracts_product_name_with_brackets():
    """「帮我买成猫全价主粮（三文鱼）」要抽出干净商品名，不能带「帮我买」。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.user = type("U", (), {"role": "customer"})()
    parsed = runner._interpret_by_rule("帮我买成猫全价主粮（三文鱼）")
    assert parsed["intent"] == "add_goods_to_cart"
    assert parsed["slots"]["product_name"] == "成猫全价主粮（三文鱼）"
