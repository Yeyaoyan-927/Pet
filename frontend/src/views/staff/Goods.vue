<!--
  用品工作台（店员/店长）：订单 / 核销 / 库存 / 商品维护四个页签。
  数据来源：GET /goods/orders、/stock、/admin/products。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">用品管理</h2>
        <p class="pp-page-desc">
          确认订单 → 备货 → 核销取货；核销时扣减销量并记录线下收款（暂不支持在线支付）。
        </p>
      </div>
      <el-button :icon="Refresh" @click="loadAll">刷新</el-button>
    </div>

    <el-row :gutter="12">
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="待确认" :value="stat.pending" icon="Clock" tone="warning" /></el-col>
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="已确认" :value="stat.confirmed" icon="CircleCheck" tone="primary" /></el-col>
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="待取货" :value="stat.ready" icon="Van" tone="ai" /></el-col>
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="今日完成" :value="stat.completed" icon="Sunny" tone="success" /></el-col>
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="低库存 SKU" :value="lowCount" icon="WarnTriangleFilled" tone="danger" /></el-col>
      <el-col :xs="12" :sm="8" :md="4"><StatCard label="缺货取消" :value="stat.stockout" icon="CloseBold" tone="default" /></el-col>
    </el-row>

    <section class="pp-card pp-mt-5">
      <el-tabs v-model="tab">
        <el-tab-pane label="订单" name="orders">
          <div class="pp-filter">
            <el-radio-group v-model="status" @change="loadOrders(1)">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button value="pending">待确认</el-radio-button>
              <el-radio-button value="confirmed">已确认</el-radio-button>
              <el-radio-button value="ready">待取货</el-radio-button>
              <el-radio-button value="completed">已完成</el-radio-button>
            </el-radio-group>
          </div>

          <PawLoading v-if="loading" variant="paw" text="正在加载订单…" />
          <EmptyState
            v-else-if="!orders.length"
            illustration="paw"
            title="暂时没有用品订单"
            description="宠主下单后会出现在这里，确认后备货即可。"
          />

          <el-table v-else :data="orders" stripe>
            <el-table-column prop="order_no" label="单号" width="180" />
            <el-table-column label="宠主" width="150">
              <template #default="{ row }">
                <div>{{ row.owner_name }}</div>
                <div class="cell-sub">{{ row.owner_phone }}</div>
              </template>
            </el-table-column>
            <el-table-column label="商品" min-width="220">
              <template #default="{ row }">
                <div v-for="item in row.items" :key="item.id" class="cell-sub">
                  {{ item.product_name }} · {{ item.spec_name }} ×{{ item.quantity }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="取货" width="150">
              <template #default="{ row }">
                <div>{{ row.pickup_method_label }}</div>
                <div class="cell-sub">{{ row.pickup_code }}</div>
              </template>
            </el-table-column>
            <el-table-column label="金额" width="100">
              <template #default="{ row }">¥{{ row.total_amount.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag size="small" :type="tone(row.status)" effect="light">{{ row.status_label }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="260" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="row.status === 'pending'"
                  size="small"
                  type="primary"
                  @click="change(row, 'confirmed')"
                >确认订单</el-button>
                <el-button
                  v-if="row.status === 'confirmed'"
                  size="small"
                  type="primary"
                  @click="change(row, 'ready')"
                >备货完成</el-button>
                <el-button
                  v-if="['confirmed', 'ready'].includes(row.status)"
                  size="small"
                  type="success"
                  @click="verify(row)"
                >核销取货</el-button>
                <el-button
                  v-if="['pending', 'confirmed'].includes(row.status)"
                  size="small"
                  type="danger"
                  plain
                  @click="stockout(row)"
                >缺货取消</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="total > size" class="pp-pager">
            <el-pagination
              layout="prev, pager, next"
              :total="total"
              :page-size="size"
              :current-page="page"
              @current-change="loadOrders"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane label="核销" name="verify">
          <div class="verify">
            <p class="verify__tip">让宠主出示核销码，或直接扫描小票条码；核销后自动记销量与线下收款。</p>
            <div class="verify__row">
              <el-input
                v-model="code"
                placeholder="输入 8 位核销码"
                maxlength="12"
                style="width: 260px"
                @keyup.enter="doVerify"
              />
              <el-button type="primary" :loading="verifying" @click="doVerify">核销</el-button>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane :label="`商品（${products.length}）`" name="products">
          <div class="pp-filter">
            <el-input
              v-model="productKeyword"
              placeholder="搜商品名 / 品牌"
              clearable
              style="width: 220px"
              @keyup.enter="loadProducts"
            />
            <el-button type="primary" :icon="Search" @click="loadProducts">搜索</el-button>
            <el-button type="primary" plain :icon="Plus" @click="openProduct()">新增商品</el-button>
          </div>
          <el-table :data="products" stripe>
            <el-table-column prop="name" label="商品" min-width="200">
              <template #default="{ row }">
                <div>{{ row.name }}</div>
                <div class="cell-sub">{{ row.brand || '门店自营' }} · {{ row.category_label }}</div>
              </template>
            </el-table-column>
            <el-table-column label="安全标签" min-width="180">
              <template #default="{ row }">
                <el-tag v-for="a in row.allergy_tags" :key="'a' + a" size="small" type="danger" effect="plain">
                  含{{ a }}
                </el-tag>
                <el-tag v-for="t in row.taboo_tags" :key="'t' + t" size="small" type="warning" effect="plain">
                  {{ t }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="规格数" width="90">
              <template #default="{ row }">{{ row.skus.length }}</template>
            </el-table-column>
            <el-table-column label="总库存" width="100">
              <template #default="{ row }">{{ row.total_stock }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 'on' ? 'success' : 'info'" effect="light">
                  {{ row.status === 'on' ? '在售' : '已下架' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="primary" plain @click="openProduct(row)">编辑</el-button>
                <el-button size="small" plain @click="toggleProduct(row)">
                  {{ row.status === 'on' ? '下架' : '上架' }}
                </el-button>
                <el-button size="small" type="danger" plain @click="removeProduct(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="`库存（低库存 ${lowCount}）`" name="stock">
          <div class="pp-filter">
            <el-checkbox v-model="onlyLow" @change="loadStock">只看低库存</el-checkbox>
          </div>
          <el-table :data="stock" stripe>
            <el-table-column prop="product_name" label="商品" min-width="200" />
            <el-table-column prop="spec_name" label="规格" width="140" />
            <el-table-column label="售价" width="100">
              <template #default="{ row }">¥{{ row.price.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="库存" width="120">
              <template #default="{ row }">
                <span :class="{ 'is-low': row.low_stock }">{{ row.stock }}</span>
                <span class="cell-sub"> / 阈值 {{ row.warn_threshold }}</span>
              </template>
            </el-table-column>
            <el-table-column label="盘点" width="220">
              <template #default="{ row }">
                <el-input-number v-model="row.newStock" :min="0" :max="99999" size="small" />
                <el-button size="small" type="primary" plain class="pp-ml-2" @click="restock(row)">保存</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </section>

    <!-- 商品新增 / 编辑 -->
    <el-dialog v-model="productVisible" :title="productForm.id ? '编辑商品' : '新增商品'" width="640px">
      <el-form label-position="top">
        <el-row :gutter="12">
          <el-col :xs="24" :sm="12">
            <el-form-item label="商品名"><el-input v-model="productForm.name" maxlength="120" /></el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="品牌"><el-input v-model="productForm.brand" maxlength="60" /></el-form-item>
          </el-col>
          <el-col :xs="12" :sm="8">
            <el-form-item label="分类">
              <el-select v-model="productForm.category" style="width: 100%">
                <el-option v-for="(label, key) in categories" :key="key" :label="label" :value="key" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="8">
            <el-form-item label="适用对象">
              <el-select v-model="productForm.species" style="width: 100%">
                <el-option label="通用" value="all" />
                <el-option label="犬" value="dog" />
                <el-option label="猫" value="cat" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="8">
            <el-form-item label="状态">
              <el-select v-model="productForm.status" style="width: 100%">
                <el-option label="在售" value="on" />
                <el-option label="下架" value="off" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="过敏原标签（逗号分隔）">
              <el-input v-model="productForm.allergy_tags" placeholder="如：燕麦,鸡肉" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="禁忌标签（逗号分隔）">
              <el-input v-model="productForm.taboo_tags" placeholder="如：幼年不宜,肾病禁用" />
            </el-form-item>
          </el-col>
          <el-col :xs="24">
            <el-form-item label="卖点标签（逗号分隔）">
              <el-input v-model="productForm.selling_points" placeholder="如：低敏,无香精" />
            </el-form-item>
          </el-col>
          <el-col :xs="24">
            <el-form-item label="详情">
              <el-input v-model="productForm.detail" type="textarea" :rows="2" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">规格与库存</el-divider>
        <div v-for="(sku, idx) in productForm.skus" :key="idx" class="sku-row">
          <el-input v-model="sku.spec_name" placeholder="规格（如 500ml）" style="width: 150px" />
          <el-input-number v-model="sku.price_yuan" :min="0" :max="99999" :precision="2" :step="1" />
          <span class="cell-sub">元</span>
          <el-input-number v-model="sku.weight_g" :min="0" :max="100000" :step="100" />
          <span class="cell-sub">克</span>
          <el-input-number v-model="sku.stock" :min="0" :max="99999" />
          <span class="cell-sub">件</span>
          <el-button link type="danger" :icon="Delete" @click="productForm.skus.splice(idx, 1)" />
        </div>
        <el-button link type="primary" :icon="Plus" @click="addSku">添加规格</el-button>
      </el-form>
      <template #footer>
        <el-button @click="productVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveProduct">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus, Refresh, Search } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import StatCard from '@/components/StatCard.vue'
import { goodsApi } from '@/api/goods'
import type { GoodsOrder } from '@/types'

// ---- 页面结构（阅读顺序）----
// 1) 状态：orders（订单页签）、stock（库存/低库存）、products（商品维护页签）
// 2) 状态机按钮由后端返回的 status + 前端字典决定，缺货取消强制填原因
// 3) 核销：verify 只需核销码，成功后订单自动完成并记线下收款
// 4) 商品维护：openProduct/saveProduct（含 SKU 行编辑与单位价自动计算）、上下架、删除
// 5) 生命周期：onMounted 一次性拉三个页签的数据，任一页签操作后只刷新自己

interface StockRow {
  sku_id: number
  product_name: string
  spec_name: string
  stock: number
  warn_threshold: number
  low_stock: boolean
  price: number
  newStock?: number
}

const tab = ref('orders')
const status = ref('')
const orders = ref<GoodsOrder[]>([])
const loading = ref(true)
const page = ref(1)
const size = ref(10)
const total = ref(0)

const stock = ref<StockRow[]>([])
const onlyLow = ref(false)

interface ProductRow {
  id: number
  name: string
  brand?: string | null
  category: string
  category_label: string
  species: string
  stage: string
  size: string
  status: string
  sort_no: number
  selling_points: string[]
  allergy_tags: string[]
  taboo_tags: string[]
  detail?: string | null
  skus: { id: number; spec_name: string; price: number; weight_g: number | null; stock: number }[]
  total_stock: number
}

const products = ref<ProductRow[]>([])
const productKeyword = ref('')
const categories = ref<Record<string, string>>({})
const productVisible = ref(false)
const saving = ref(false)
const productForm = reactive({
  id: 0,
  name: '',
  brand: '',
  category: 'clean',
  species: 'all',
  stage: 'all',
  size: 'all',
  status: 'on',
  selling_points: '',
  allergy_tags: '',
  taboo_tags: '',
  detail: '',
  skus: [] as { spec_name: string; price_yuan: number; weight_g: number; stock: number }[]
})
const code = ref('')
const verifying = ref(false)

const TONE: Record<string, string> = {
  pending: 'warning', confirmed: 'primary', ready: 'info',
  completed: 'success', cancelled: 'info', stockout_cancelled: 'danger'
}

const stat = computed(() => {
  const base: Record<string, number> = { pending: 0, confirmed: 0, ready: 0, completed: 0, stockout: 0 }
  for (const o of orders.value) {
    if (o.status in base) base[o.status] += 1
    if (o.status === 'stockout_cancelled') base.stockout += 1
  }
  return base
})
const lowCount = computed(() => stock.value.filter((s) => s.low_stock).length)

function tone(s: string) {
  return TONE[s] || 'info'
}

async function loadOrders(p = page.value) {
  page.value = p
  loading.value = true
  try {
    const res = await goodsApi.orders({ status: status.value || undefined, page: p, size: 100 })
    orders.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function loadProducts() {
  const res = await goodsApi.adminProducts(productKeyword.value || undefined)
  products.value = res.items as unknown as ProductRow[]
  categories.value = res.categories
}

function addSku() {
  productForm.skus.push({ spec_name: '', price_yuan: 0, weight_g: 0, stock: 0 })
}

function openProduct(row?: ProductRow) {
  if (row) {
    productForm.id = row.id
    productForm.name = row.name
    productForm.brand = row.brand || ''
    productForm.category = row.category
    productForm.species = row.species
    productForm.stage = row.stage
    productForm.size = row.size
    productForm.status = row.status
    productForm.selling_points = row.selling_points.join(',')
    productForm.allergy_tags = row.allergy_tags.join(',')
    productForm.taboo_tags = row.taboo_tags.join(',')
    productForm.detail = row.detail || ''
    productForm.skus = row.skus.map((s) => ({
      spec_name: s.spec_name,
      price_yuan: s.price,
      weight_g: s.weight_g || 0,
      stock: s.stock
    }))
  } else {
    productForm.id = 0
    productForm.name = ''
    productForm.brand = ''
    productForm.category = 'clean'
    productForm.species = 'all'
    productForm.stage = 'all'
    productForm.size = 'all'
    productForm.status = 'on'
    productForm.selling_points = ''
    productForm.allergy_tags = ''
    productForm.taboo_tags = ''
    productForm.detail = ''
    productForm.skus = [{ spec_name: '标准装', price_yuan: 0, weight_g: 0, stock: 0 }]
  }
  productVisible.value = true
}

async function saveProduct() {
  if (!productForm.name.trim()) {
    ElMessage.warning('请填写商品名')
    return
  }
  const skus = productForm.skus.filter((s) => s.spec_name.trim())
  if (!skus.length) {
    ElMessage.warning('至少需要一个规格')
    return
  }
  saving.value = true
  try {
    await goodsApi.saveProduct({
      name: productForm.name.trim(),
      brand: productForm.brand || undefined,
      category: productForm.category,
      species: productForm.species,
      stage: productForm.stage,
      size: productForm.size,
      status: productForm.status,
      selling_points: productForm.selling_points || undefined,
      allergy_tags: productForm.allergy_tags || undefined,
      taboo_tags: productForm.taboo_tags || undefined,
      detail: productForm.detail || undefined,
      skus: skus.map((s) => ({
        spec_name: s.spec_name.trim(),
        price_cents: Math.round(s.price_yuan * 100),
        weight_g: s.weight_g || undefined,
        stock: s.stock
      }))
    })
    ElMessage.success('商品已保存')
    productVisible.value = false
    await Promise.all([loadProducts(), loadStock()])
  } finally {
    saving.value = false
  }
}

async function toggleProduct(row: ProductRow) {
  const target = row.status === 'on' ? 'off' : 'on'
  await goodsApi.saveProduct({
    name: row.name,
    brand: row.brand || undefined,
    category: row.category,
    species: row.species,
    stage: row.stage,
    size: row.size,
    status: target,
    selling_points: row.selling_points.join(',') || undefined,
    allergy_tags: row.allergy_tags.join(',') || undefined,
    taboo_tags: row.taboo_tags.join(',') || undefined,
    detail: row.detail || undefined,
    skus: row.skus.map((s) => ({
      spec_name: s.spec_name,
      price_cents: Math.round(s.price * 100),
      weight_g: s.weight_g || undefined,
      stock: s.stock
    }))
  })
  ElMessage.success(target === 'on' ? '已上架' : '已下架')
  await loadProducts()
}

async function removeProduct(row: ProductRow) {
  await ElMessageBox.confirm(
    `删除「${row.name}」会连同 ${row.skus.length} 个规格一起移除（历史订单快照不受影响），确定吗？`,
    '删除商品',
    { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' }
  )
  await goodsApi.deleteProduct(row.id)
  ElMessage.success('商品已删除')
  await Promise.all([loadProducts(), loadStock()])
}

async function loadStock() {
  const res = await goodsApi.stock(onlyLow.value)
  stock.value = res.items.map((i) => ({ ...i, newStock: i.stock }))
}

async function change(row: GoodsOrder, target: string) {
  const res = await goodsApi.changeStatus(row.id, { target_status: target })
  ElMessage.success(`已更新为「${res.status_label}」`)
  await loadAll()
}

async function verify(row: GoodsOrder) {
  await goodsApi.verifyPickup(row.pickup_code)
  ElMessage.success(`已核销 ${row.order_no}`)
  await loadAll()
}

async function stockout(row: GoodsOrder) {
  const { value } = await ElMessageBox.prompt('缺货取消会释放库存并向宠主说明原因', '缺货取消', {
    confirmButtonText: '确认取消',
    cancelButtonText: '返回',
    inputPlaceholder: '如：该规格临时缺货，预计 3 天到货'
  }).catch(() => ({ value: '' }))
  if (!value) return
  await goodsApi.changeStatus(row.id, {
    target_status: 'stockout_cancelled',
    reason: value,
    pay_status: 'refunded_offline'
  })
  ElMessage.success('已按缺货取消并回补库存')
  await loadAll()
}

async function doVerify() {
  if (code.value.trim().length < 4) {
    ElMessage.warning('请输入完整核销码')
    return
  }
  verifying.value = true
  try {
    const res = await goodsApi.verifyPickup(code.value.trim())
    ElMessage.success(`核销成功：${res.order_no}，实收 ¥${res.total_amount.toFixed(2)}`)
    code.value = ''
    await loadAll()
  } finally {
    verifying.value = false
  }
}

async function restock(row: StockRow) {
  await goodsApi.updateStock(row.sku_id, row.newStock ?? row.stock, '门店盘点')
  ElMessage.success('库存已更新')
  await loadStock()
}

async function loadAll() {
  await Promise.all([loadOrders(1), loadStock(), loadProducts()])
}

onMounted(loadAll)
</script>

<style scoped>
.cell-sub {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.is-low {
  color: var(--pp-danger);
  font-weight: var(--pp-fw-semibold);
}

.verify {
  padding: var(--pp-space-4) 0;
}

.verify__tip {
  margin-bottom: var(--pp-space-3);
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
}

.verify__row {
  display: flex;
  gap: var(--pp-space-2);
}

.sku-row {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  margin-bottom: var(--pp-space-2);
  flex-wrap: wrap;
}
</style>
