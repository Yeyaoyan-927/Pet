"""V7.2 用品核心回归：库存并发防超卖 + 过敏交叉校验。

两点和寄养同源：
- 库存扣减是 check-then-act，必须「锁 SKU 行 + 当前读」；
- 过敏校验是**硬拦截**（不是提示），因为它关系到宠物安全。
"""
from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.models import CartItem, GoodsOrder, GoodsOrderItem, Pet, Product, ProductSku, User
from app.schemas.goods import GoodsOrderCreateIn
from app.services import goods_service
from app.utils.exceptions import BizError, ConflictError
from tests.conftest import cleanup, get_user_id, rand_tag


async def _prepare(owner_id: int, tag: str, *, stock: int = 1) -> tuple[int, int, int, int]:
    """造商品 + SKU（指定库存）+ 一只过敏宠物，返回 (sku_id, product_id, pet_id, order_base)。"""
    async with AsyncSessionLocal() as db:
        product = Product(name=f"{tag}低敏浴液", category="clean", species="all",
                          stage="all", size="all", allergy_tags="燕麦", status="on")
        db.add(product)
        await db.flush()
        sku = ProductSku(product_id=product.id, spec_name="测试规格", price_cents=5000,
                         weight_g=500, stock=stock, warn_threshold=1)
        pet = Pet(user_id=owner_id, name=f"{tag}过敏犬", species="dog", gender="male",
                  sterilized=1, weight=12, allergy="对含燕麦成分的浴液过敏")
        db.add_all([sku, pet])
        await db.commit()
        return sku.id, product.id, pet.id, product.id


async def _order(owner_id: int, sku_id: int, key: str, pet_id: int | None = None) -> str:
    """一次并发下单：独占会话（等价于一个独立 HTTP 请求）。"""
    async with AsyncSessionLocal() as db:
        owner = await db.get(User, owner_id)
        payload = GoodsOrderCreateIn(
            items=[{"sku_id": sku_id, "quantity": 1, "pet_id": pet_id}],
            pickup_method="self", idempotent_key=key,
        )
        try:
            await goods_service.create_order(db, owner, payload)
            return "ok"
        except (ConflictError, BizError):
            await db.rollback()
            return "reject"
        except Exception as exc:
            await db.rollback()
            return f"error:{type(exc).__name__}"


async def test_concurrent_goods_order_never_oversells():
    """库存 1 时 4 个并发下单：恰好 1 单成功，库存归零且不为负。"""
    owner_id = await get_user_id("demo")
    tag = rand_tag("v7goods")
    sku_id, product_id, _pet_id, _ = await _prepare(owner_id, tag, stock=1)
    try:
        results = await asyncio.gather(*[
            _order(owner_id, sku_id, f"{tag}-{i}") for i in range(4)
        ])
        assert results.count("ok") == 1, f"库存超卖：成功 {results.count('ok')} 单 → {results}"
        assert results.count("reject") == 3, results

        async with AsyncSessionLocal() as db:
            sku = await db.get(ProductSku, sku_id)
            assert sku.stock == 0, f"库存应为 0，实际 {sku.stock}"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(GoodsOrderItem).where(GoodsOrderItem.product_id == product_id))
            await db.execute(delete(GoodsOrder).where(GoodsOrder.idempotent_key.like(f"{tag}-%")))
            await db.execute(delete(CartItem).where(CartItem.sku_id == sku_id))
            await db.execute(delete(ProductSku).where(ProductSku.id == sku_id))
            await db.execute(delete(Product).where(Product.id == product_id))
            await db.commit()
        async with AsyncSessionLocal() as db:
            await cleanup(db, pet_ids=[_pet_id])


async def test_allergy_blocks_order():
    """商品过敏原与宠物档案命中时，下单必须被硬拦截（不是提示）。"""
    owner_id = await get_user_id("demo")
    tag = rand_tag("v7allergy")
    sku_id, product_id, pet_id, _ = await _prepare(owner_id, tag, stock=5)
    try:
        async with AsyncSessionLocal() as db:
            owner = await db.get(User, owner_id)
            try:
                await goods_service.create_order(db, owner, GoodsOrderCreateIn(
                    items=[{"sku_id": sku_id, "quantity": 1, "pet_id": pet_id}],
                    pickup_method="self", idempotent_key=f"{tag}-blocked",
                ))
                raise AssertionError("过敏商品仍下单成功，硬拦截失效")
            except BizError as exc:
                assert "燕麦" in str(exc) or "不适合" in str(exc), str(exc)
                await db.rollback()

        # 不关联宠物时可以买（自用/代买场景），说明校验是精准的而非一刀切
        async with AsyncSessionLocal() as db:
            owner = await db.get(User, owner_id)
            order = await goods_service.create_order(db, owner, GoodsOrderCreateIn(
                items=[{"sku_id": sku_id, "quantity": 1}],
                pickup_method="self", idempotent_key=f"{tag}-ok",
            ))
            assert order.total_cents == 5000, order.total_cents
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(GoodsOrderItem).where(GoodsOrderItem.product_id == product_id))
            await db.execute(delete(GoodsOrder).where(GoodsOrder.idempotent_key.like(f"{tag}-%")))
            await db.execute(delete(CartItem).where(CartItem.sku_id == sku_id))
            await db.execute(delete(ProductSku).where(ProductSku.id == sku_id))
            await db.execute(delete(Product).where(Product.id == product_id))
            await db.commit()
        async with AsyncSessionLocal() as db:
            await cleanup(db, pet_ids=[pet_id])
