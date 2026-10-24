<!--
  寄养看板（店长）：订单量、收入、入住率、客单价、房型结构、状态分布、照护异常率。
  数据来源：GET /boarding/dashboard。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">寄养看板</h2>
        <p class="pp-page-desc">
          入住率、客单价、收入结构与照护质量（异常发生率）—— 用于判断房型投入与服务质量。
        </p>
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

    <PawLoading v-if="loading" variant="paw" text="正在汇总寄养数据…" />

    <template v-else-if="data">
      <el-row :gutter="12">
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="寄养订单" :value="data.orders" icon="Tickets" tone="primary" /></el-col>
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="寄养收入" :value="data.revenue" icon="Money" tone="success" suffix="元" /></el-col>
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="平均晚数" :value="data.avg_nights" icon="Calendar" tone="warning" suffix="晚" /></el-col>
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="客单价" :value="data.avg_price" icon="Wallet" tone="primary" suffix="元" /></el-col>
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="当前入住率" :value="data.occupancy_rate" icon="House" tone="ai" suffix="%" /></el-col>
        <el-col :xs="12" :sm="8" :md="4">
          <StatCard label="照护异常率" :value="data.abnormal_rate" icon="WarnTriangleFilled" tone="danger" suffix="%" />
        </el-col>
      </el-row>

      <el-row :gutter="16" class="pp-mt-5">
        <el-col :xs="24" :lg="12">
          <section class="pp-card">
            <div class="pp-card-title">
              房型收入与订单
              <span class="pp-card-extra">共 {{ data.total_rooms }} 间房舍</span>
            </div>
            <BaseChart v-if="typeOption" :option="typeOption" height="280px" />
            <EmptyState v-else illustration="paw" title="区间内暂无寄养订单" :size="72" />
          </section>
        </el-col>

        <el-col :xs="24" :lg="12">
          <section class="pp-card">
            <div class="pp-card-title">订单状态分布</div>
            <BaseChart v-if="statusOption" :option="statusOption" height="280px" />
            <EmptyState v-else illustration="cat" title="区间内暂无寄养订单" :size="72" />
          </section>
        </el-col>
      </el-row>

      <el-row :gutter="16" class="pp-mt-4">
        <el-col :xs="24" :lg="12">
          <section class="pp-card">
            <div class="pp-card-title">房态分布</div>
            <div class="room-status">
              <div v-for="(count, label) in data.room_status_stat" :key="label" class="room-status__item">
                <span>{{ label }}</span>
                <b>{{ count }}</b>
              </div>
            </div>
          </section>
        </el-col>
        <el-col :xs="24" :lg="12">
          <section class="pp-card">
            <div class="pp-card-title">照护质量</div>
            <div class="quality">
              <div class="quality__item">
                <span>照护日报</span>
                <b>{{ data.care_logs }} 条</b>
              </div>
              <div class="quality__item">
                <span>异常记录</span>
                <b :class="{ 'is-danger': data.abnormal_logs > 0 }">{{ data.abnormal_logs }} 条</b>
              </div>
              <div class="quality__item">
                <span>异常发生率</span>
                <b :class="{ 'is-danger': data.abnormal_rate > 10 }">{{ data.abnormal_rate }}%</b>
              </div>
            </div>
            <p class="hint">
              异常记录会即时推送宠主并通知店长；异常率偏高时建议复盘 SOP 执行与房型适配度。
            </p>
          </section>
        </el-col>
      </el-row>
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
import { boardingApi } from '@/api/boarding'
import { toDateStr } from '@/utils/format'
import type { BoardingDashboard } from '@/types'

const data = ref<BoardingDashboard | null>(null)
const loading = ref(true)
const today = new Date()
const range = ref<[string, string]>([toDateStr(new Date(today.getTime() - 180 * 86400000)), toDateStr(today)])

const typeOption = computed<EChartsOption | null>(() => {
  const stat = data.value?.room_type_stat || []
  if (!stat.length) return null
  return {
    color: ['#5B9BD5', '#7FB77E'],
    tooltip: { trigger: 'axis' },
    legend: { data: ['订单数', '收入(元)'], textStyle: { color: '#6B6560' }, top: 0 },
    grid: { left: 48, right: 24, top: 40, bottom: 32 },
    xAxis: {
      type: 'category',
      data: stat.map((i) => i.label),
      axisLabel: { color: '#9C948B', fontSize: 12 },
      axisLine: { lineStyle: { color: '#EDE6DB' } }
    },
    yAxis: [
      { type: 'value', minInterval: 1, axisLabel: { color: '#9C948B', fontSize: 12 }, splitLine: { lineStyle: { color: '#F5EFE6' } } },
      { type: 'value', axisLabel: { color: '#9C948B', fontSize: 12 }, splitLine: { show: false } }
    ],
    series: [
      { name: '订单数', type: 'bar', barWidth: 22, itemStyle: { borderRadius: [8, 8, 0, 0] }, data: stat.map((i) => i.count) },
      { name: '收入(元)', type: 'line', yAxisIndex: 1, smooth: true, symbolSize: 7, data: stat.map((i) => i.revenue) }
    ]
  }
})

const statusOption = computed<EChartsOption | null>(() => {
  const stat = data.value?.status_stat || []
  if (!stat.length) return null
  return {
    color: ['#F2A65A'],
    tooltip: { trigger: 'axis' },
    grid: { left: 48, right: 24, top: 20, bottom: 32 },
    xAxis: {
      type: 'category',
      data: stat.map((i) => i.label),
      axisLabel: { color: '#9C948B', fontSize: 12, interval: 0 },
      axisLine: { lineStyle: { color: '#EDE6DB' } }
    },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#9C948B', fontSize: 12 }, splitLine: { lineStyle: { color: '#F5EFE6' } } },
    series: [{ type: 'bar', barWidth: 22, itemStyle: { borderRadius: [8, 8, 0, 0] }, data: stat.map((i) => i.count) }]
  }
})

async function load() {
  if (!range.value) return
  loading.value = true
  try {
    data.value = await boardingApi.dashboard({ start: range.value[0], end: range.value[1] })
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.room-status {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: var(--pp-space-3);
}

.room-status__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--pp-space-3);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-sunken);
  color: var(--pp-text-regular);
}

.room-status__item b {
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-lg);
  color: var(--pp-text-primary);
}

.quality {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-2);
}

.quality__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--pp-space-3);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-sunken);
  color: var(--pp-text-regular);
}

.quality__item b {
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-lg);
  color: var(--pp-text-primary);
}

.quality__item b.is-danger {
  color: var(--pp-danger);
}

.hint {
  margin-top: var(--pp-space-3);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-regular);
  line-height: 1.7;
}
</style>
