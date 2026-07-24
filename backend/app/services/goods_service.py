"""宠物用品业务服务（V7.2）。

三个工程约束：
1. **库存用「锁 SKU 行 + 当前读」扣减**：`SELECT ... FOR UPDATE` 拿到最新库存再判断，
   避免 check-then-act 超卖（沿用 V6 的教训：只加锁不做当前读，在 REPEATABLE READ 下等于没防）。
2. **过敏交叉校验是硬拦截**：商品安全标签与宠物档案 `allergy` 命中即拒绝下单，并给出同类替代建议。
3. **金额一律用「分」整数**；订单明细存**价格快照**，商品改价不影响历史订单。
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    GOODS_PAY_LABEL,
    GOODS_REASON_REQUIRED_STATUS,
    GOODS_STATUS_LABEL,
    GOODS_TERMINAL_STATUS,
    GOODS_TRANSITIONS,
    PICKUP_METHOD_LABEL,
    PRODUCT_CATEGORY_LABEL,
    PRODUCT_SIZE_LABEL,
    PRODUCT_STAGE_LABEL,
    GoodsOrderStatus,
    GoodsPayStatus,
    MessageType,
    PickupMethod,
    UserRole,
)
from app.models import CartItem, GoodsOrder, GoodsOrderItem, Pet, Product, ProductSku, User
from app.schemas.goods import CartAddIn, GoodsOrderCreateIn
from app.services import message_service, setting_service
from app.services import setting_service
from app.services.audit_service import write_log
from app.utils.datetime_util import calc_age_month, gen_order_no, now
from app.utils.exceptions import BizError, ConflictError, NotFoundError, PermissionError_, StateMachineError
from app.utils.logger import logger

SELECTABLE_STATUS = set(GOODS_TRANSITIONS)


def gen_pickup_code() -> str:
    """核销码：8 位大写字母 + 数字，剔除易混淆的 0/O/1/I，方便店员口述或手输。"""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choices(alphabet, k=8))



# ---------------------------------------------------------------- 安全交叉校验
def _split(raw: str | None) -> list[str]:
    """逗号分隔串转数组（标签字段的统一解析）。


    """
    return [t.strip() for t in (raw or "").replace("，", ",").split(",") if t.strip()]


def safety_conflicts(pet: Pet, product: Product) -> list[str]:
    """商品安全标签 × 宠物档案交叉校验，返回冲突说明列表（空表示安全）。

    匹配策略刻意宽松：标签用前 2 个字做包含匹配，容忍「含燕麦」vs「对含燕麦成分的浴液过敏」
    这类自由文本差异 —— 宁可多提示一次，也不要放过一次过敏风险。
    """
    conflicts: list[str] = []
    allergy_text = f"{pet.allergy or ''}{pet.skin_disease or ''}"

    for tag in _split(product.allergy_tags):
        key = tag[:2]
        if key and key in allergy_text:
            conflicts.append(f"含「{tag}」，与档案过敏史冲突")

    month = calc_age_month(pet.birthday) or 0
    for tag in _split(product.taboo_tags):
        if "幼" in tag and 0 < month < 12:
            conflicts.append(f"标注「{tag}」，该毛孩子仅 {month} 月龄")
        elif "老年" in tag and month >= 96:
            conflicts.append(f"标注「{tag}」，该毛孩子已 {month} 月龄")
        elif "皮肤" in tag and (pet.skin_disease or "").strip():
            conflicts.append(f"标注「{tag}」，档案有皮肤病史")
        elif "孕" in tag and pet.sterilized == 0:
            conflicts.append(f"标注「{tag}」，该毛孩子未绝育需先确认")

    if product.min_weight and pet.weight is not None and float(pet.weight) < product.min_weight:
        conflicts.append(f"适用体重 ≥{product.min_weight}kg，当前 {pet.weight}kg")
    if product.max_weight and pet.weight is not None and float(pet.weight) > product.max_weight:
        conflicts.append(f"适用体重 ≤{product.max_weight}kg，当前 {pet.weight}kg")
    return conflicts


async def _alternative_for(
    db: AsyncSession, product: Product, pet: Pet | None
) -> dict | None:
    """命中过敏时给一个同类且安全的替代建议（没有就返回 None，不硬凑）。"""
    rows = (
        await db.execute(
            select(Product, ProductSku)
            .join(ProductSku, ProductSku.product_id == Product.id)
            .where(
                Product.id != product.id, Product.status == "on", ProductSku.enabled == 1,
                ProductSku.stock > 0, Product.category == product.category,
            ).order_by(Product.sort_no).limit(6)
        )
    ).all()
    for alt, sku in rows:
        if pet is not None and safety_conflicts(pet, alt):
            continue
        return {"id": alt.id, "name": alt.name, "price": sku.price_cents / 100}
    return None


# ---------------------------------------------------------------- 商品
async def list_products(
    db: AsyncSession, *, category: str | None = None, keyword: str | None = None,
    species: str | None = None, pet_id: int | None = None, sort: str = "default",
) -> list[dict]:
    """商品列表。传 `pet_id` 时附带该宠物的安全校验结果（用于列表上的安全角标）。"""
    cond = [Product.status == "on"]
    if category:
        cond.append(Product.category == category)
    if species:
        cond.append(or_(Product.species == species, Product.species == "all"))
    kw = (keyword or "").strip()
    if kw:
        cond.append(or_(Product.name.like(f"%{kw}%"), Product.brand.like(f"%{kw}%")))

    order_by = Product.sort_no.asc()
    if sort == "price":
        order_by = Product.sort_no.asc()  # 价格排序在取到 SKU 后于 Python 层处理
    elif sort == "sales":
        order_by = Product.sales_count.desc()

    products = (await db.execute(select(Product).where(*cond).order_by(order_by))).scalars().all()
    skus = (await db.execute(
        select(ProductSku).where(ProductSku.product_id.in_([p.id for p in products]),
                                 ProductSku.enabled == 1)
    )).scalars().all() if products else []

    pet = await _load_pet(db, pet_id) if pet_id else None
    by_product: dict[int, list[ProductSku]] = {}
    for sku in skus:
        by_product.setdefault(sku.product_id, []).append(sku)

    items = []
    for product in products:
        product_skus = sorted(by_product.get(product.id, []), key=lambda s: s.price_cents)
        if not product_skus:
            continue
        conflicts = safety_conflicts(pet, product) if pet else []
        items.append({
            "id": product.id, "name": product.name, "brand": product.brand,
            "category": product.category, "category_label": PRODUCT_CATEGORY_LABEL.get(product.category, product.category),
            "species": product.species, "stage": product.stage, "stage_label": PRODUCT_STAGE_LABEL.get(product.stage, product.stage),
            "size": product.size, "size_label": PRODUCT_SIZE_LABEL.get(product.size, product.size),
            "main_image": product.main_image,
            "selling_points": _split(product.selling_points), "promo_tags": _split(product.promo_tags),
            "allergy_tags": _split(product.allergy_tags), "taboo_tags": _split(product.taboo_tags),
            "min_price": product_skus[0].price_cents / 100,
            "max_price": product_skus[-1].price_cents / 100,
            "total_stock": sum(s.stock for s in product_skus),
            "sales_count": product.sales_count,
            "skus": [sku_to_out(s) for s in product_skus],
            "unsafe": bool(conflicts), "conflicts": conflicts,
        })
    if sort == "price":
        items.sort(key=lambda i: i["min_price"])
    return items


async def get_product(db: AsyncSession, product_id: int, *, pet_id: int | None = None) -> dict:
    """商品详情：按宠物做过敏与禁忌交叉校验，命中时给同类替代建议。"""
    product = (await db.execute(select(Product).where(Product.id == product_id))).scalars().first()
    if product is None:
        raise NotFoundError("商品不存在")
    skus = (await db.execute(
        select(ProductSku).where(ProductSku.product_id == product.id, ProductSku.enabled == 1)
        .order_by(ProductSku.price_cents)
    )).scalars().all()

    pet = await _load_pet(db, pet_id) if pet_id else None
    conflicts = safety_conflicts(pet, product) if pet else []
    alt = await _alternative_for(db, product, pet) if conflicts else None
    return {
        "id": product.id, "name": product.name, "brand": product.brand,
        "category": product.category, "category_label": PRODUCT_CATEGORY_LABEL.get(product.category, product.category),
        "species": product.species, "stage": product.stage, "stage_label": PRODUCT_STAGE_LABEL.get(product.stage, product.stage),
        "size": product.size, "size_label": PRODUCT_SIZE_LABEL.get(product.size, product.size),
        "main_image": product.main_image, "detail": product.detail,
        "selling_points": _split(product.selling_points), "promo_tags": _split(product.promo_tags),
        "allergy_tags": _split(product.allergy_tags), "taboo_tags": _split(product.taboo_tags),
        "min_weight": product.min_weight, "max_weight": product.max_weight,
        "skus": [sku_to_out(s) for s in skus],
        "unsafe": bool(conflicts), "conflicts": conflicts,
        "pet_name": pet.name if pet else None,
        "alternative": alt,
    }


def sku_to_out(sku: ProductSku) -> dict:
    """SKU 序列化：价格由分转元，补单位价（元/kg）便于比价。"""
    return {
        "id": sku.id, "spec_name": sku.spec_name,
        "price": sku.price_cents / 100, "price_cents": sku.price_cents,
        "unit_price": (sku.unit_price_cents / 100) if sku.unit_price_cents else None,
        "weight_g": sku.weight_g, "stock": sku.stock,
        "low_stock": sku.stock <= sku.warn_threshold, "barcode": sku.barcode,
    }


async def _load_pet(db: AsyncSession, pet_id: int) -> Pet:
    """按 ID 取宠物档案（用品校验需要过敏史、月龄与体重）。


    """
    pet = (await db.execute(
        select(Pet).where(Pet.id == pet_id, Pet.deleted_at.is_(None))
    )).scalars().first()
    if pet is None:
        raise NotFoundError("宠物档案不存在")
    return pet


# ---------------------------------------------------------------- 购物车
async def add_to_cart(db: AsyncSession, user: User, payload: CartAddIn) -> dict:
    """加入购物车：库存不足直接拒绝；命中过敏/禁忌**只警告不拦截**（允许先看看）。"""
    sku = await _load_sku(db, payload.sku_id, lock=False)
    if sku.stock < payload.quantity:
        raise ConflictError(f"库存不足（剩余 {sku.stock} 件）")

    product = (await db.execute(select(Product).where(Product.id == sku.product_id))).scalars().first()
    warnings: list[str] = []
    if payload.pet_id:
        pet = await _load_pet(db, payload.pet_id)
        if pet.user_id != user.id and user.role == UserRole.CUSTOMER.value:
            raise PermissionError_("只能关联自己的宠物")
        conflicts = safety_conflicts(pet, product)
        if conflicts:
            warnings = conflicts  # 加购只警告，下单才硬拦截（允许先看看）

    item = (await db.execute(
        select(CartItem).where(
            CartItem.user_id == user.id, CartItem.sku_id == payload.sku_id,
            CartItem.pet_id == payload.pet_id if payload.pet_id else CartItem.pet_id.is_(None),
        )
    )).scalars().first()
    if item is None:
        item = CartItem(user_id=user.id, sku_id=payload.sku_id,
                        quantity=payload.quantity, pet_id=payload.pet_id)
        db.add(item)
    else:
        item.quantity = min(item.quantity + payload.quantity, 99)
    await db.commit()
    return {"sku_id": sku.id, "quantity": item.quantity, "warnings": warnings}


async def list_cart(db: AsyncSession, user: User) -> dict:
    """购物车内容：逐行标注是否与该商品关联宠物的档案冲突。"""
    rows = (await db.execute(
        select(CartItem, ProductSku, Product)
        .join(ProductSku, ProductSku.id == CartItem.sku_id)
        .join(Product, Product.id == ProductSku.product_id)
        .where(CartItem.user_id == user.id).order_by(CartItem.id.desc())
    )).all()
    pets = {p.id: p for p in (await db.execute(
        select(Pet).where(Pet.user_id == user.id, Pet.deleted_at.is_(None))
    )).scalars().all()}

    items, total, count = [], 0, 0
    for item, sku, product in rows:
        pet = pets.get(item.pet_id) if item.pet_id else None
        conflicts = safety_conflicts(pet, product) if pet else []
        subtotal = sku.price_cents * item.quantity
        total += subtotal
        count += item.quantity
        items.append({
            "id": item.id, "sku_id": sku.id, "product_id": product.id,
            "product_name": product.name, "spec_name": sku.spec_name,
            "image": product.main_image, "price": sku.price_cents / 100,
            "quantity": item.quantity, "subtotal": subtotal / 100,
            "stock": sku.stock,
            "pet_id": item.pet_id, "pet_name": pet.name if pet else None,
            "unsafe": bool(conflicts), "conflicts": conflicts,
        })
    return {"items": items, "total": total / 100, "count": count}


async def update_cart(db: AsyncSession, user: User, cart_id: int, quantity: int) -> dict:
    """改数量（0 视为删除），仍受库存上限约束。"""
    item = (await db.execute(
        select(CartItem).where(CartItem.id == cart_id, CartItem.user_id == user.id)
    )).scalars().first()
    if item is None:
        raise NotFoundError("购物车条目不存在")
    if quantity == 0:
        await db.delete(item)
    else:
        sku = await _load_sku(db, item.sku_id, lock=False)
        if sku.stock < quantity:
            raise ConflictError(f"库存不足（剩余 {sku.stock} 件）")
        item.quantity = quantity
    await db.commit()
    return {"id": cart_id, "quantity": quantity}


async def clear_cart(db: AsyncSession, user: User) -> dict:
    """清空购物车，返回移除条数。"""
    items = (await db.execute(select(CartItem).where(CartItem.user_id == user.id))).scalars().all()
    for item in items:
        await db.delete(item)
    await db.commit()
    return {"removed": len(items)}


async def remove_cart_item(db: AsyncSession, user: User, cart_id: int) -> dict:
    """删除单行，并校验该行属于当前用户。"""
    return await update_cart(db, user, cart_id, 0)


# ---------------------------------------------------------------- 库存
async def _load_sku(db: AsyncSession, sku_id: int, *, lock: bool) -> ProductSku:
    """读取 SKU。

    `lock=True` 时不仅加 `FOR UPDATE`（数据库层面的当前读），还必须 `populate_existing=True`：
    否则 SQLAlchemy 的 **identity map 会返回本会话中此前已加载的旧对象**，
    `sku.stock` 仍是旧值 —— 锁加了、当前读也发了，判断却用旧数据，照样超卖（实测 4 并发 4 单全成功）。
    """
    stmt = select(ProductSku).where(ProductSku.id == sku_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    sku = (await db.execute(stmt)).scalars().first()
    if sku is None or (not lock and not sku.enabled):
        raise NotFoundError("商品规格不存在或已下架")
    return sku


async def _deduct_stock(db: AsyncSession, sku_id: int, quantity: int) -> ProductSku:
    """扣减库存：锁行后按最新库存判断，防超卖。"""
    sku = await _load_sku(db, sku_id, lock=True)
    if not sku.enabled:
        raise BizError(f"「{sku.spec_name}」已下架")
    if sku.stock < quantity:
        raise ConflictError(f"「{sku.spec_name}」库存不足（剩余 {sku.stock} 件，需要 {quantity} 件）")
    sku.stock -= quantity
    return sku


async def _restore_stock(db: AsyncSession, sku_id: int, quantity: int) -> None:
    """回补库存（取消 / 缺货取消时调用），与扣减一样走锁行 + 当前读。


    """
    sku = await _load_sku(db, sku_id, lock=True)
    sku.stock += quantity


# ---------------------------------------------------------------- 下单
async def create_order(
    db: AsyncSession, user: User, payload: GoodsOrderCreateIn, request: Request | None = None
) -> GoodsOrder:
    """下单主链路：来源可为 items 或购物车 → 过敏**硬拦截** → 锁 SKU 行 + 当前读扣库存 →

        生成核销码 → 清空购物车 → 审计与站内信。幂等键命中直接回已有单。
    """
    if payload.idempotent_key:
        existed = (await db.execute(
            select(GoodsOrder).where(GoodsOrder.user_id == user.id,
                                     GoodsOrder.idempotent_key == payload.idempotent_key)
        )).scalars().first()
        if existed is not None:
            return existed

    # 1) 收集条目：直接下单 or 取购物车
    raw_items: list[tuple[int, int, int | None]]
    cart_items: list[CartItem] = []
    if payload.items:
        raw_items = [(i.sku_id, i.quantity, i.pet_id) for i in payload.items]
    else:
        cart_items = (await db.execute(
            select(CartItem).where(CartItem.user_id == user.id)
        )).scalars().all()
        if not cart_items:
            raise BizError("购物车是空的，先挑几件吧")
        raw_items = [(c.sku_id, c.quantity, c.pet_id) for c in cart_items]

    if len(raw_items) > 30:
        raise BizError("单次最多下单 30 个规格")

    # 2) 过敏交叉校验（硬拦截）+ 库存扣减（锁行 + 当前读）
    order_items: list[GoodsOrderItem] = []
    total_cents = 0
    count = 0
    for sku_id, quantity, pet_id in raw_items:
        sku = await _load_sku(db, sku_id, lock=False)
        product = (await db.execute(select(Product).where(Product.id == sku.product_id))).scalars().first()
        if product is None or product.status != "on":
            raise BizError(f"「{product.name if product else '商品'}」已下架")
        if pet_id or payload.pet_id:
            pet = await _load_pet(db, pet_id or payload.pet_id)
            conflicts = safety_conflicts(pet, product)
            if conflicts:
                raise BizError(
                    f"「{product.name}」不适合 {pet.name}：" + "；".join(conflicts) +
                    "。请更换其它商品后再下单"
                )
        await _deduct_stock(db, sku_id, quantity)
        subtotal = sku.price_cents * quantity
        total_cents += subtotal
        count += quantity
        order_items.append(GoodsOrderItem(
            sku_id=sku.id, product_id=product.id, product_name=product.name,
            spec_name=sku.spec_name, image=product.main_image, price_cents=sku.price_cents,
            quantity=quantity, subtotal_cents=subtotal,
        ))

    delivery_fee = 0
    if payload.pickup_method == PickupMethod.DELIVERY.value:
        delivery_fee = await setting_service.get_int(db, "goods_delivery_fee") * 100
        if not (payload.address or "").strip():
            raise BizError("选择门店配送时必须填写收货地址")

    order = GoodsOrder(
        order_no=gen_order_no(prefix="GD"),
        user_id=user.id,
        status=GoodsOrderStatus.PENDING.value,
        pay_status=GoodsPayStatus.UNPAID.value,
        item_count=count,
        total_cents=total_cents + delivery_fee,
        delivery_fee_cents=delivery_fee,
        pickup_method=payload.pickup_method,
        address=payload.address,
        remark=payload.remark,
        pickup_code=gen_pickup_code(),
        idempotent_key=payload.idempotent_key,
        pet_id=payload.pet_id,
    )
    db.add(order)
    await db.flush()
    for item in order_items:
        item.order_id = order.id
        db.add(item)

    # 清空购物车（仅当用购物车下单）
    for cart in cart_items:
        await db.delete(cart)

    await message_service.create_message(
        db, user_id=user.id, title=f"用品订单已提交：{order.order_no}",
        content=(f"共 {count} 件，应付 ¥{order.total_cents / 100:.2f}，"
                 f"{PICKUP_METHOD_LABEL.get(order.pickup_method, order.pickup_method)}。核销码 {order.pickup_code}。"),
        msg_type=MessageType.GOODS_CREATED.value, biz_id=order.id,
    )
    await write_log(db, module="goods", action="create", user_id=user.id, biz_id=order.id,
                    after={"order_no": order.order_no, "total_cents": order.total_cents}, request=request,
                    detail=f"件数={count} 过敏校验=通过")
    await db.commit()
    await db.refresh(order)
    logger.info("goods_order_created",
                extra={"extra_fields": {"order_no": order.order_no, "total_cents": order.total_cents}})
    return order


# ---------------------------------------------------------------- 查询
async def list_orders(
    db: AsyncSession, user: User, *, status: str | None = None, page: int = 1, size: int = 10
) -> tuple[list[tuple[GoodsOrder, User | None]], int]:
    """用品订单分页：宠主只看自己的，店员/店长看全店。"""
    cond = []
    if user.role == UserRole.CUSTOMER.value:
        cond.append(GoodsOrder.user_id == user.id)
    if status:
        cond.append(GoodsOrder.status == status)
    total = int(await db.scalar(select(func.count()).select_from(GoodsOrder).where(*cond)) or 0)
    rows = (await db.execute(
        select(GoodsOrder, User).join(User, User.id == GoodsOrder.user_id)
        .where(*cond).order_by(GoodsOrder.id.desc())
        .offset((page - 1) * size).limit(size)
    )).all()
    return [(r[0], r[1]) for r in rows], total


async def get_order(db: AsyncSession, order_id: int, user: User) -> dict:
    """按 ID 取单并校验归属（宠主不能看他人订单）。"""
    order = (await db.execute(select(GoodsOrder).where(GoodsOrder.id == order_id))).scalars().first()
    if order is None:
        raise NotFoundError("订单不存在")
    if user.role == UserRole.CUSTOMER.value and order.user_id != user.id:
        raise PermissionError_("无权查看他人订单")
    items = (await db.execute(
        select(GoodsOrderItem).where(GoodsOrderItem.order_id == order.id)
    )).scalars().all()
    owner = (await db.execute(select(User).where(User.id == order.user_id))).scalars().first()
    return await order_to_out(order, items, owner)


async def order_to_out(order: GoodsOrder, items: list[GoodsOrderItem], owner: User | None = None) -> dict:
    """订单序列化：明细 + 金额（元）+ 状态/支付中文标签 + 核销码。"""
    from app.utils.crypto import decrypt_text, mask_phone

    return {
        "id": order.id, "order_no": order.order_no, "user_id": order.user_id,
        "owner_name": owner.real_name if owner else None,
        "owner_phone": mask_phone(decrypt_text(owner.phone_encrypted)) if owner else None,
        "status": order.status, "status_label": GOODS_STATUS_LABEL.get(order.status, order.status),
        "pay_status": order.pay_status, "pay_status_label": GOODS_PAY_LABEL.get(order.pay_status, order.pay_status),
        "item_count": order.item_count, "total_amount": order.total_cents / 100,
        "delivery_fee": order.delivery_fee_cents / 100,
        "pickup_method": order.pickup_method,
        "pickup_method_label": PICKUP_METHOD_LABEL.get(order.pickup_method, order.pickup_method),
        "address": order.address, "remark": order.remark,
        "pickup_code": order.pickup_code,
        "cancel_reason": order.cancel_reason,
        "confirmed_at": order.confirmed_at, "completed_at": order.completed_at,
        "created_at": order.created_at,
        "items": [
            {"id": i.id, "sku_id": i.sku_id, "product_id": i.product_id,
             "product_name": i.product_name, "spec_name": i.spec_name, "image": i.image,
             "price": i.price_cents / 100, "quantity": i.quantity, "subtotal": i.subtotal_cents / 100}
            for i in items
        ],
    }


# ---------------------------------------------------------------- 状态流转
async def change_status(
    db: AsyncSession, order: GoodsOrder, target: str, operator: User,
    reason: str | None = None, pay_status: str | None = None, request: Request | None = None,
) -> GoodsOrder:
    """状态流转：走状态机表校验；取消/缺货取消时自动回补库存（stock_released 防重复回补）。"""
    if target not in GOODS_STATUS_LABEL:
        raise BizError(f"未知的订单状态：{target}")
    if target not in GOODS_TRANSITIONS.get(order.status, set()):
        raise StateMachineError(
            f"订单当前状态「{GOODS_STATUS_LABEL.get(order.status)}」不允许变更为「{GOODS_STATUS_LABEL[target]}」"
        )
    if target in GOODS_REASON_REQUIRED_STATUS and not (reason or "").strip():
        raise BizError(f"变更为「{GOODS_STATUS_LABEL[target]}」必须填写原因")

    before = {"status": order.status, "pay_status": order.pay_status}
    order.status = target
    if target == GoodsOrderStatus.CONFIRMED.value:
        order.confirmed_at = now()
    elif target == GoodsOrderStatus.COMPLETED.value:
        order.completed_at = now()
    if target in (GoodsOrderStatus.CANCELLED.value, GoodsOrderStatus.STOCKOUT.value):
        order.cancel_reason = reason
        # 取消 / 缺货：回补库存（用标记防重复回补）
        if not order.stock_released:
            items = (await db.execute(
                select(GoodsOrderItem).where(GoodsOrderItem.order_id == order.id)
            )).scalars().all()
            for item in items:
                await _restore_stock(db, item.sku_id, item.quantity)
            order.stock_released = 1
        if target == GoodsOrderStatus.STOCKOUT.value and pay_status is None:
            order.pay_status = GoodsPayStatus.REFUNDED_OFFLINE.value
    if pay_status:
        if pay_status not in {p.value for p in GoodsPayStatus}:
            raise BizError("支付状态不合法")
        order.pay_status = pay_status

    await message_service.create_message(
        db, user_id=order.user_id, title=f"用品订单状态更新：{GOODS_STATUS_LABEL[target]}",
        content=(f"订单 {order.order_no} 已变更为「{GOODS_STATUS_LABEL[target]}」。"
                 + (f"原因：{reason}" if reason else "")
                 + (f"　核销码：{order.pickup_code}" if target == GoodsOrderStatus.READY.value else "")),
        msg_type=MessageType.GOODS_STATUS.value, biz_id=order.id,
    )
    await write_log(db, module="goods", action=f"status_{target}", user_id=operator.id,
                    staff_id=operator.id if operator.role != UserRole.CUSTOMER.value else None,
                    biz_id=order.id, before=before,
                    after={"status": order.status, "pay_status": order.pay_status},
                    request=request, detail=reason)
    await db.commit()
    await db.refresh(order)
    return order


async def verify_pickup(
    db: AsyncSession, pickup_code: str, operator: User, pay_status: str = "paid_offline",
    request: Request | None = None,
) -> GoodsOrder:
    """核销取货：按核销码找到订单 → completed（库存已在下单时占用，此处不重复扣减）。"""
    order = (await db.execute(
        select(GoodsOrder).where(GoodsOrder.pickup_code == pickup_code)
    )).scalars().first()
    if order is None:
        raise NotFoundError("核销码无效")
    if order.status == GoodsOrderStatus.COMPLETED.value:
        raise BizError("该订单已核销，无需重复操作")
    if order.status not in (GoodsOrderStatus.CONFIRMED.value, GoodsOrderStatus.READY.value):
        raise StateMachineError(
            f"订单当前状态「{GOODS_STATUS_LABEL.get(order.status)}」不可核销，请先确认备货"
        )

    order.status = GoodsOrderStatus.COMPLETED.value
    order.completed_at = now()
    order.pay_status = pay_status if pay_status in {p.value for p in GoodsPayStatus} else \
        GoodsPayStatus.PAID_OFFLINE.value

    # 累计销量（门店自营口径）
    items = (await db.execute(
        select(GoodsOrderItem).where(GoodsOrderItem.order_id == order.id)
    )).scalars().all()
    for item in items:
        product = (await db.execute(select(Product).where(Product.id == item.product_id))).scalars().first()
        if product is not None:
            product.sales_count += item.quantity

    await message_service.create_message(
        db, user_id=order.user_id, title=f"用品已取货：{order.order_no}",
        content=f"共 {order.item_count} 件，实收 ¥{order.total_cents / 100:.2f}。感谢光临 🐾",
        msg_type=MessageType.GOODS_STATUS.value, biz_id=order.id,
    )
    await write_log(db, module="goods", action="verify_pickup", user_id=operator.id,
                    staff_id=operator.id, biz_id=order.id,
                    after={"status": order.status, "pay_status": order.pay_status},
                    request=request, detail=f"核销码={pickup_code}")
    await db.commit()
    await db.refresh(order)
    return order


# ---------------------------------------------------------------- 库存与看板
async def stock_overview(db: AsyncSession, *, only_low: bool = False) -> list[dict]:
    """库存总览，可只看低库存（低于预警阈值）。"""
    rows = (await db.execute(
        select(ProductSku, Product).join(Product, Product.id == ProductSku.product_id)
        .order_by(ProductSku.stock.asc(), Product.id)
    )).all()
    items = []
    for sku, product in rows:
        low = sku.stock <= sku.warn_threshold
        if only_low and not low:
            continue
        items.append({
            "sku_id": sku.id, "product_id": product.id, "product_name": product.name,
            "spec_name": sku.spec_name, "stock": sku.stock,
            "warn_threshold": sku.warn_threshold, "low_stock": low,
            "price": sku.price_cents / 100, "barcode": sku.barcode,
            "status": product.status,
        })
    return items


async def restock(db: AsyncSession, sku_id: int, stock: int, operator: User, remark: str | None = None,
                  request: Request | None = None) -> dict:
    """盘点：把某个 SKU 的库存直接改成实盘值，并记录盘点前后差异。"""
    sku = await _load_sku(db, sku_id, lock=True)
    before = sku.stock
    sku.stock = stock
    await write_log(db, module="goods", action="restock", user_id=operator.id, biz_id=sku.id,
                    before={"stock": before}, after={"stock": stock}, request=request, detail=remark)
    await db.commit()
    return {"sku_id": sku.id, "before": before, "after": stock}


async def dashboard(db: AsyncSession, start: date, end: date) -> dict:
    """用品看板：销售额、客单价、连带率、品类结构、热销榜、低库存与缺货取消率。"""
    orders = (await db.execute(
        select(GoodsOrder).where(
            GoodsOrder.created_at >= datetime.combine(start, datetime.min.time()),
            GoodsOrder.created_at <= datetime.combine(end, datetime.max.time()),
        )
    )).scalars().all()

    valid = [o for o in orders if o.status == GoodsOrderStatus.COMPLETED.value]
    revenue = sum(o.total_cents for o in valid) / 100
    avg_price = round(revenue / len(valid), 2) if valid else 0
    avg_items = round(sum(o.item_count for o in valid) / len(valid), 1) if valid else 0

    item_rows = (await db.execute(
        select(GoodsOrderItem, Product.category)
        .join(GoodsOrder, GoodsOrder.id == GoodsOrderItem.order_id)
        .join(Product, Product.id == GoodsOrderItem.product_id)
        .where(GoodsOrder.status == GoodsOrderStatus.COMPLETED.value)
    )).all()

    top: dict[str, dict] = {}
    category: dict[str, float] = {}
    for item, cat in item_rows:
        node = top.setdefault(item.product_name, {"name": item.product_name, "qty": 0, "revenue": 0.0})
        node["qty"] += item.quantity
        node["revenue"] = round(node["revenue"] + item.subtotal_cents / 100, 2)
        category[cat] = round(category.get(cat, 0) + item.subtotal_cents / 100, 2)

    lows = await stock_overview(db, only_low=True)
    return {
        "range_start": str(start), "range_end": str(end),
        "orders": len(orders),
        "completed": len(valid),
        "cancelled": len([o for o in orders if o.status == GoodsOrderStatus.CANCELLED.value]),
        "stockout": len([o for o in orders if o.status == GoodsOrderStatus.STOCKOUT.value]),
        "revenue": round(revenue, 2),
        "avg_price": avg_price,
        "avg_items": avg_items,
        "top_products": sorted(top.values(), key=lambda x: -x["qty"])[:10],
        "category_stat": [
            {"category": k, "label": PRODUCT_CATEGORY_LABEL.get(k, k), "revenue": v}
            for k, v in category.items()
        ],
        "low_stock_count": len(lows),
        "low_stock": lows[:10],
        "cancel_rate": round(
            (len([o for o in orders if o.status == GoodsOrderStatus.CANCELLED.value])
             + len([o for o in orders if o.status == GoodsOrderStatus.STOCKOUT.value]))
            / len(orders) * 100, 1
        ) if orders else 0.0,
    }


# ---------------------------------------------------------------- 种子商品
SEED_PRODUCTS: list[dict] = [
    {
        "name": "低敏无香洗护套装", "brand": "PawCare", "category": "clean", "species": "all",
        "stage": "all", "size": "all", "selling_points": "无香精,无色素,低敏配方",
        "promo_tags": "门店推荐", "allergy_tags": "", "taboo_tags": "", "sort_no": 1,
        "detail": "无香精无色素，适合敏感肌与过敏体质毛孩子；配合门店洗护使用效果更佳。",
        "skus": [
            {"spec_name": "500ml", "price_cents": 6800, "weight_g": 500, "stock": 30},
            {"spec_name": "1L 家庭装", "price_cents": 11800, "weight_g": 1000, "stock": 12},
        ],
    },
    {
        "name": "燕麦舒缓浴液", "brand": "PetSoft", "category": "clean", "species": "all",
        "stage": "all", "size": "all", "selling_points": "燕麦提取,舒缓止痒",
        "allergy_tags": "燕麦", "taboo_tags": "皮肤破损慎用", "sort_no": 2,
        "detail": "含燕麦提取物，适合干燥瘙痒皮肤；**对燕麦过敏的毛孩子请勿使用**。",
        "skus": [{"spec_name": "400ml", "price_cents": 5800, "weight_g": 400, "stock": 20}],
    },
    {
        "name": "鸡肉味磨牙棒", "brand": "ChewJoy", "category": "snack", "species": "dog",
        "stage": "adult", "size": "small", "selling_points": "洁齿,低脂",
        "allergy_tags": "鸡肉", "taboo_tags": "幼年不宜", "sort_no": 3,
        "detail": "低温烘焙鸡肉磨牙棒，帮助清洁牙垢；3 月龄以下幼犬不建议。",
        "skus": [{"spec_name": "200g", "price_cents": 3200, "weight_g": 200, "stock": 40}],
    },
    {
        "name": "成猫全价主粮（三文鱼）", "brand": "MeowFit", "category": "basic_food", "species": "cat",
        "stage": "adult", "size": "all", "selling_points": "高蛋白,护毛",
        "allergy_tags": "鱼肉", "taboo_tags": "", "sort_no": 4,
        "detail": "三文鱼配方成猫粮，粗蛋白 ≥36%，适口性好。",
        "skus": [
            {"spec_name": "1.5kg", "price_cents": 12800, "weight_g": 1500, "stock": 18},
            {"spec_name": "5kg", "price_cents": 35800, "weight_g": 5000, "stock": 6},
        ],
    },
    {
        "name": "互动漏食球", "brand": "PlayPet", "category": "toy", "species": "all",
        "stage": "all", "size": "all", "selling_points": "耐咬,慢食,益智",
        "allergy_tags": "", "taboo_tags": "", "sort_no": 5,
        "detail": "可填充零食的漏食球，缓解分离焦虑，适合日常互动。",
        "skus": [{"spec_name": "标准号", "price_cents": 4500, "weight_g": 200, "stock": 25}],
    },
    {
        "name": "关节保健软骨素", "brand": "VetPlus", "category": "health", "species": "dog",
        "stage": "senior", "size": "medium", "selling_points": "关节养护,老年适用",
        "allergy_tags": "", "taboo_tags": "肾病禁用", "min_weight": 5, "max_weight": 40, "sort_no": 6,
        "detail": "含葡萄糖胺与软骨素，适合 8 岁以上或大型犬关节养护；肾病宠物请遵医嘱。",
        "skus": [{"spec_name": "60 片", "price_cents": 9800, "weight_g": 180, "stock": 15}],
    },
    # ---------------- V8.6.1 扩充：按主流电商品类与价格带补齐（犬猫双线） ----------------
    # 主粮
    {
        "name": "小型犬成犬粮（鸡肉）", "brand": "Wanpy", "category": "basic_food", "species": "dog",
        "stage": "adult", "size": "small", "selling_points": "高蛋白,小颗粒,适口性好",
        "allergy_tags": "鸡肉", "taboo_tags": "", "min_weight": 2, "max_weight": 12, "sort_no": 11,
        "detail": "小型犬成犬配方，粗蛋白 ≥28%，颗粒直径 8mm，适合泰迪、比熊、博美等。",
        "skus": [
            {"spec_name": "2kg", "price_cents": 8900, "weight_g": 2000, "stock": 24},
            {"spec_name": "10kg", "price_cents": 34900, "weight_g": 10000, "stock": 8},
        ],
    },
    {
        "name": "中大型犬成犬粮（牛肉）", "brand": "Myfoodie", "category": "basic_food", "species": "dog",
        "stage": "adult", "size": "large", "selling_points": "大颗粒,护关节,高能量",
        "allergy_tags": "牛肉", "taboo_tags": "", "min_weight": 15, "max_weight": 60, "sort_no": 12,
        "detail": "中大型犬成犬配方，添加葡萄糖胺，颗粒直径 15mm，减少吞咽过快。",
        "skus": [
            {"spec_name": "10kg", "price_cents": 29900, "weight_g": 10000, "stock": 10},
            {"spec_name": "15kg", "price_cents": 41900, "weight_g": 15000, "stock": 5},
        ],
    },
    {
        "name": "幼犬奶糕粮", "brand": "Bridge", "category": "basic_food", "species": "dog",
        "stage": "puppy", "size": "all", "selling_points": "断奶过渡,易泡软,高钙",
        "allergy_tags": "鸡肉", "taboo_tags": "", "sort_no": 13,
        "detail": "断奶期到 4 月龄幼犬用，温水泡软后喂食；大型犬幼犬需控制钙磷比，不可自行加钙片。",
        "skus": [{"spec_name": "1.5kg", "price_cents": 9900, "weight_g": 1500, "stock": 20}],
    },
    {
        "name": "幼猫粮（鸡肉）", "brand": "MeowFit", "category": "basic_food", "species": "cat",
        "stage": "puppy", "size": "all", "selling_points": "高蛋白,护肠道,易消化",
        "allergy_tags": "鸡肉", "taboo_tags": "", "sort_no": 14,
        "detail": "幼猫与孕哺期母猫用，粗蛋白 ≥38%；断奶后建议每日 4 餐少量多餐。",
        "skus": [
            {"spec_name": "1.5kg", "price_cents": 11900, "weight_g": 1500, "stock": 18},
            {"spec_name": "10kg", "price_cents": 46900, "weight_g": 10000, "stock": 4},
        ],
    },
    {
        "name": "老年犬低脂粮", "brand": "PetPlus", "category": "basic_food", "species": "dog",
        "stage": "senior", "size": "all", "selling_points": "低脂,护肾,易消化",
        "allergy_tags": "鸡肉", "taboo_tags": "肾病需遵医嘱", "sort_no": 15,
        "detail": "8 岁以上老年犬用，脂肪 ≤10%，添加益生元；已确诊肾病的犬只请用处方粮。",
        "skus": [{"spec_name": "2kg", "price_cents": 12900, "weight_g": 2000, "stock": 14}],
    },
    # 零食
    {
        "name": "冻干鸡胸肉粒", "brand": "Lando", "category": "snack", "species": "all",
        "stage": "all", "size": "all", "selling_points": "单一蛋白,高适口,训练奖励",
        "allergy_tags": "鸡肉", "taboo_tags": "", "sort_no": 16,
        "detail": "纯鸡胸冻干，单一蛋白源，适合训练奖励与拌粮；开封后冷藏并两周内用完。",
        "skus": [{"spec_name": "100g", "price_cents": 4500, "weight_g": 100, "stock": 36}],
    },
    {
        "name": "猫条（金枪鱼）", "brand": "MeowFit", "category": "snack", "species": "cat",
        "stage": "all", "size": "all", "selling_points": "补水,湿粮,互动奖励",
        "allergy_tags": "鱼肉", "taboo_tags": "不可替代主粮", "sort_no": 17,
        "detail": "含水量 85%，可作为补水与喂药辅助；每日不超过 2 支，不能代替主粮。",
        "skus": [{"spec_name": "30 支", "price_cents": 3900, "weight_g": 420, "stock": 30}],
    },
    {
        "name": "洁齿骨（中型犬）", "brand": "ChewJoy", "category": "snack", "species": "dog",
        "stage": "adult", "size": "medium", "selling_points": "洁齿,耐咬,低脂",
        "allergy_tags": "", "taboo_tags": "幼年不宜,吞咬过快慎用", "sort_no": 18,
        "detail": "硬度适中的洁齿骨，帮助减少牙垢；6 月龄以下或吞咽过快的犬只不建议。",
        "skus": [{"spec_name": "7 支", "price_cents": 3500, "weight_g": 350, "stock": 28}],
    },
    {
        "name": "风干牛肉粒", "brand": "Wanpy", "category": "snack", "species": "dog",
        "stage": "adult", "size": "all", "selling_points": "风干,高蛋白,耐嚼",
        "allergy_tags": "牛肉", "taboo_tags": "", "sort_no": 19,
        "detail": "低温风干牛肉粒，蛋白 ≥60%；小块投喂，避免整块吞咽。",
        "skus": [{"spec_name": "200g", "price_cents": 4200, "weight_g": 200, "stock": 26}],
    },
    {
        "name": "猫用化毛零食片", "brand": "VetPlus", "category": "snack", "species": "cat",
        "stage": "adult", "size": "all", "selling_points": "化毛,膳食纤维,适口",
        "allergy_tags": "", "taboo_tags": "", "sort_no": 20,
        "detail": "含膳食纤维与植物油，换毛期每日 2~3 片；长期毛球问题优先增加梳毛频率。",
        "skus": [{"spec_name": "60g", "price_cents": 2900, "weight_g": 60, "stock": 32}],
    },
    # 清洁
    {
        "name": "豆腐猫砂", "brand": "N1", "category": "clean", "species": "cat",
        "stage": "all", "size": "all", "selling_points": "可冲厕,低粉尘,结团快",
        "allergy_tags": "", "taboo_tags": "一次最多冲1-2坨", "sort_no": 21,
        "detail": "2mm 豆腐砂，可少量冲厕；梅雨季注意密封防潮，受潮后结团变差。",
        "skus": [{"spec_name": "6L", "price_cents": 3800, "weight_g": 2500, "stock": 40}],
    },
    {
        "name": "膨润土猫砂", "brand": "PetClean", "category": "clean", "species": "cat",
        "stage": "all", "size": "all", "selling_points": "结团硬,性价比,低尘款",
        "allergy_tags": "", "taboo_tags": "不可冲厕,粉尘敏感慎用", "sort_no": 22,
        "detail": "钠基膨润土，结团快、用量省；粉尘较豆腐砂大，建议配封闭砂盆。",
        "skus": [{"spec_name": "10kg", "price_cents": 2600, "weight_g": 10000, "stock": 35}],
    },
    {
        "name": "豆腐膨润土混合砂", "brand": "PetClean", "category": "clean", "species": "cat",
        "stage": "all", "size": "all", "selling_points": "结团除臭均衡,低粉尘",
        "allergy_tags": "", "taboo_tags": "不可大量冲厕", "sort_no": 23,
        "detail": "70% 豆腐砂 + 30% 膨润土，兼顾结团与粉尘控制，适合大多数单猫家庭。",
        "skus": [{"spec_name": "5kg", "price_cents": 3200, "weight_g": 5000, "stock": 38}],
    },
    {
        "name": "宠物环境除臭喷雾", "brand": "PetClean", "category": "clean", "species": "all",
        "stage": "all", "size": "all", "selling_points": "生物酶,无香,可喷织物",
        "allergy_tags": "", "taboo_tags": "避开口鼻眼", "sort_no": 24,
        "detail": "生物酶分解异味，可用于猫砂盆周边与织物；喷后自然晾干，不要直接喷宠物。",
        "skus": [{"spec_name": "450ml", "price_cents": 3900, "weight_g": 450, "stock": 30}],
    },
    {
        "name": "加厚宠物尿垫", "brand": "PetSoft", "category": "clean", "species": "all",
        "stage": "puppy", "size": "all", "selling_points": "加厚,强吸水,带背胶",
        "allergy_tags": "", "taboo_tags": "", "sort_no": 25,
        "detail": "五层加厚，吸水量 ≥800ml，带背胶防移位；幼犬定点训练与寄养场景常用。",
        "skus": [
            {"spec_name": "S 号 100 片", "price_cents": 4500, "weight_g": 1200, "stock": 25},
            {"spec_name": "L 号 50 片", "price_cents": 5900, "weight_g": 1800, "stock": 18},
        ],
    },
    {
        "name": "宠物清洁湿巾", "brand": "PetSoft", "category": "clean", "species": "all",
        "stage": "all", "size": "all", "selling_points": "无酒精,温和,爪部清洁",
        "allergy_tags": "", "taboo_tags": "", "sort_no": 26,
        "detail": "无酒精无香精，适合外出后擦爪与局部清洁；不能替代洗澡。",
        "skus": [{"spec_name": "80 抽", "price_cents": 1900, "weight_g": 300, "stock": 42}],
    },
    # 玩具
    {
        "name": "羽毛逗猫棒", "brand": "PlayPet", "category": "toy", "species": "cat",
        "stage": "all", "size": "all", "selling_points": "互动,可替换头,激发狩猎",
        "allergy_tags": "", "taboo_tags": "线绳需有人看管", "sort_no": 27,
        "detail": "天然羽毛替换头，适合每日 10 分钟互动；玩后收起，避免误食线绳。",
        "skus": [{"spec_name": "标准装", "price_cents": 1900, "weight_g": 80, "stock": 40}],
    },
    {
        "name": "剑麻立式猫抓板", "brand": "PlayPet", "category": "toy", "species": "cat",
        "stage": "all", "size": "all", "selling_points": "剑麻,立式,可全身伸展",
        "allergy_tags": "", "taboo_tags": "", "sort_no": 28,
        "detail": "高度 60cm，剑麻绳缠绕，底座加重防倾倒；放在猫醒来的必经之路比数量更重要。",
        "skus": [{"spec_name": "60cm", "price_cents": 3500, "weight_g": 1500, "stock": 22}],
    },
    {
        "name": "发声毛绒玩具", "brand": "PlayPet", "category": "toy", "species": "dog",
        "stage": "adult", "size": "small", "selling_points": "发声,耐咬,互动",
        "allergy_tags": "", "taboo_tags": "不可无人看管使用", "sort_no": 29,
        "detail": "内置发声器，适合互动取物；毛绒材质不适合拆咬型犬只独自玩耍，防误食填充棉。",
        "skus": [{"spec_name": "小号", "price_cents": 2900, "weight_g": 120, "stock": 30}],
    },
    {
        "name": "棉绳磨牙结", "brand": "ChewJoy", "category": "toy", "species": "dog",
        "stage": "adult", "size": "medium", "selling_points": "拔河,磨牙,清洁牙缝",
        "allergy_tags": "", "taboo_tags": "散线需及时丢弃", "sort_no": 30,
        "detail": "天然棉绳编织，适合拔河互动；出现散线立即更换，避免线头缠绕肠道。",
        "skus": [{"spec_name": "中号", "price_cents": 2500, "weight_g": 200, "stock": 28}],
    },
    {
        "name": "猫咪隧道玩具", "brand": "PlayPet", "category": "toy", "species": "cat",
        "stage": "all", "size": "all", "selling_points": "可折叠,躲藏,释放精力",
        "allergy_tags": "", "taboo_tags": "", "sort_no": 31,
        "detail": "三通折叠隧道，满足躲藏与伏击天性；适合室内活动不足的猫。",
        "skus": [{"spec_name": "三通款", "price_cents": 4500, "weight_g": 600, "stock": 16}],
    },
    # 保健
    {
        "name": "益生菌（犬猫通用）", "brand": "VetPlus", "category": "health", "species": "all",
        "stage": "all", "size": "all", "selling_points": "活菌,换粮期,软便辅助",
        "allergy_tags": "", "taboo_tags": "不解决寄生虫与过敏", "sort_no": 32,
        "detail": "含双歧杆菌与粪肠球菌，适合换粮期、抗生素后与轻度软便；水样便或便血请就医。",
        "skus": [{"spec_name": "30 袋", "price_cents": 7900, "weight_g": 90, "stock": 24}],
    },
    {
        "name": "深海鱼油", "brand": "VetPlus", "category": "health", "species": "all",
        "stage": "all", "size": "all", "selling_points": "Omega-3,护毛护肤,关节辅助",
        "allergy_tags": "鱼肉", "taboo_tags": "凝血异常慎用", "sort_no": 33,
        "detail": "EPA+DHA 含量 ≥30%，建议 20~40mg/kg/天；过量易腹泻，术前两周停用。",
        "skus": [{"spec_name": "100ml", "price_cents": 9900, "weight_g": 120, "stock": 20}],
    },
    {
        "name": "猫咪化毛膏", "brand": "VetPlus", "category": "health", "species": "cat",
        "stage": "adult", "size": "all", "selling_points": "排毛,润滑肠道,换毛期",
        "allergy_tags": "", "taboo_tags": "不可长期依赖", "sort_no": 34,
        "detail": "换毛期短期使用，每次 3~5cm；长期毛球问题优先增加梳毛与膳食纤维。",
        "skus": [{"spec_name": "120g", "price_cents": 4900, "weight_g": 120, "stock": 22}],
    },
    {
        "name": "猫用牛磺酸片", "brand": "VetPlus", "category": "health", "species": "cat",
        "stage": "all", "size": "all", "selling_points": "护心,护眼,必需氨基酸",
        "allergy_tags": "", "taboo_tags": "", "sort_no": 35,
        "detail": "猫必需氨基酸，长期自制猫饭的家庭需额外补充；正规全价粮已添加，无需叠加。",
        "skus": [{"spec_name": "100 片", "price_cents": 5900, "weight_g": 100, "stock": 18}],
    },
    # 日用
    {
        "name": "全封闭猫砂盆", "brand": "PetHome", "category": "daily", "species": "cat",
        "stage": "all", "size": "all", "selling_points": "防带砂,遮味,可拆洗",
        "allergy_tags": "", "taboo_tags": "多猫家庭建议另配开放式", "sort_no": 36,
        "detail": "顶入式全封闭设计，盆长 58cm（适合体长 38cm 以内的猫）；老年猫建议配开放式备用。",
        "skus": [{"spec_name": "大号", "price_cents": 8800, "weight_g": 3200, "stock": 12}],
    },
    {
        "name": "猫咪陶瓷食盆", "brand": "PetHome", "category": "daily", "species": "cat",
        "stage": "all", "size": "all", "selling_points": "陶瓷,防黑下巴,宽口浅盘",
        "allergy_tags": "", "taboo_tags": "", "sort_no": 37,
        "detail": "宽口浅盘设计，减少胡须疲劳；陶瓷表面不易藏菌，比塑料碗更适合易发黑下巴的猫。",
        "skus": [{"spec_name": "单碗", "price_cents": 3900, "weight_g": 450, "stock": 26}],
    },
    {
        "name": "宠物指甲剪", "brand": "PetHome", "category": "daily", "species": "all",
        "stage": "all", "size": "all", "selling_points": "弧形刃,带挡片,防剪过深",
        "allergy_tags": "", "taboo_tags": "", "sort_no": 38,
        "detail": "弧形刃贴合甲型，挡片控制剪切长度；只剪透明部分，避开血线，深色甲需少量多次。",
        "skus": [{"spec_name": "中号", "price_cents": 2900, "weight_g": 120, "stock": 30}],
    },
    {
        "name": "宠物针梳", "brand": "PetHome", "category": "daily", "species": "all",
        "stage": "all", "size": "all", "selling_points": "去浮毛,圆头针,不伤皮肤",
        "allergy_tags": "", "taboo_tags": "皮肤破损处避开", "sort_no": 39,
        "detail": "圆头不锈钢针，适合长毛与双层毛日常梳理；换毛期每日一次可显著减少毛球。",
        "skus": [{"spec_name": "中号", "price_cents": 4500, "weight_g": 180, "stock": 24}],
    },
    {
        "name": "航空箱（中型犬）", "brand": "PetTravel", "category": "daily", "species": "dog",
        "stage": "all", "size": "medium", "selling_points": "硬壳,透气,可托运",
        "allergy_tags": "", "taboo_tags": "需按站立高度选型", "sort_no": 40,
        "detail": "尺寸 68×48×51cm，符合 IATA 基础要求；选购标准是宠物能站立、转身、趴下伸展。",
        "skus": [{"spec_name": "M 号", "price_cents": 15900, "weight_g": 4500, "stock": 8}],
    },
    # 服饰
    {
        "name": "宠物雨衣", "brand": "PetWear", "category": "clothes", "species": "dog",
        "stage": "all", "size": "medium", "selling_points": "防水,反光条,可牵引开口",
        "allergy_tags": "", "taboo_tags": "", "sort_no": 41,
        "detail": "三层防水面料，背部留牵引开口；按胸围选码，留两指松量。",
        "skus": [{"spec_name": "M 号", "price_cents": 6900, "weight_g": 300, "stock": 15}],
    },
    {
        "name": "宠物保暖马甲", "brand": "PetWear", "category": "clothes", "species": "dog",
        "stage": "senior", "size": "small", "selling_points": "抓绒,轻便,老年适用",
        "allergy_tags": "", "taboo_tags": "", "sort_no": 42,
        "detail": "抓绒内里，适合老年犬与短毛小型犬冬季外出；不建议长时间穿着，注意皮肤透气。",
        "skus": [{"spec_name": "S 号", "price_cents": 5900, "weight_g": 180, "stock": 14}],
    },
]


async def upsert_product(
    db: AsyncSession, payload, operator: User, request: Request | None = None
) -> dict:
    """新增 / 更新商品（按商品名判重）。

    单位价（分/kg）在这里统一计算：**业务规则不该散落在路由里** ——
    之前只在路由与种子数据里各算一遍，导致服务层造的数据没有单位价，
    前端比价字段直接为空（V8 抽出）。
    """
    product = (
        await db.execute(select(Product).where(Product.name == payload.name))
    ).scalars().first()
    data = payload.model_dump()
    skus = data.pop("skus", [])

    if product is None:
        product = Product(**data)
        db.add(product)
    else:
        for key, value in data.items():
            setattr(product, key, value)
    await db.flush()

    default_warn = await setting_service.get_int(db, "goods_stock_warn_default")
    for sku in skus:
        exists = (
            await db.execute(
                select(ProductSku).where(
                    ProductSku.product_id == product.id, ProductSku.spec_name == sku["spec_name"]
                )
            )
        ).scalars().first()
        unit = round(sku["price_cents"] / (sku["weight_g"] / 1000)) if sku.get("weight_g") else None
        if exists is None:
            db.add(ProductSku(product_id=product.id, unit_price_cents=unit,
                              **{**sku, "warn_threshold": sku.get("warn_threshold", default_warn)}))
        else:
            for key, value in sku.items():
                setattr(exists, key, value)
            exists.unit_price_cents = unit

    await write_log(db, module="goods", action="upsert_product", user_id=operator.id,
                    biz_id=product.id, after=data, request=request)
    await db.commit()
    logger.info("goods_product_saved",
                extra={"extra_fields": {"product_id": product.id, "skus": len(skus)}})
    return {"id": product.id, "name": product.name}


async def admin_list_products(db: AsyncSession, *, keyword: str | None = None) -> list[dict]:
    """门店侧商品维护列表：**包含已下架**（宠主端只看到 on 的）。"""
    cond = []
    kw = (keyword or "").strip()
    if kw:
        cond.append(or_(Product.name.like(f"%{kw}%"), Product.brand.like(f"%{kw}%")))
    products = (await db.execute(
        select(Product).where(*cond).order_by(Product.status, Product.sort_no, Product.id)
    )).scalars().all()
    skus = (await db.execute(
        select(ProductSku).where(ProductSku.product_id.in_([p.id for p in products]))
    )).scalars().all() if products else []
    by_product: dict[int, list[ProductSku]] = {}
    for sku in skus:
        by_product.setdefault(sku.product_id, []).append(sku)

    return [
        {
            "id": product.id, "name": product.name, "brand": product.brand,
            "category": product.category,
            "category_label": PRODUCT_CATEGORY_LABEL.get(product.category, product.category),
            "species": product.species, "stage": product.stage, "size": product.size,
            "status": product.status, "sort_no": product.sort_no,
            "selling_points": _split(product.selling_points),
            "allergy_tags": _split(product.allergy_tags), "taboo_tags": _split(product.taboo_tags),
            "min_weight": product.min_weight, "max_weight": product.max_weight,
            "detail": product.detail,
            "skus": [sku_to_out(k) for k in sorted(by_product.get(product.id, []), key=lambda x: x.id)],
            "total_stock": sum(k.stock for k in by_product.get(product.id, [])),
        }
        for product in products
    ]


async def delete_product(
    db: AsyncSession, product_id: int, operator: User, request: Request | None = None
) -> dict:
    """删除商品（连同 SKU）；订单明细存的是**价格与名称快照**，历史订单不受影响。

    同步清理购物车里引用这些 SKU 的条目，避免出现「加购了但商品已删」的脏数据。
    """
    product = (await db.execute(select(Product).where(Product.id == product_id))).scalars().first()
    if product is None:
        raise NotFoundError("商品不存在")

    skus = (await db.execute(
        select(ProductSku).where(ProductSku.product_id == product_id)
    )).scalars().all()
    sku_ids = [k.id for k in skus]
    if sku_ids:
        carts = (await db.execute(select(CartItem).where(CartItem.sku_id.in_(sku_ids)))).scalars().all()
        for cart in carts:
            await db.delete(cart)

    name = product.name
    for sku in skus:
        await db.delete(sku)
    await db.delete(product)
    await write_log(db, module="goods", action="delete_product", user_id=operator.id,
                    biz_id=product_id, before={"name": name, "skus": len(sku_ids)}, request=request)
    await db.commit()
    logger.info("goods_product_deleted",
                extra={"extra_fields": {"product_id": product_id, "skus": len(sku_ids)}})
    return {"id": product_id, "name": name, "removed_skus": len(sku_ids)}


async def seed_products(db: AsyncSession) -> int:
    """灌入种子商品（幂等：按商品名判重），并自动算单位价。"""
    exist = {n for n in (await db.execute(select(Product.name))).scalars().all()}
    added = 0
    for item in SEED_PRODUCTS:
        if item["name"] in exist:
            continue
        # 不要 pop：`SEED_PRODUCTS` 是模块级常量，pop 会原地改掉它，
        # 同一进程内第二次调用就会 KeyError（幂等性直接失效）。
        payload = {k: v for k, v in item.items() if k != "skus"}
        product = Product(**payload)
        db.add(product)
        await db.flush()
        for sku in item.get("skus") or []:
            price = sku["price_cents"]
            weight = sku.get("weight_g")
            unit = round(price / (weight / 1000)) if weight else None  # 分/kg
            db.add(ProductSku(product_id=product.id, unit_price_cents=unit, **sku))
        added += 1
    if added:
        await db.flush()
    return added
