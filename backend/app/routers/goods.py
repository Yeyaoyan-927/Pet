"""宠物用品接口（V7.2）。

权限：商品浏览/购物车/下单/我的订单 → 登录用户；确认/备货/核销/库存 → 店员与店长；
商品维护与经营看板 → 店长。
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import GOODS_STATUS_LABEL, PRODUCT_CATEGORY_LABEL, UserRole
from app.database import get_db
from app.deps.auth import get_current_user, get_manager_user, get_staff_user
from app.models import GoodsOrder, Product, ProductSku, User
from app.schemas.common import ok
from app.schemas.goods import (
    CartAddIn,
    CartUpdateIn,
    GoodsOrderCreateIn,
    GoodsStatusIn,
    PickupVerifyIn,
    ProductIn,
    StockUpdateIn,
)
from app.services import goods_service
from app.utils.exceptions import BizError, NotFoundError, PermissionError_

router = APIRouter(prefix="/goods", tags=["宠物用品"])


# ---------------------------------------------------------------- 商品
@router.get("/products", summary="商品列表（可按宠物过滤并标注安全冲突）")
async def list_products(
    category: str | None = Query(None),
    keyword: str | None = Query(None),
    species: str | None = Query(None),
    pet_id: int | None = Query(None, description="传宠物 ID 则返回该宠物的安全校验结果"),
    sort: str = Query("default", description="default / price / sales"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """商品列表（可按宠物过滤并标注安全冲突）。"""
    items = await goods_service.list_products(
        db, category=category, keyword=keyword, species=species, pet_id=pet_id, sort=sort
    )
    return ok({"items": items, "total": len(items), "categories": PRODUCT_CATEGORY_LABEL})


@router.get("/products/{product_id}", summary="商品详情（含安全提示与替代建议）")
async def product_detail(
    product_id: int,
    pet_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """商品详情（含安全提示与替代建议）。"""
    return ok(await goods_service.get_product(db, product_id, pet_id=pet_id))


@router.get("/admin/products", summary="商品维护列表（含已下架，店员 / 店长）")
async def admin_products(
    keyword: str | None = Query(None),
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """商品维护列表（含已下架，店员 / 店长）。"""
    items = await goods_service.admin_list_products(db, keyword=keyword)
    return ok({"items": items, "total": len(items), "categories": PRODUCT_CATEGORY_LABEL})


@router.delete("/products/{product_id}", summary="删除商品（店员 / 店长，含 SKU 与购物车清理）")
async def delete_product(
    product_id: int,
    request: Request,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """删除商品（店员 / 店长，含 SKU 与购物车清理）。"""
    return ok(await goods_service.delete_product(db, product_id, staff, request), "商品已删除")


@router.post("/products", summary="新增 / 更新商品（店员 / 店长）")
async def upsert_product(
    payload: ProductIn,
    request: Request,
    manager: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """新增 / 更新商品（店员 / 店长）。"""
    result = await goods_service.upsert_product(db, payload, manager, request)
    return ok(result, "商品已保存")


# ---------------------------------------------------------------- 购物车
@router.get("/cart", summary="购物车")
async def get_cart(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """购物车。"""
    return ok(await goods_service.list_cart(db, user))


@router.post("/cart", summary="加入购物车（含过敏校验提示）")
async def add_cart(
    payload: CartAddIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """加入购物车（含过敏校验提示）。"""
    res = await goods_service.add_to_cart(db, user, payload)
    msg = "已加入购物车"
    if res["warnings"]:
        msg = "已加入购物车，但请注意：" + "；".join(res["warnings"])
    return ok(res, msg)


@router.patch("/cart/{cart_id}", summary="修改购物车数量（0 表示删除）")
async def update_cart(
    cart_id: int,
    payload: CartUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """修改购物车数量（0 表示删除）。"""
    return ok(await goods_service.update_cart(db, user, cart_id, payload.quantity), "已更新")


@router.delete("/cart/{cart_id}", summary="删除购物车条目")
async def remove_cart(
    cart_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除购物车条目。"""
    return ok(await goods_service.remove_cart_item(db, user, cart_id), "已删除")


@router.post("/cart/clear", summary="清空购物车")
async def clear_cart(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """清空购物车。"""
    return ok(await goods_service.clear_cart(db, user), "购物车已清空")


# ---------------------------------------------------------------- 订单
@router.post("/orders", summary="提交用品订单（过敏硬拦截 + 库存锁定）")
async def create_order(
    payload: GoodsOrderCreateIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提交用品订单（过敏硬拦截 + 库存锁定）。"""
    order = await goods_service.create_order(db, user, payload, request)
    data = await goods_service.get_order(db, order.id, user)
    return ok(data, "订单已提交，等待门店确认")


@router.get("/orders", summary="订单列表（宠主仅自己）")
async def list_orders(
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """订单列表（宠主仅自己）。"""
    rows, total = await goods_service.list_orders(db, user, status=status, page=page, size=size)
    items = []
    for order, owner in rows:
        detail = await goods_service.get_order(db, order.id, user)
        items.append(detail)
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.get("/orders/{order_id}", summary="订单详情（含核销码）")
async def order_detail(
    order_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """订单详情（含核销码）。"""
    return ok(await goods_service.get_order(db, order_id, user))


@router.post("/orders/{order_id}/cancel", summary="取消订单（仅待确认）")
async def cancel_order(
    order_id: int,
    payload: GoodsStatusIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消订单（仅待确认）。"""
    order = (await db.execute(select(GoodsOrder).where(GoodsOrder.id == order_id))).scalars().first()
    if order is None:
        raise NotFoundError("订单不存在")
    if user.role == UserRole.CUSTOMER.value and order.user_id != user.id:
        raise PermissionError_("无权操作他人订单")
    updated = await goods_service.change_status(
        db, order, "cancelled", user, reason=payload.reason or "宠主取消", request=request
    )
    return ok({"id": updated.id, "status": updated.status}, "订单已取消，库存已释放")


@router.post("/orders/{order_id}/status", summary="订单状态流转（店员 / 店长）")
async def change_status(
    order_id: int,
    payload: GoodsStatusIn,
    request: Request,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """订单状态流转（店员 / 店长）。"""
    order = (await db.execute(select(GoodsOrder).where(GoodsOrder.id == order_id))).scalars().first()
    if order is None:
        raise NotFoundError("订单不存在")
    updated = await goods_service.change_status(
        db, order, payload.target_status, staff,
        reason=payload.reason, pay_status=payload.pay_status, request=request,
    )
    return ok({
        "id": updated.id, "status": updated.status,
        "status_label": GOODS_STATUS_LABEL.get(updated.status, updated.status),
        "pickup_code": updated.pickup_code,
    }, "状态已更新")


@router.post("/pickup/verify", summary="核销取货（店员 / 店长，按核销码）")
async def verify_pickup(
    payload: PickupVerifyIn,
    request: Request,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """核销取货（店员 / 店长，按核销码）。"""
    order = await goods_service.verify_pickup(
        db, payload.pickup_code.strip(), staff, payload.pay_status, request
    )
    return ok(
        {"id": order.id, "order_no": order.order_no, "total_amount": order.total_cents / 100},
        "核销成功，已记录销售",
    )


# ---------------------------------------------------------------- 库存与看板
@router.get("/stock", summary="库存总览（低库存高亮）")
async def stock(
    only_low: bool = Query(False),
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """库存总览（低库存高亮）。"""
    items = await goods_service.stock_overview(db, only_low=only_low)
    return ok({"items": items, "low_count": len([i for i in items if i["low_stock"]])})


@router.patch("/skus/{sku_id}/stock", summary="库存盘点（店员 / 店长）")
async def update_stock(
    sku_id: int,
    payload: StockUpdateIn,
    request: Request,
    staff: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """库存盘点（店员 / 店长）。"""
    return ok(await goods_service.restock(db, sku_id, payload.stock, staff, payload.remark, request), "库存已更新")


@router.get("/dashboard", summary="用品经营看板（仅店长）")
async def dashboard(
    start: date = Query(...),
    end: date = Query(...),
    manager: User = Depends(get_manager_user),
    db: AsyncSession = Depends(get_db),
):
    """用品经营看板（仅店长）。"""
    return ok(await goods_service.dashboard(db, start, end))
