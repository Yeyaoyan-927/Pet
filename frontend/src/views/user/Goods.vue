<!--
  宠物用品（宠主）：分类浏览、按宠物做安全标记、详情与替代建议、购物车与下单。
  数据来源：GET /goods/products、/goods/cart。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">宠物用品</h2>
        <p class="pp-page-desc">
          门店自营好物：选好毛孩子后，含过敏原或禁忌的商品会被自动标记并拦截下单。
        </p>
      </div>
      <div class="head-actions">
        <el-button :icon="ShoppingCart" @click="openCart">
          购物车
          <el-tag v-if="cart.count" size="small" type="danger" effect="light">{{ cart.count }}</el-tag>
        </el-button>
        <el-button :icon="Tickets" @click="router.push('/user/goods/orders')">我的订单</el-button>
      </div>
    </div>

    <section class="pp-filter">
      <el-select v-model="petId" placeholder="为哪只毛孩子挑选" clearable style="width: 200px" @change="load">
        <el-option v-for="p in pets" :key="p.id" :label="`${p.name}（${SPECIES_LABEL[p.species]}）`" :value="p.id" />
      </el-select>
      <el-radio-group v-model="category" @change="load">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button v-for="(label, key) in categories" :key="key" :value="key">{{ label }}</el-radio-button>
      </el-radio-group>
      <el-select v-model="sort" style="width: 140px" @change="load">
        <el-option label="综合排序" value="default" />
        <el-option label="价格从低到高" value="price" />
        <el-option label="销量优先" value="sales" />
      </el-select>
      <el-input v-model="keyword" placeholder="搜商品名 / 品牌" clearable style="width: 200px" @keyup.enter="load" />
      <el-button type="primary" :icon="Search" @click="load">搜索</el-button>
    </section>

    <PawLoading v-if="loading" variant="paw" text="正在上架好物…" />
    <EmptyState
      v-else-if="!products.length"
      illustration="cat"
      title="没有找到合适的商品"
      description="换个分类或关键词试试，也可以清除筛选看全部。"
    />

    <div v-else class="pp-grid">
      <div
        v-for="item in products"
        :key="item.id"
        class="goods-card pp-card pp-card--hover"
        :class="{ 'is-unsafe': item.unsafe }"
        @click="openDetail(item)"
      >
        <div class="goods-card__head">
          <span class="goods-card__name">{{ item.name }}</span>
          <el-tag v-if="item.unsafe" size="small" type="danger" effect="light">不适合当前毛孩子</el-tag>
          <el-tag v-else-if="item.promo_tags.length" size="small" type="warning" effect="light">
            {{ item.promo_tags[0] }}
          </el-tag>
        </div>
        <div class="goods-card__meta">
          {{ item.brand || '门店自营' }} · {{ item.category_label }} · {{ item.stage_label }}适用
        </div>
        <div class="goods-card__tags">
          <el-tag v-for="p in item.selling_points.slice(0, 3)" :key="p" size="small" effect="plain">{{ p }}</el-tag>
          <el-tag v-for="a in item.allergy_tags" :key="'a' + a" size="small" type="danger" effect="plain">
            含{{ a }}
          </el-tag>
        </div>
        <div class="goods-card__footer">
          <div class="goods-card__price">
            ¥{{ (item.min_price || 0).toFixed(2) }}
            <span v-if="(item.max_price || 0) !== (item.min_price || 0)" class="goods-card__range">起</span>
          </div>
          <span class="goods-card__stock">库存 {{ item.total_stock }}</span>
        </div>
        <p v-if="item.unsafe" class="goods-card__warn">{{ item.conflicts[0] }}</p>
      </div>
    </div>

    <!-- 商品详情 -->
    <el-drawer v-model="detailVisible" size="520px" :with-header="false">
      <div v-if="detail" class="detail">
        <h3 class="detail__name">{{ detail.name }}</h3>
        <div class="detail__meta">{{ detail.brand || '门店自营' }} · {{ detail.category_label }}</div>
        <el-alert
          v-if="detail.unsafe"
          type="error"
          :closable="false"
          show-icon
          title="该商品不适合当前毛孩子"
          :description="detail.conflicts.join('；')"
          class="pp-mb-4"
        />
        <p v-if="detail.unsafe && detail.alternative" class="detail__alt">
          同类替代建议：{{ detail.alternative.name }}（¥{{ detail.alternative.price.toFixed(2) }}）
        </p>
        <div class="detail__tags">
          <el-tag v-for="p in detail.selling_points" :key="p" size="small" effect="plain">{{ p }}</el-tag>
          <el-tag v-for="a in detail.allergy_tags" :key="'x' + a" size="small" type="danger" effect="plain">
            含{{ a }}
          </el-tag>
          <el-tag v-for="t in detail.taboo_tags" :key="'t' + t" size="small" type="warning" effect="plain">
            {{ t }}
          </el-tag>
        </div>
        <p class="detail__desc">{{ detail.detail || '门店精选好物，欢迎到店咨询。' }}</p>

        <div class="detail__specs">
          <div
            v-for="sku in detail.skus"
            :key="sku.id"
            class="spec"
            :class="{ 'is-active': pickedSku === sku.id, 'is-out': sku.stock <= 0 }"
            @click="sku.stock > 0 && (pickedSku = sku.id)"
          >
            <span>{{ sku.spec_name }}</span>
            <b>¥{{ sku.price.toFixed(2) }}</b>
            <span v-if="sku.unit_price" class="spec__unit">¥{{ sku.unit_price }}/kg</span>
            <span v-if="sku.stock <= 0" class="spec__out">缺货</span>
            <span v-else-if="sku.low_stock" class="spec__low">仅剩 {{ sku.stock }}</span>
          </div>
        </div>

        <div class="detail__buy">
          <el-input-number v-model="quantity" :min="1" :max="99" />
          <el-button type="primary" :disabled="!pickedSku || detail.unsafe" @click="addToCart">
            加入购物车
          </el-button>
        </div>
        <p class="detail__note">到店自提免配送费；门店配送 {{ 10 }} 元起（以门店配置为准）。</p>
      </div>
    </el-drawer>

    <!-- 购物车 -->
    <el-drawer v-model="cartVisible" title="购物车" size="480px">
      <EmptyState
        v-if="!cart.items.length"
        illustration="paw"
        title="购物车空空的"
        description="挑几件毛孩子用得上的一起带回家吧。"
        :size="72"
      />
      <template v-else>
        <div v-for="line in cart.items" :key="line.id" class="cart-line">
          <div class="cart-line__main">
            <div class="cart-line__name">
              {{ line.product_name }}
              <el-tag v-if="line.unsafe" size="small" type="danger" effect="light">冲突</el-tag>
            </div>
            <div class="cart-line__meta">
              {{ line.spec_name }} · ¥{{ line.price.toFixed(2) }}
              <template v-if="line.pet_name"> · 为 {{ line.pet_name }} 购买</template>
            </div>
            <p v-if="line.unsafe" class="cart-line__warn">{{ line.conflicts[0] }}</p>
          </div>
          <el-input-number
            :model-value="line.quantity"
            :min="0"
            :max="99"
            size="small"
            @change="(v: number | undefined) => changeQty(line.id, v ?? 0)"
          />
          <div class="cart-line__subtotal">¥{{ line.subtotal.toFixed(2) }}</div>
        </div>

        <el-divider />
        <div class="cart-summary">
          <span>共 {{ cart.count }} 件</span>
          <b>¥{{ cart.total.toFixed(2) }}</b>
        </div>

        <el-form label-position="top" class="pp-mt-3">
          <el-form-item label="取货方式">
            <el-radio-group v-model="pickupMethod">
              <el-radio-button value="self">到店自提</el-radio-button>
              <el-radio-button value="delivery">门店配送</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="pickupMethod === 'delivery'" label="收货地址">
            <el-input v-model="address" placeholder="详细到门牌号" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="remark" placeholder="如：到店前先电话联系" />
          </el-form-item>
        </el-form>
        <el-button type="primary" size="large" style="width: 100%" :loading="submitting" @click="submitOrder">
          提交订单
        </el-button>
        <p class="detail__note">暂不支持在线支付，到店取货时线下付款。</p>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search, ShoppingCart, Tickets } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import { goodsApi } from '@/api/goods'
import { petApi } from '@/api/pet'
import { SPECIES_LABEL } from '@/utils/dict'
import type { CartLine, GoodsProduct, Pet } from '@/types'

// ---- 页面结构（阅读顺序）----
// 1) 状态：products/pets/categories（商品与档案）、cart（购物车抽屉）、selectedPet（过敏校验上下文）
// 2) computed：按当前宠物把商品分成「可用 / 不适合」两档，前端只做展示，判定以后端 unsafe 为准
// 3) 数据加载：loadProducts 带 pet_id → 后端返回 unsafe/conflicts；loadCart 拉购物车
// 4) 关键操作：openDetail（详情与替代建议）、addCart（只警告）、checkout（后端硬拦截过敏商品）
// 5) 生命周期：onMounted 先并行拉宠物与商品，选中宠物后再刷新商品标记

const router = useRouter()
const products = ref<GoodsProduct[]>([])
const pets = ref<Pet[]>([])
const categories = ref<Record<string, string>>({})
const loading = ref(true)
const petId = ref<number | undefined>()
const category = ref('')
const keyword = ref('')
const sort = ref('default')

const detailVisible = ref(false)
const detail = ref<GoodsProduct | null>(null)
const pickedSku = ref(0)
const quantity = ref(1)

const cartVisible = ref(false)
const cart = reactive<{ items: CartLine[]; total: number; count: number }>({ items: [], total: 0, count: 0 })
const pickupMethod = ref('self')
const address = ref('')
const remark = ref('')
const submitting = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await goodsApi.products({
      category: category.value || undefined,
      keyword: keyword.value || undefined,
      pet_id: petId.value,
      sort: sort.value
    })
    products.value = res.items
    categories.value = res.categories
  } finally {
    loading.value = false
  }
}

async function openDetail(item: GoodsProduct) {
  const data = await goodsApi.product(item.id, petId.value)
  detail.value = data
  pickedSku.value = data.skus.find((s) => s.stock > 0)?.id ?? 0
  quantity.value = 1
  detailVisible.value = true
}

async function addToCart() {
  if (!pickedSku.value) return
  const res = await goodsApi.addCart({
    sku_id: pickedSku.value,
    quantity: quantity.value,
    pet_id: petId.value ?? null
  })
  ElMessage.success(res.warnings.length ? `已加入，但请注意：${res.warnings[0]}` : '已加入购物车')
  detailVisible.value = false
  await loadCart()
}

async function loadCart() {
  const data = await goodsApi.cart()
  cart.items = data.items
  cart.total = data.total
  cart.count = data.count
}

async function openCart() {
  await loadCart()
  cartVisible.value = true
}

async function changeQty(id: number, quantity: number) {
  await goodsApi.updateCart(id, quantity)
  await loadCart()
}

async function submitOrder() {
  submitting.value = true
  try {
    const order = await goodsApi.createOrder({
      pickup_method: pickupMethod.value,
      address: pickupMethod.value === 'delivery' ? address.value : undefined,
      remark: remark.value || undefined,
      pet_id: petId.value ?? null,
      idempotent_key: `goods-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    })
    ElMessage.success(`下单成功，核销码 ${order.pickup_code}`)
    cartVisible.value = false
    await loadCart()
    router.push('/user/goods/orders')
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  pets.value = await petApi.list()
  await load()
  await loadCart()
})
</script>

<style scoped>
.head-actions {
  display: flex;
  gap: var(--pp-space-2);
}

.goods-card {
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.goods-card.is-unsafe {
  border-color: rgba(224, 122, 95, 0.35);
}

.goods-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--pp-space-2);
}

.goods-card__name {
  font-size: var(--pp-fs-md);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.goods-card__meta {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.goods-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-height: 22px;
}

.goods-card__footer {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-top: var(--pp-space-2);
}

.goods-card__price {
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-lg);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-danger);
}

.goods-card__range {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.goods-card__stock {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.goods-card__warn {
  font-size: var(--pp-fs-xs);
  color: var(--pp-danger);
}

.detail__name {
  font-size: var(--pp-fs-xl);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.detail__meta {
  margin: 4px 0 var(--pp-space-4);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.detail__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: var(--pp-space-3);
}

.detail__desc {
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
  line-height: 1.8;
}

.detail__alt {
  margin-bottom: var(--pp-space-3);
  padding: var(--pp-space-2) var(--pp-space-3);
  border-radius: var(--pp-radius-sm);
  background: var(--pp-success-bg);
  color: var(--pp-success);
  font-size: var(--pp-fs-sm);
}

.detail__specs {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-2);
  margin: var(--pp-space-4) 0;
}

.spec {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  padding: var(--pp-space-3);
  border: 1px solid var(--pp-border-light);
  border-radius: var(--pp-radius-md);
  cursor: pointer;
  transition: all var(--pp-dur-fast) var(--pp-ease);
}

.spec.is-active {
  border-color: var(--pp-primary);
  background: var(--pp-primary-lighter);
}

.spec.is-out {
  opacity: 0.55;
  cursor: not-allowed;
}

.spec b {
  font-family: var(--pp-font-num);
  color: var(--pp-danger);
}

.spec__unit {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.spec__out {
  margin-left: auto;
  font-size: var(--pp-fs-xs);
  color: var(--pp-danger);
}

.spec__low {
  margin-left: auto;
  font-size: var(--pp-fs-xs);
  color: var(--pp-warning);
}

.detail__buy {
  display: flex;
  gap: var(--pp-space-2);
}

.detail__note {
  margin-top: var(--pp-space-3);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-regular);
  line-height: 1.7;
}

.cart-line {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  padding: var(--pp-space-3) 0;
  border-bottom: 1px solid var(--pp-border-light);
}

.cart-line__main {
  flex: 1;
  min-width: 0;
}

.cart-line__name {
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-medium);
  color: var(--pp-text-primary);
}

.cart-line__meta {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.cart-line__warn {
  font-size: var(--pp-fs-xs);
  color: var(--pp-danger);
}

.cart-line__subtotal {
  width: 80px;
  text-align: right;
  font-family: var(--pp-font-num);
  color: var(--pp-text-primary);
}

.cart-summary {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  color: var(--pp-text-regular);
}

.cart-summary b {
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-xl);
  color: var(--pp-danger);
}
</style>
