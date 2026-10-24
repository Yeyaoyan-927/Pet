<!--
  我的寄养（宠主）：状态筛选 + 寄养卡片，进详情看照护日报。
  数据来源：GET /boarding/orders。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">宠物寄养</h2>
        <p class="pp-page-desc">
          毛孩子的寄养都在这里：查看状态、每日照护日报、接送任务与费用明细。
        </p>
      </div>
      <el-button type="primary" :icon="Plus" @click="router.push('/user/boarding/create')">新建寄养</el-button>
    </div>

    <section class="pp-filter">
      <el-radio-group v-model="status" @change="load(1)">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button
          v-for="(label, key) in activeStatus"
          :key="key"
          :value="key"
        >{{ label }}</el-radio-button>
      </el-radio-group>
    </section>

    <section class="pp-card">
      <PawLoading v-if="loading" variant="paw" text="正在查看寄养记录…" />
      <EmptyState
        v-else-if="!items.length"
        illustration="dog"
        title="还没有寄养记录"
        description="出门在外也不放心毛孩子？给它订一间安心的小窝吧。"
      >
        <el-button type="primary" @click="router.push('/user/boarding/create')">去预约寄养</el-button>
      </EmptyState>

      <div v-else class="board-list">
        <div
          v-for="item in items"
          :key="item.id"
          class="board-item"
          @click="router.push(`/user/boarding/${item.id}`)"
        >
          <PetAvatar :species="item.pet_species === 'cat' ? 'cat' : 'dog'" :size="44" />
          <div class="board-item__main">
            <div class="board-item__title">
              {{ item.pet_name }} · {{ item.room_type_label }}
              <el-tag size="small" :type="tone(item.status)" effect="light">{{ item.status_label }}</el-tag>
              <el-tag v-if="item.isolate_required" size="small" type="warning" effect="light">需隔离观察</el-tag>
            </div>
            <div class="board-item__meta">
              {{ item.check_in_date }} ~ {{ item.check_out_date }} · {{ item.nights }} 晚 ·
              {{ item.room_no }} · 单号 {{ item.order_no }}
            </div>
          </div>
          <div class="board-item__amount">
            <div class="board-item__price">¥{{ item.total_amount.toFixed(2) }}</div>
            <el-icon><ArrowRight /></el-icon>
          </div>
        </div>
      </div>

      <div v-if="total > size" class="pp-pager">
        <el-pagination
          layout="prev, pager, next"
          :total="total"
          :page-size="size"
          :current-page="page"
          @current-change="load"
        />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Plus } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import PetAvatar from '@/components/PetAvatar.vue'
import { boardingApi } from '@/api/boarding'
import { BOARDING_STATUS_TONE } from '@/utils/dict'
import type { BoardingOrder } from '@/types'

const router = useRouter()
const items = ref<BoardingOrder[]>([])
const loading = ref(true)
const status = ref('')
const page = ref(1)
const size = ref(10)
const total = ref(0)

/** 宠主端只列出对自己有意义的阶段，避免一屏十几个状态按钮 */
const activeStatus = computed(() => ({
  pending: '待确认',
  confirmed: '已确认',
  waiting_checkin: '待入住',
  checked_in: '寄养中',
  waiting_pickup: '待接回',
  completed: '已完成'
}))

function tone(s: string) {
  return BOARDING_STATUS_TONE[s] || 'info'
}

async function load(p = page.value) {
  page.value = p
  loading.value = true
  try {
    const res = await boardingApi.orders({ status: status.value || undefined, page: p, size: size.value })
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

onMounted(() => load(1))
</script>

<style scoped>
.board-list {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-2);
}

.board-item {
  display: flex;
  align-items: center;
  gap: var(--pp-space-3);
  padding: var(--pp-space-4);
  border: 1px solid var(--pp-border-light);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-sunken);
  cursor: pointer;
  transition: all var(--pp-dur-fast) var(--pp-ease);
}

.board-item:hover {
  background: var(--pp-primary-lighter);
  border-color: transparent;
}

.board-item__main {
  flex: 1;
  min-width: 0;
}

.board-item__title {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-medium);
  color: var(--pp-text-primary);
  flex-wrap: wrap;
}

.board-item__meta {
  margin-top: 4px;
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  font-family: var(--pp-font-num);
}

.board-item__amount {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--pp-text-placeholder);
}

.board-item__price {
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-md);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}
</style>
