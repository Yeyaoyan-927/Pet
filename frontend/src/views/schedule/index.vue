<!--
  门店排期页：周视图展示每天各时段占用与预约，支持按店员筛选。
  数据来源：GET /schedule。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">门店排期</h2>
        <p class="pp-page-desc">
          按日期 × 时段展示门店接待能力与预约占用情况。颜色越浅表示越空闲，越深表示越接近满载。
        </p>
      </div>
      <div class="pp-page-actions">
        <el-button :icon="ArrowLeft" @click="shiftWeek(-7)">上一周</el-button>
        <el-button @click="goToday">本周</el-button>
        <el-button :icon="ArrowRight" @click="shiftWeek(7)">下一周</el-button>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <el-row :gutter="16" class="pp-mb-4">
      <el-col :xs="12" :sm="8">
        <StatCard label="单时段容量" :value="data?.capacity ?? 0" suffix="单/时段" icon="Grid" tone="primary" />
      </el-col>
      <el-col :xs="12" :sm="8">
        <StatCard label="区间总预约" :value="totalBookings" icon="Calendar" tone="success" />
      </el-col>
      <el-col :xs="12" :sm="8">
        <StatCard label="满员时段" :value="fullSlots" icon="WarnTriangleFilled" tone="warning" />
      </el-col>
    </el-row>

    <div class="pp-filter">
      <el-form :inline="true" @submit.prevent>
        <el-form-item label="起始日期">
          <el-date-picker v-model="startDate" type="date" value-format="YYYY-MM-DD"
                          style="width: 170px" @change="load" />
        </el-form-item>
        <el-form-item label="查询天数">
          <el-select v-model="days" style="width: 120px" @change="load">
            <el-option :value="1" label="1 天" />
            <el-option :value="3" label="3 天" />
            <el-option :value="7" label="7 天" />
            <el-option :value="14" label="14 天" />
          </el-select>
        </el-form-item>
        <el-form-item label="图例">
          <div class="legend">
            <span class="legend__item"><i class="lv lv--free" />空闲</span>
            <span class="legend__item"><i class="lv lv--mid" />较忙</span>
            <span class="legend__item"><i class="lv lv--full" />已满</span>
          </div>
        </el-form-item>
      </el-form>
    </div>

    <PawLoading v-if="loading" variant="paw" text="加载排期中…" />

    <section v-else-if="data" class="pp-card schedule-wrap">
      <div class="schedule" :style="{ gridTemplateColumns: `100px repeat(${data.days.length}, minmax(140px, 1fr))` }">
        <!-- 表头 -->
        <div class="schedule__corner">时段</div>
        <div
          v-for="day in data.days"
          :key="day.date"
          class="schedule__day"
          :class="{ 'is-today': day.is_today }"
        >
          <div class="schedule__day-week">{{ day.weekday }}</div>
          <div class="schedule__day-date">{{ day.date.slice(5) }}</div>
          <div class="schedule__day-count">{{ day.total }} 单</div>
        </div>

        <!-- 行 -->
        <template v-for="row in rows" :key="row.slotTime">
          <div class="schedule__time">{{ row.slotTime }}</div>
          <div
            v-for="cell in row.cells"
            :key="`${cell.date}-${row.slotTime}`"
            class="schedule__cell"
            :class="cell.cls"
            @click="openCell(cell.date, row.slotTime)"
          >
            <span v-if="cell.used" class="schedule__cell-count">{{ cell.used }}/{{ cell.capacity }}</span>
            <span v-else class="schedule__cell-empty">空</span>
          </div>
        </template>
      </div>
    </section>

    <!-- 时段详情 -->
    <el-drawer v-model="cellVisible" :title="cellTitle" size="480px">
      <template v-if="cellDay && cellSlot">
        <div class="cell-summary">
          <span>容量 {{ cellSlot.capacity }}</span>
          <span>已占用 {{ cellSlot.used }}</span>
          <span>剩余 {{ cellSlot.remain }}</span>
        </div>

        <EmptyState
          v-if="!cellSlot.appointments.length"
          illustration="paw"
          title="这个时段还没有预约"
          description="可以安排代客预约或作为空闲时段保留。"
          :size="72"
        />

        <div v-else class="cell-list">
          <div v-for="appt in cellSlot.appointments" :key="appt.id" class="cell-item">
            <PetAvatar :species="appt.pet_species || 'dog'" :size="38" />
            <div class="cell-item__main">
              <div class="cell-item__title">
                {{ appt.pet_name }} · {{ appt.service_type_label }}
                <RiskBadge :level="appt.risk_level" />
              </div>
              <div class="cell-item__meta">{{ appt.owner_name }} · {{ appt.order_no }}</div>
            </div>
            <StatusTag :status="appt.status" :label="appt.status_label" />
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowLeft, ArrowRight, Refresh } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import PetAvatar from '@/components/PetAvatar.vue'
import RiskBadge from '@/components/RiskBadge.vue'
import StatCard from '@/components/StatCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { scheduleApi } from '@/api/schedule'
import { addDays, toDateStr } from '@/utils/format'
import type { ScheduleData, ScheduleDay, ScheduleSlot } from '@/types'

const loading = ref(true)
const data = ref<ScheduleData | null>(null)
const startDate = ref(toDateStr(new Date()))
const days = ref(7)

const cellVisible = ref(false)
const cellDay = ref<ScheduleDay | null>(null)
const cellSlot = ref<ScheduleSlot | null>(null)

const slotTimes = computed(() => data.value?.days[0]?.slots.map((s) => s.slot_time) ?? [])

/** 排期网格：行 = 时段，单元格 = 日期 × 时段（预计算占用与样式，避免模板内做多重查找） */
interface ScheduleCell {
  date: string
  cls: string
  used: number
  capacity: number
}

const rows = computed<{ slotTime: string; cells: ScheduleCell[] }[]>(() => {
  const current = data.value
  if (!current) return []
  return slotTimes.value.map((slotTime) => ({
    slotTime,
    cells: current.days.map((day: ScheduleDay) => {
      const slot = day.slots.find((s) => s.slot_time === slotTime)
      const used = slot?.used ?? 0
      const capacity = slot?.capacity ?? current.capacity
      const ratio = used / Math.max(capacity, 1)
      let cls = 'is-free'
      if (ratio >= 1) cls = 'is-full'
      else if (ratio >= 0.6) cls = 'is-mid'
      else if (used > 0) cls = 'is-low'
      return { date: day.date, cls, used, capacity }
    })
  }))
})

const totalBookings = computed(() =>
  data.value ? data.value.days.reduce((sum, d) => sum + d.total, 0) : 0
)

const fullSlots = computed(() =>
  data.value
    ? data.value.days.reduce((sum, d) => sum + d.slots.filter((s) => s.full).length, 0)
    : 0
)

const cellTitle = computed(() =>
  cellDay.value && cellSlot.value
    ? `${cellDay.value.date} ${cellDay.value.weekday} · ${cellSlot.value.slot_time}`
    : '时段详情'
)

function slotOf(day: ScheduleDay, slotTime: string) {
  return day.slots.find((s) => s.slot_time === slotTime)
}

function shiftWeek(delta: number) {
  startDate.value = toDateStr(addDays(new Date(startDate.value), delta))
  load()
}

function goToday() {
  startDate.value = toDateStr(new Date())
  load()
}

function openCell(dateStr: string, slotTime: string) {
  const day = data.value?.days.find((d) => d.date === dateStr)
  if (!day) return
  const slot = slotOf(day, slotTime)
  if (!slot) return
  cellDay.value = day
  cellSlot.value = slot
  cellVisible.value = true
}

async function load() {
  loading.value = true
  try {
    data.value = await scheduleApi.week({ start: startDate.value, days: days.value })
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.legend {
  display: flex;
  gap: var(--pp-space-4);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.legend__item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.lv {
  width: 14px;
  height: 14px;
  border-radius: var(--pp-radius-xs);
  display: inline-block;
}
.lv--free {
  background: #f7fbfe;
  border: 1px solid var(--pp-border-light);
}
.lv--mid {
  background: #dbeafa;
  border: 1px solid #c8e0f5;
}
.lv--full {
  background: #f6d6cc;
  border: 1px solid #eebfb0;
}

.schedule-wrap {
  overflow-x: auto;
}

.schedule {
  display: grid;
  gap: 6px;
  min-width: 720px;
}

.schedule__corner,
.schedule__day {
  background: var(--pp-bg-cream);
  border-radius: var(--pp-radius-sm);
  padding: 8px;
  text-align: center;
}

.schedule__corner {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.schedule__day.is-today {
  background: var(--pp-primary-lighter);
  box-shadow: inset 0 0 0 1.5px var(--pp-primary-light);
}

.schedule__day-week {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.schedule__day-date {
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.schedule__day-count {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-placeholder);
  font-family: var(--pp-font-num);
}

.schedule__time {
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-secondary);
  background: var(--pp-bg-sunken);
  border-radius: var(--pp-radius-sm);
  min-height: 46px;
}

.schedule__cell {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 46px;
  border-radius: var(--pp-radius-sm);
  border: 1px solid var(--pp-border-light);
  cursor: pointer;
  transition: all var(--pp-dur-fast) var(--pp-ease);
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-sm);
}

.schedule__cell:hover {
  transform: translateY(-1px);
  box-shadow: var(--pp-shadow-sm);
}

.schedule__cell.is-free {
  background: #f7fbfe;
}
.schedule__cell.is-low {
  background: var(--pp-primary-lighter);
}
.schedule__cell.is-mid {
  background: #dbeafa;
  color: #2f6fa8;
}
.schedule__cell.is-full {
  background: var(--pp-danger-bg);
  color: #c25a3f;
  font-weight: var(--pp-fw-semibold);
}

.schedule__cell-empty {
  color: var(--pp-text-placeholder);
  font-size: var(--pp-fs-xs);
}

.cell-summary {
  display: flex;
  gap: var(--pp-space-4);
  padding: var(--pp-space-3) var(--pp-space-4);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-sunken);
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
  font-family: var(--pp-font-num);
  margin-bottom: var(--pp-space-4);
}

.cell-list {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-2);
}

.cell-item {
  display: flex;
  align-items: center;
  gap: var(--pp-space-3);
  padding: var(--pp-space-3);
  border-radius: var(--pp-radius-md);
  border: 1px solid var(--pp-border-light);
  background: var(--pp-bg-card);
}

.cell-item__main {
  flex: 1;
  min-width: 0;
}

.cell-item__title {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  font-size: var(--pp-fs-sm);
  font-weight: var(--pp-fw-medium);
  color: var(--pp-text-primary);
}

.cell-item__meta {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  font-family: var(--pp-font-num);
  margin-top: 2px;
}
</style>
