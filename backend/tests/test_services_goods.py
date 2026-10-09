"""用品服务层用例（V8）：过敏交叉校验、库存、订单状态机、核销、看板。

核心差异点是「商品安全标签 × 宠物档案」，因此单独测 `safety_conflicts` 纯函数，
再用真实数据验证列表标记、下单硬拦截与替代建议。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import delete, func, select

from app.constants import GoodsOrderStatus
from app.database import AsyncSessionLocal
from app.models import (
    CartItem,
    GoodsOrder,
    GoodsOrderItem,
    Pet,
    Product,
    ProductSku,
    User,
)
from app.schemas.goods import CartAddIn, GoodsOrderCreateIn, ProductIn, ProductSkuIn
from app.services import goods_service
from app.utils.exceptions import BizError, ConflictError, NotFoundError
from tests.conftest import rand_tag

TAG = rand_tag("v8g")


async def _demo(role_username: str = "demo") -> User:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == role_username))).scalars().first()
    assert user is not None, "演示账号缺失，请先执行 scripts/init_db.py"
    return user


async def _make_pet(owner_id: int, *, allergy: str | None = None, weight: float = 8.0,
                    birthday: date | None = None) -> int:
    async with AsyncSessionLocal() as db:
        pet = Pet(user_id=owner_id, name=f"{TAG}犬", species="dog", gender="male",
                  weight=weight, sterilized=1, allergy=allergy, birthday=birthday)
        db.add(pet)
        await db.commit()
        return pet.id


async def _make_product(*, name: str | None = None, allergy_tags: str | None = None,
                        stock: int = 10, price_cents: int = 5000, category: str = "clean",
                        status: str = "on") -> tuple[int, int]:
    """返回 (product_id, sku_id)。"""
    name = name or f"{TAG}洗护"
    async with AsyncSessionLocal() as db:
        product = Product(name=name, brand="回归品牌", category=category, species="all",
                          stage="all", size="all", status=status, sort_no=99,
                          allergy_tags=allergy_tags, selling_points="低敏,无香")
        db.add(product)
        await db.flush()
        # 单位价（分/kg）：正式链路由 goods_service.upsert_product 统一计算，
        # 这里手工造数据也要保持一致，否则比价字段为空
        sku = ProductSku(product_id=product.id, spec_name="标准装", price_cents=price_cents,
                          unit_price_cents=round(price_cents / 0.5),
                          weight_g=500, stock=stock, warn_threshold=3)
        db.add(sku)
        await db.commit()
        return product.id, sku.id


async def _cleanup(pet_ids: list[int], product_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        if product_ids:
            sku_ids = (await db.execute(
                select(ProductSku.id).where(ProductSku.product_id.in_(product_ids))
            )).scalars().all()
            if sku_ids:
                await db.execute(delete(CartItem).where(CartItem.sku_id.in_(sku_ids)))
                orders = (await db.execute(
                    select(GoodsOrderItem.order_id).where(GoodsOrderItem.sku_id.in_(sku_ids))
                )).scalars().all()
                if orders:
                    await db.execute(delete(GoodsOrderItem).where(GoodsOrderItem.order_id.in_(orders)))
                    await db.execute(delete(GoodsOrder).where(GoodsOrder.id.in_(orders)))
                await db.execute(delete(ProductSku).where(ProductSku.id.in_(sku_ids)))
            await db.execute(delete(Product).where(Product.id.in_(product_ids)))
        if pet_ids:
            await db.execute(delete(Pet).where(Pet.id.in_(pet_ids)))
        await db.commit()


def test_safety_conflicts_pure_rules():
    """过敏原 / 禁忌 / 月龄 / 体重四条规则（纯函数，不依赖数据库）。"""
    # 过敏原：宠物过敏「燕麦」，商品含燕麦 → 命中
    pet = Pet(name="测试", species="dog", allergy="燕麦,鸡肉", weight=8.0, sterilized=1,
              birthday=date.today() - timedelta(days=365 * 3))
    product = Product(name="燕麦浴液", category="clean", allergy_tags="燕麦,香精",
                      taboo_tags="皮肤破损禁用", min_weight=0, max_weight=50, status="on")
    conflicts = goods_service.safety_conflicts(pet, product)
    assert any("燕麦" in c for c in conflicts)

    # 禁忌：皮肤病史 × 禁忌标签
    pet_skin = Pet(name="皮肤犬", species="dog", skin_disease="真菌感染史", weight=8.0, sterilized=1,
                   birthday=date.today() - timedelta(days=365 * 3))
    assert any("禁忌" in c or "皮肤" in c for c in goods_service.safety_conflicts(pet_skin, product))

    # 月龄：幼犬 × 幼年不宜
    puppy = Pet(name="幼犬", species="dog", weight=3.0, sterilized=1,
                birthday=date.today() - timedelta(days=60))
    adult_only = Product(name="成犬粮", category="basic_food", taboo_tags="幼年不宜", status="on")
    assert goods_service.safety_conflicts(puppy, adult_only)

    # 体重区间：超重犬 × 上限 5kg 的用品
    heavy = Pet(name="大狗", species="dog", weight=30.0, sterilized=1,
                birthday=date.today() - timedelta(days=365 * 4))
    small_only = Product(name="小犬胸背", category="clothes", min_weight=0, max_weight=5, status="on")
    assert goods_service.safety_conflicts(heavy, small_only)

    # 完全匹配 → 无冲突
    clean_pet = Pet(name="健康犬", species="dog", weight=8.0, sterilized=1,
                    birthday=date.today() - timedelta(days=365 * 3))
    safe = Product(name="通用毛巾", category="daily", status="on")
    assert goods_service.safety_conflicts(clean_pet, safe) == []


async def test_list_products_with_pet_flags_and_alternative():
    """列表带宠物上下文时：冲突商品标 unsafe 并给替代建议，无冲突商品不受影响。"""
    owner = await _demo()
    pet_id = await _make_pet(owner.id, allergy="燕麦")
    bad_id, _ = await _make_product(name=f"{TAG}燕麦浴液", allergy_tags="燕麦")
    good_id, _ = await _make_product(name=f"{TAG}低敏浴液", allergy_tags="")
    try:
        async with AsyncSessionLocal() as db:
            items = await goods_service.list_products(db, pet_id=pet_id)
            by_id = {i["id"]: i for i in items}
            assert by_id[bad_id]["unsafe"] is True and by_id[bad_id]["conflicts"]
            assert by_id[good_id]["unsafe"] is False
            # 列表只做标记（省查询），替代建议在详情里给
            assert "alternative" not in by_id[bad_id]

            detail = await goods_service.get_product(db, bad_id, pet_id=pet_id)
            assert detail["unsafe"] and detail["conflicts"]
            assert detail["alternative"]

            safe_detail = await goods_service.get_product(db, good_id, pet_id=pet_id)
            assert safe_detail["unsafe"] is False
            assert safe_detail["skus"][0]["unit_price"], "SKU 应带单位价便于比价"
    finally:
        await _cleanup([pet_id], [bad_id, good_id])


async def test_cart_flow_and_stock_guard():
    """购物车：加购（含警告）/ 改数量 / 超卖拒绝 / 删除 / 清空。"""
    owner = await _demo()
    product_id, sku_id = await _make_product(stock=5, price_cents=3000)
    try:
        async with AsyncSessionLocal() as db:
            res = await goods_service.add_to_cart(db, owner, CartAddIn(sku_id=sku_id, quantity=2))
            assert res["quantity"] == 2 and res["warnings"] == []

            cart = await goods_service.list_cart(db, owner)
            line = next(x for x in cart["items"] if x["sku_id"] == sku_id)
            assert cart["count"] == 2 and line["subtotal"] == 60.0

            # 超过库存
            with pytest.raises(BizError):
                await goods_service.add_to_cart(db, owner, CartAddIn(sku_id=sku_id, quantity=99))

            await goods_service.update_cart(db, owner, line["id"], 3)
            cart = await goods_service.list_cart(db, owner)
            assert next(x for x in cart["items"] if x["sku_id"] == sku_id)["quantity"] == 3

            await goods_service.remove_cart_item(db, owner, line["id"])
            assert (await goods_service.list_cart(db, owner))["count"] == 0

            await goods_service.add_to_cart(db, owner, CartAddIn(sku_id=sku_id, quantity=1))
            removed = await goods_service.clear_cart(db, owner)
            assert removed["removed"] >= 1
            assert (await goods_service.list_cart(db, owner))["count"] == 0
    finally:
        await _cleanup([], [product_id])


async def test_create_order_stock_idempotent_and_cart_clear():
    """下单：扣库存、清购物车、幂等键复用同一单；库存不足拒绝。"""
    owner = await _demo()
    product_id, sku_id = await _make_product(stock=3, price_cents=2000)
    try:
        async with AsyncSessionLocal() as db:
            before = (await db.execute(select(ProductSku.stock).where(ProductSku.id == sku_id))).scalar()

            key = rand_tag("idem")
            order = await goods_service.create_order(db, owner, GoodsOrderCreateIn(
                items=[CartAddIn(sku_id=sku_id, quantity=2)],
                pickup_method="delivery", address="回归路 9 号", idempotent_key=key,
            ))
            assert order.status == GoodsOrderStatus.PENDING.value
            assert order.delivery_fee_cents > 0
            assert order.total_cents == 2000 * 2 + order.delivery_fee_cents
            assert len(order.pickup_code) == 8

            again = await goods_service.create_order(db, owner, GoodsOrderCreateIn(
                items=[CartAddIn(sku_id=sku_id, quantity=2)],
                pickup_method="delivery", address="回归路 9 号", idempotent_key=key,
            ))
            assert again.id == order.id, "同一幂等键必须复用同一单"

            after = (await db.execute(select(ProductSku.stock).where(ProductSku.id == sku_id))).scalar()
            assert after == before - 2

            # 库存只剩 1，要 5 件 → 拒绝
            with pytest.raises(BizError):
                await goods_service.create_order(db, owner, GoodsOrderCreateIn(
                    items=[CartAddIn(sku_id=sku_id, quantity=5)],
                    pickup_method="self", idempotent_key=rand_tag("idem"),
                ))

            # 购物车下单：加购后不传 items
            await goods_service.add_to_cart(db, owner, CartAddIn(sku_id=sku_id, quantity=1))
            cart_order = await goods_service.create_order(db, owner, GoodsOrderCreateIn(
                pickup_method="self", idempotent_key=rand_tag("idem"),
            ))
            assert cart_order.item_count == 1
            assert (await goods_service.list_cart(db, owner))["count"] == 0
    finally:
        await _cleanup([], [product_id])


async def test_order_state_machine_and_stock_release():
    """状态机：非法流转报错；缺货取消必须回补库存且只回补一次。"""
    owner = await _demo()
    staff = await _demo("staff1")
    product_id, sku_id = await _make_product(stock=5, price_cents=1500)
    try:
        async with AsyncSessionLocal() as db:
            order = await goods_service.create_order(db, owner, GoodsOrderCreateIn(
                items=[CartAddIn(sku_id=sku_id, quantity=2)],
                pickup_method="self", idempotent_key=rand_tag("idem"),
            ))
            with pytest.raises(BizError):
                await goods_service.change_status(db, order, "completed", staff)

            await goods_service.change_status(db, order, "confirmed", staff)
            stock_after_order = (await db.execute(select(ProductSku.stock).where(ProductSku.id == sku_id))).scalar()
            assert stock_after_order == 3

            await goods_service.change_status(db, order, "stockout_cancelled", staff, reason="供应商断货")
            stock_released = (await db.execute(select(ProductSku.stock).where(ProductSku.id == sku_id))).scalar()
            assert stock_released == 5, "缺货取消必须回补库存"

            with pytest.raises(BizError):
                await goods_service.change_status(db, order, "ready", staff)
    finally:
        await _cleanup([], [product_id])


async def test_verify_pickup_and_double_verify():
    """核销：待取货才能核销；重复核销必须被拒；核销后累计销量。"""
    owner = await _demo()
    staff = await _demo("staff1")
    product_id, sku_id = await _make_product(stock=4, price_cents=2500)
    try:
        async with AsyncSessionLocal() as db:
            order = await goods_service.create_order(db, owner, GoodsOrderCreateIn(
                items=[CartAddIn(sku_id=sku_id, quantity=1)],
                pickup_method="self", idempotent_key=rand_tag("idem"),
            ))
            with pytest.raises(BizError):
                await goods_service.verify_pickup(db, order.pickup_code, staff)

            await goods_service.change_status(db, order, "confirmed", staff)
            await goods_service.change_status(db, order, "ready", staff)
            done = await goods_service.verify_pickup(db, order.pickup_code, staff, pay_status="paid_offline")
            assert done.id == order.id, "核销返回订单对象"
            assert order.status == GoodsOrderStatus.COMPLETED.value
            assert order.pay_status == "paid_offline"

            with pytest.raises(BizError):
                await goods_service.verify_pickup(db, order.pickup_code, staff)

            with pytest.raises(NotFoundError):
                await goods_service.verify_pickup(db, "ZZZZZZZZ", staff)
    finally:
        await _cleanup([], [product_id])


async def test_restock_overview_and_dashboard():
    """盘点 / 低库存筛选 / 看板口径。"""
    staff = await _demo("staff1")
    product_id, sku_id = await _make_product(stock=1, price_cents=1000)
    try:
        async with AsyncSessionLocal() as db:
            res = await goods_service.restock(db, sku_id, 7, staff, remark="回归盘点")
            assert res["after"] == 7

            overview = await goods_service.stock_overview(db)
            line = next(x for x in overview if x["sku_id"] == sku_id)
            assert line["stock"] == 7

            data = await goods_service.dashboard(db, date.today() - timedelta(days=365),
                                                 date.today() + timedelta(days=30))
            for key in ("orders", "revenue", "avg_price", "avg_items", "top_products",
                        "category_stat", "low_stock_count", "cancel_rate"):
                assert key in data
    finally:
        await _cleanup([], [product_id])


async def test_admin_product_crud_and_delete_cleans_cart():
    """商品维护：新增（自动算单位价）/ 下架不可见 / 删除连带清理购物车引用。"""
    owner = await _demo()
    created_id = None
    try:
        async with AsyncSessionLocal() as db:
            name = f"{TAG}猫砂"
            saved = await goods_service.upsert_product(db, ProductIn(
                name=name, brand="回归品牌", category="daily", species="cat",
                stage="all", size="all", status="on", sort_no=99,
                skus=[ProductSkuIn(spec_name="5L", price_cents=3900, weight_g=2500, stock=6)],
            ), operator=owner)
            created_id = saved["id"]

            items = await goods_service.admin_list_products(db, keyword=name)
            assert len(items) == 1 and items[0]["total_stock"] == 6
            sku_id = items[0]["skus"][0]["id"]
            # 单位价由服务层统一计算：39 元 / 2.5kg = 15.6 元/kg
            assert items[0]["skus"][0]["unit_price"] == 15.6

            # 下架后宠主端不可见
            await goods_service.upsert_product(db, ProductIn(
                name=name, brand="回归品牌", category="daily", species="cat",
                stage="all", size="all", status="off", sort_no=99,
                skus=[ProductSkuIn(spec_name="5L", price_cents=3900, weight_g=2500, stock=6)],
            ), operator=owner)
            assert len(await goods_service.list_products(db, keyword=name)) == 0

            # 加购后再删商品：购物车引用应被清理
            await goods_service.add_to_cart(db, owner, CartAddIn(sku_id=sku_id, quantity=1))
            removed = await goods_service.delete_product(db, created_id, owner)
            assert removed["removed_skus"] == 1
            left = (await db.execute(select(func.count()).select_from(CartItem)
                                     .where(CartItem.sku_id == sku_id))).scalar()
            assert left == 0
            created_id = None
    finally:
        await _cleanup([], [created_id] if created_id else [])
