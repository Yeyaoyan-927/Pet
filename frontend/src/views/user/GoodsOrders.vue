<!--
  我的用品订单（宠主）：状态筛选、明细与金额、核销码（大写便于口述）、待确认可取消。
  数据来源：GET /goods/orders。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">我的用品订单</h2>
        <p class="pp-page-desc">到店自提时把核销码报给店员即可；暂不支持在线支付，取货时线下付款。</p>
      </div>
      <el-button :icon="Back" @click="router.push('/user/goods')">继续逛逛</el-button>
    </div>

    <section class="pp-filter">
      <el-radio-group v-model="status" @change="load(1)">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="pending">待确认</el-radio-button>
        <el-radio-button value="confirmed">已确认</el-radio-button>
        <el-radio-button value="ready">待取货</el-radio-button>
        <el-radio-button value="completed">已完成</el-radio-button>
      </el-radio-group>
    </section>

    <PawLoading v-if="loading" variant="paw" text="正在加载订单…" />
    <EmptyState
      v-else-if="!orders.length"
      illustration="paw"
      title="还没有用品订单"
      description="给毛孩子囤点口粮和零食吧，门店自提很方便。"
    >
      <el-button type="primary" @click="router.push('/user/goods')">去看看</el-button>
    </EmptyState>

    <div v-else class="order-list">
      <section v-for="order in orders" :key="order.id" class="pp-card order">
        <div class="order__head">
          <div>
            <span class="order__no">{{ order.order_no }}</span>
            <el-tag size="small" :type="tone(order.status)" effect="light">{{ order.status_label }}</el-tag>
            <el-tag size="small" effect="plain">{{ order.pickup_method_label }}</el-tag>
          </div>
          <div class="order__amount">¥{{ order.total_amount.toFixed(2) }}</div>
        </div>

        <div class="order__items">
          <div v-for="item in order.items" :key="item.id" class="order__item">
            <span>{{ item.product_name }} · {{ item.spec_name }}</span>
            <span>×{{ item.quantity }}</span>
            <span>¥{{ item.subtotal.toFixed(2) }}</span>
          </div>
        </div>

        <div class="order__foot">
          <div class="order__code">
            核销码
            <b>{{ order.pickup_code }}</b>
            <span class="order__hint">（到店报给店员）</span>
          </div>
          <div class="order__ops">
            <el-button
              v-if="order.status === 'pending'"
              size="small"
              type="danger"
              plain
              @click="cancel(order)"
            >取消订单</el-button>
          </div>
        </div>
        <p v-if="order.cancel_reason" class="order__reason">{{ order.cancel_reason }}</p>
      </section>

      <div v-if="total > size" class="pp-pager">
        <el-pagination
          layout="prev, pager, next"
          :total="total"
          :page-size="size"
          :current-page="page"
          @current-change="load"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Back } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import { goodsApi } from '@/api/goods'
import type { GoodsOrder } from '@/types'

const router = useRouter()
const orders = ref<GoodsOrder[]>([])
const loading = ref(true)
const status = ref('')
const page = ref(1)
const size = ref(10)
const total = ref(0)

const TONE: Record<string, string> = {
  pending: 'warning',
  confirmed: 'primary',
  ready: 'info',
  completed: 'success',
  cancelled: 'info',
  stockout_cancelled: 'danger'
}

function tone(s: string) {
  return TONE[s] || 'info'
}

async function load(p = page.value) {
  page.value = p
  loading.value = true
  try {
    const res = await goodsApi.orders({ status: status.value || undefined, page: p, size: size.value })
    orders.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function cancel(order: GoodsOrder) {
  const { value } = await ElMessageBox.prompt('取消后库存会释放给其他顾客，确定取消吗？', '取消订单', {
    confirmButtonText: '确定取消',
    cancelButtonText: '再想想',
    inputPlaceholder: '填写取消原因（便于门店改进备货）'
  }).catch(() => ({ value: '' }))
  if (value === '') return
  await goodsApi.cancelOrder(order.id, value || '宠主取消')
  ElMessage.success('订单已取消')
  await load()
}

onMounted(() => load(1))
</script>

<style scoped>
.order-list {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-3);
}

.order__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--pp-space-2);
  flex-wrap: wrap;
}

.order__no {
  margin-right: var(--pp-space-2);
  font-family: var(--pp-font-num);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.order__amount {
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-lg);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-danger);
}

.order__items {
  margin: var(--pp-space-3) 0;
  padding: var(--pp-space-3);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-sunken);
}

.order__item {
  display: flex;
  justify-content: space-between;
  gap: var(--pp-space-3);
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
  padding: 3px 0;
}

.order__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--pp-space-2);
  flex-wrap: wrap;
}

.order__code {
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
}

.order__code b {
  margin: 0 4px;
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-md);
  letter-spacing: 2px;
  color: var(--pp-primary-dark);
}

.order__hint {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.order__reason {
  margin-top: var(--pp-space-2);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}
</style>
