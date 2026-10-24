<!--
  经营报表页（店长）：订单与完成率、爽约/取消率、复购率、服务结构、每日趋势、高峰时段、店员负载、流失与高风险。
  数据来源：GET /report/summary。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">经营报表</h2>
        <p class="pp-page-desc">
          统计区间 {{ summary?.range_start || '-' }} ~ {{ summary?.range_end || '-' }}；
          订单量口径为「已确认及以上」，爽约率 = 爽约订单 ÷ 已确认订单。
        </p>
      </div>
      <div class="pp-page-actions">
        <el-date-picker v-model="range" type="daterange" value-format="YYYY-MM-DD"
                        range-separator="至" start-placeholder="开始" end-placeholder="结束"
                        style="width: 260px" @change="load" />
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button v-if="userStore.isManager" type="primary" :icon="Download" @click="router.push('/report/export')">
          导出数据
        </el-button>
      </div>
    </div>

    <PawLoading v-if="loading" variant="paw" text="正在汇总数据…" />

    <template v-else-if="summary">
      <el-row :gutter="16">
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="订单量" :value="summary.total_orders" icon="Tickets" tone="primary" /></el-col>
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="已完成" :value="summary.completed_orders" icon="CircleCheck" tone="success" /></el-col>
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="已取消" :value="summary.cancelled_orders" icon="CircleClose" tone="default" /></el-col>
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="爽约" :value="summary.no_show_orders" icon="WarnTriangleFilled" tone="warning" /></el-col>
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="爽约率" :value="summary.no_show_rate" suffix="%" icon="DataLine" tone="danger" /></el-col>
        <el-col :xs="12" :sm="8" :md="4"><StatCard label="复购率" :value="summary.repurchase_rate" suffix="%" icon="RefreshRight" tone="ai" /></el-col>
      </el-row>

      <el-row :gutter="16" class="pp-mt-5">
        <el-col :xs="24" :lg="12">
          <section class="pp-card">
            <div class="pp-card-title">预约量趋势</div>
            <BaseChart :option="trendOption" height="300px" />
          </section>
        </el-col>
        <el-col :xs="24" :lg="12">
          <section class="pp-card">
            <div class="pp-card-title">
              服务占比
              <span class="pp-card-extra">分母为已完成订单</span>
            </div>
            <BaseChart :option="serviceOption" height="300px" />
          </section>
        </el-col>
      </el-row>

      <el-row :gutter="16" class="pp-mt-4">
        <el-col :xs="24" :lg="12">
          <section class="pp-card">
            <div class="pp-card-title">预约高峰时段</div>
            <BaseChart :option="peakOption" height="300px" />
          </section>
        </el-col>
        <el-col :xs="24" :lg="12">
          <section class="pp-card">
            <div class="pp-card-title">店员工作量（已完成单数）</div>
            <BaseChart :option="staffOption" height="300px" />
          </section>
        </el-col>
      </el-row>

      <el-row :gutter="16" class="pp-mt-4">
        <el-col :xs="24" :lg="10">
          <section class="pp-card">
            <div class="pp-card-title">预约状态分布</div>
            <BaseChart :option="statusOption" height="320px" />
          </section>
        </el-col>
        <el-col :xs="24" :lg="14">
          <section class="pp-card">
            <div class="pp-card-title">
              流失预警名单
              <span class="pp-card-extra">超过 {{ summary.churn_days }} 天无已完成洗护</span>
            </div>
            <EmptyState
              v-if="!summary.churn_pets.length"
              illustration="paw"
              title="暂时没有流失预警"
              description="毛孩子们都按时回店啦 🐾"
              :size="72"
            />
            <el-table v-else :data="summary.churn_pets" max-height="280" size="small">
              <el-table-column prop="pet_name" label="宠物" width="110" />
              <el-table-column label="最后洗护" width="120">
                <template #default="{ row }">{{ row.last_wash_date || '从未洗护' }}</template>
              </el-table-column>
              <el-table-column label="空闲天数" width="110">
                <template #default="{ row }">
                  <el-tag v-if="row.idle_days !== null" size="small" type="warning" effect="light">
                    {{ row.idle_days }} 天
                  </el-tag>
                  <el-tag v-else size="small" type="danger" effect="light">未消费</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </el-col>
      </el-row>
    </template>
  </div>
</template>

<script setup lang="ts">
import type { EChartsOption } from 'echarts'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Download, Refresh } from '@element-plus/icons-vue'
import BaseChart from '@/components/BaseChart.vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import StatCard from '@/components/StatCard.vue'
import { reportApi } from '@/api/report'
import { useUserStore } from '@/stores/user'
import { toDateStr } from '@/utils/format'
import type { ReportSummary } from '@/types'

const router = useRouter()
const userStore = useUserStore()

const loading = ref(true)
const summary = ref<ReportSummary | null>(null)

const end = new Date()
const start = new Date()
start.setDate(end.getDate() - 29)
const range = ref<[string, string]>([toDateStr(start), toDateStr(end)])

/** 与设计令牌保持一致的柔和色板 */
const C = {
  primary: '#5B9BD5',
  light: '#8FBDE8',
  success: '#7FB77E',
  warning: '#F2A65A',
  danger: '#E07A5F',
  ai: '#9B8AC4',
  info: '#8FB8D8',
  neutral: '#A89F94'
}
const PALETTE = [C.primary, C.success, C.warning, C.ai, C.info, C.danger, C.neutral]

const axisStyle = {
  axisLabel: { color: '#9C948B', fontSize: 12 },
  axisLine: { lineStyle: { color: '#EDE6DB' } }
}
const splitStyle = { splitLine: { lineStyle: { color: '#F5EFE6' } } }

const trendOption = computed<EChartsOption>(() => ({
  color: [C.primary],
  tooltip: { trigger: 'axis' },
  grid: { left: 44, right: 20, top: 24, bottom: 30 },
  xAxis: { type: 'category', data: summary.value?.daily_trend.map((i) => i.label) ?? [], ...axisStyle },
  yAxis: { type: 'value', minInterval: 1, ...axisStyle, ...splitStyle },
  series: [
    {
      name: '预约量',
      type: 'line',
      smooth: true,
      symbolSize: 7,
      lineStyle: { width: 2.5 },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(91,155,213,.3)' },
            { offset: 1, color: 'rgba(91,155,213,.02)' }
          ]
        }
      },
      data: summary.value?.daily_trend.map((i) => i.value) ?? []
    }
  ]
}))

const serviceOption = computed<EChartsOption>(() => ({
  color: PALETTE,
  tooltip: { trigger: 'item', formatter: '{b}：{c}（{d}%）' },
  legend: { bottom: 0, textStyle: { color: '#6B6560' }, icon: 'circle' },
  series: [
    {
      name: '服务占比',
      type: 'pie',
      radius: ['44%', '68%'],
      center: ['50%', '44%'],
      itemStyle: { borderColor: '#fff', borderWidth: 3, borderRadius: 6 },
      label: { color: '#6B6560', formatter: '{b}\n{d}%' },
      data: summary.value?.service_ratio.map((i) => ({ name: i.label, value: i.value })) ?? []
    }
  ]
}))

const peakOption = computed<EChartsOption>(() => ({
  color: [C.warning],
  tooltip: { trigger: 'axis' },
  grid: { left: 44, right: 20, top: 24, bottom: 30 },
  xAxis: { type: 'category', data: summary.value?.peak_hours.map((i) => i.label) ?? [], ...axisStyle },
  yAxis: { type: 'value', minInterval: 1, ...axisStyle, ...splitStyle },
  series: [
    {
      name: '提交量',
      type: 'bar',
      barMaxWidth: 22,
      itemStyle: { borderRadius: [6, 6, 0, 0] },
      data: summary.value?.peak_hours.map((i) => i.value) ?? []
    }
  ]
}))

const staffOption = computed<EChartsOption>(() => ({
  color: [C.success],
  tooltip: { trigger: 'axis' },
  grid: { left: 84, right: 32, top: 16, bottom: 24 },
  xAxis: { type: 'value', minInterval: 1, ...axisStyle, ...splitStyle },
  yAxis: {
    type: 'category',
    data: summary.value?.staff_workload.map((i) => i.staff_name) ?? [],
    axisLabel: { color: '#6B6560', fontSize: 12 },
    axisLine: { lineStyle: { color: '#EDE6DB' } }
  },
  series: [
    {
      name: '已完成单数',
      type: 'bar',
      barMaxWidth: 18,
      itemStyle: { borderRadius: [0, 6, 6, 0] },
      label: { show: true, position: 'right', color: '#6B6560' },
      data: summary.value?.staff_workload.map((i) => i.finished_count) ?? []
    }
  ]
}))

const statusOption = computed<EChartsOption>(() => ({
  color: PALETTE,
  tooltip: { trigger: 'item', formatter: '{b}：{c}' },
  legend: { bottom: 0, type: 'scroll', textStyle: { color: '#6B6560' }, icon: 'circle' },
  series: [
    {
      name: '状态分布',
      type: 'pie',
      radius: ['34%', '62%'],
      center: ['50%', '42%'],
      itemStyle: { borderColor: '#fff', borderWidth: 3, borderRadius: 6 },
      label: { color: '#6B6560', formatter: '{b}\n{c}' },
      data: summary.value?.status_distribution.map((i) => ({ name: i.label, value: i.value })) ?? []
    }
  ]
}))

async function load() {
  loading.value = true
  try {
    summary.value = await reportApi.summary({ start: range.value?.[0], end: range.value?.[1] })
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
