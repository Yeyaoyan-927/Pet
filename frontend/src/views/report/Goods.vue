<!--
  用品看板（店长）：销售额、客单价、连带率、品类结构、热销 TOP、低库存预警。
  数据来源：GET /goods/dashboard。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">用品看板</h2>
        <p class="pp-page-desc">销售额、客单价、连带率、品类结构与滞销库存 —— 判断该补什么、清什么。</p>
      </div>
      <el-date-picker
        v-model="range"
        type="daterange"
        value-format="YYYY-MM-DD"
        range-separator="至"
        start-placeholder="开始"
        end-placeholder="结束"
        @change="load"
      />
    </div>

    <PawLoading v-if="loading" variant="paw" text="正在汇总用品数据…" />

    <template v-else-if="data">
      <el-row :gutter="12">
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="订单数" :value="data.orders" icon="Tickets" tone="primary" /></el-col>
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="销售额" :value="data.revenue" icon="Money" tone="success" suffix="元" /></el-col>
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="客单价" :value="data.avg_price" icon="Wallet" tone="primary" suffix="元" /></el-col>
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="连带率" :value="data.avg_items" icon="ShoppingBag" tone="ai" suffix="件/单" /></el-col>
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="缺货+取消率" :value="data.cancel_rate" icon="WarnTriangleFilled" tone="danger" suffix="%" /></el-col>
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="低库存 SKU" :value="data.low_stock_count" icon="Box" tone="warning" /></el-col>
      </el-row>

      <el-row :gutter="16" class="pp-mt-5">
        <el-col :xs="24" :lg="12">
          <section class="pp-card">
            <div class="pp-card-title">品类销售占比</div>
            <BaseChart v-if="categoryOption" :option="categoryOption" height="280px" />
            <EmptyState v-else illustration="paw" title="区间内暂无销售" :size="72" />
          </section>
        </el-col>
        <el-col :xs="24" :lg="12">
          <section class="pp-card">
            <div class="pp-card-title">热销 TOP10</div>
            <BaseChart v-if="topOption" :option="topOption" height="280px" />
            <EmptyState v-else illustration="cat" title="区间内暂无销售" :size="72" />
          </section>
        </el-col>
      </el-row>

      <section class="pp-card pp-mt-4">
        <div class="pp-card-title">
          低库存预警
          <span class="pp-card-extra">{{ data.low_stock_count }} 个 SKU</span>
        </div>
        <el-table v-if="data.low_stock.length" :data="data.low_stock" stripe>
          <el-table-column prop="product_name" label="商品" min-width="200" />
          <el-table-column prop="spec_name" label="规格" width="160" />
          <el-table-column label="库存" width="120">
            <template #default="{ row }">
              <span class="danger">{{ row.stock }}</span>
              <span class="sub"> / 阈值 {{ row.warn_threshold }}</span>
            </template>
          </el-table-column>
        </el-table>
        <EmptyState v-else illustration="paw" title="库存都很健康" description="没有低于阈值的 SKU。" :size="72" />
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import type { EChartsOption } from 'echarts'
import { computed, onMounted, ref } from 'vue'
import BaseChart from '@/components/BaseChart.vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import StatCard from '@/components/StatCard.vue'
import { goodsApi } from '@/api/goods'
import { toDateStr } from '@/utils/format'
import type { GoodsDashboard } from '@/types'

const data = ref<GoodsDashboard | null>(null)
const loading = ref(true)
const today = new Date()
const range = ref<[string, string]>([toDateStr(new Date(today.getTime() - 180 * 86400000)), toDateStr(today)])

const categoryOption = computed<EChartsOption | null>(() => {
  const stat = data.value?.category_stat || []
  if (!stat.length) return null
  return {
    color: ['#5B9BD5', '#7FB77E', '#F2A65A', '#E07A5F', '#9B8AC4', '#8FB8D8', '#C4BBB0'],
    tooltip: { trigger: 'item', formatter: '{b}: ¥{c}（{d}%）' },
    legend: { bottom: 0, textStyle: { color: '#6B6560' } },
    series: [{
      type: 'pie',
      radius: ['42%', '66%'],
      center: ['50%', '44%'],
      itemStyle: { borderRadius: 8, borderColor: '#fff', borderWidth: 2 },
      label: { color: '#6B6560', fontSize: 12 },
      data: stat.map((i) => ({ name: i.label, value: i.revenue }))
    }]
  }
})

const topOption = computed<EChartsOption | null>(() => {
  const stat = (data.value?.top_products || []).slice(0, 10).reverse()
  if (!stat.length) return null
  return {
    color: ['#7FB77E'],
    tooltip: { trigger: 'axis' },
    grid: { left: 130, right: 30, top: 10, bottom: 20 },
    xAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#9C948B', fontSize: 12 }, splitLine: { lineStyle: { color: '#F5EFE6' } } },
    yAxis: { type: 'category', data: stat.map((i) => i.name), axisLabel: { color: '#9C948B', fontSize: 11 }, axisLine: { lineStyle: { color: '#EDE6DB' } } },
    series: [{ type: 'bar', barWidth: 14, itemStyle: { borderRadius: [0, 8, 8, 0] }, data: stat.map((i) => i.qty) }]
  }
})

async function load() {
  if (!range.value) return
  loading.value = true
  try {
    data.value = await goodsApi.dashboard({ start: range.value[0], end: range.value[1] })
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.danger {
  color: var(--pp-danger);
  font-weight: var(--pp-fw-semibold);
}

.sub {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}
</style>
