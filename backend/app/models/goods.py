"""宠物用品（V7.2）：商品 / SKU / 购物车 / 订单 / 订单明细。

两个关键设计：
1. **安全标签**（`allergy_tags` / `taboo_tags`）与宠物档案交叉校验 —— 这是本项目独有的差异点，
   第三方电商抄不走：你店里有「豆豆对燕麦过敏」，加购含燕麦的浴液时直接拦截并给替代建议。
2. **金额用「分」整数**；**库存扣减用「锁 SKU 行 + 当前读」**（沿用 V6 结论，防超卖）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Product(Base, TimestampMixin):
    """SPU。一个商品多个 SKU（规格），安全标签挂在 SPU 上（成分维度）。"""

    __tablename__ = "product"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, comment="商品名")
    brand: Mapped[str | None] = mapped_column(String(60), comment="品牌")
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment="basic_food 主粮 / snack 零食 / toy 玩具 / clean 清洁 / clothes 服饰 / health 保健 / daily 日用",
    )
    species: Mapped[str] = mapped_column(String(10), nullable=False, default="all", comment="dog / cat / all")
    stage: Mapped[str] = mapped_column(String(10), nullable=False, default="all", comment="puppy / adult / senior / all")
    size: Mapped[str] = mapped_column(String(10), nullable=False, default="all", comment="small / medium / large / all")
    main_image: Mapped[str | None] = mapped_column(String(255), comment="主图地址")
    detail: Mapped[str | None] = mapped_column(Text, comment="详情（富文本/纯文本）")
    selling_points: Mapped[str | None] = mapped_column(String(255), comment="卖点标签，逗号分隔")
    promo_tags: Mapped[str | None] = mapped_column(String(120), comment="促销标签，逗号分隔")

    # ⭐ 安全标签：与宠物档案 allergy / skin_disease 做交叉校验
    allergy_tags: Mapped[str | None] = mapped_column(
        String(255), comment="过敏原标签，逗号分隔（如：燕麦,鸡肉,香精）"
    )
    taboo_tags: Mapped[str | None] = mapped_column(
        String(255), comment="禁忌标签，逗号分隔（如：幼犬不宜,肾病禁用,怀孕期慎用）"
    )
    min_weight: Mapped[int | None] = mapped_column(Integer, comment="适用体重下限（kg）")
    max_weight: Mapped[int | None] = mapped_column(Integer, comment="适用体重上限（kg）")

    status: Mapped[str] = mapped_column(String(10), nullable=False, default="on", index=True, comment="on / off")
    sort_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="排序权重（越小越靠前）")
    sales_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="累计销量（门店自营口径）")


class ProductSku(Base, TimestampMixin):
    """SKU：规格 + 售价 + 库存。库存扣减必须锁这一行。"""

    __tablename__ = "product_sku"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="SPU ID")
    spec_name: Mapped[str] = mapped_column(String(80), nullable=False, comment="规格名，如 2kg / 鸡肉味")
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, comment="售价（分）")
    weight_g: Mapped[int | None] = mapped_column(Integer, comment="规格重量（克），用于自动算单位价")
    unit_price_cents: Mapped[int | None] = mapped_column(Integer, comment="单位价（分/kg），比价用")
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="库存（件）")
    warn_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=5, comment="库存预警阈值")
    barcode: Mapped[str | None] = mapped_column(String(64), comment="SKU 条码（扫码核销用）")
    enabled: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="1 上架")


class CartItem(Base, TimestampMixin):
    """购物车条目。`pet_id` 用于过敏交叉校验与后续补货提醒。"""

    __tablename__ = "cart_item"
    __table_args__ = (Index("idx_cart_user_sku_pet", "user_id", "sku_id", "pet_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="宠主 ID")
    sku_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="SKU ID")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="数量")
    pet_id: Mapped[int | None] = mapped_column(BigInteger, comment="关联宠物（用于过敏校验）")


class GoodsOrder(Base, TimestampMixin):
    """用品订单。**暂不接支付**：`pay_status` 预留，取货时店员标记线下已收款，接支付时不用返工。"""

    __tablename__ = "goods_order"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, comment="用品单号")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="宠主 ID")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True, comment="订单状态")
    pay_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unpaid", comment="unpaid / paid_offline / refunded_offline"
    )

    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="商品件数（连带率用）")
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="应付总额（分）")
    delivery_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="配送费（分）")

    pickup_method: Mapped[str] = mapped_column(String(16), nullable=False, default="self", comment="self / delivery")
    address: Mapped[str | None] = mapped_column(String(255), comment="配送地址")
    remark: Mapped[str | None] = mapped_column(String(255), comment="备注")

    pickup_code: Mapped[str] = mapped_column(
        String(12), nullable=False, index=True, comment="核销码（8 位大写字母+数字，店员输入/扫码）"
    )
    idempotent_key: Mapped[str | None] = mapped_column(
        String(64), unique=True, comment="幂等键（与核销码分离：前者防重复提交，后者给店员核销）"
    )
    pet_id: Mapped[int | None] = mapped_column(BigInteger, comment="下单时关联宠物（过敏校验留痕）")

    stock_released: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, comment="库存是否已回补：1 是（防重复回补）"
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(255), comment="取消 / 缺货原因")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, comment="确认时间")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, comment="完成（核销）时间")


class GoodsOrderItem(Base, TimestampMixin):
    """订单明细：**价格与规格快照**，商品改价/改名不影响历史订单。"""

    __tablename__ = "goods_order_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="订单 ID")
    sku_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="SKU ID")
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="SPU ID")
    product_name: Mapped[str] = mapped_column(String(120), nullable=False, comment="商品名快照")
    spec_name: Mapped[str] = mapped_column(String(80), nullable=False, comment="规格快照")
    image: Mapped[str | None] = mapped_column(String(255), comment="主图快照")
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, comment="成交单价（分）")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment="数量")
    subtotal_cents: Mapped[int] = mapped_column(Integer, nullable=False, comment="小计（分）")
