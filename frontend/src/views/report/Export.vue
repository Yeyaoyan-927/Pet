<!--
  数据导出页（店长）：选区间与类型导出 CSV/Excel，并给出字段说明与二次确认。
  数据来源：GET /report/export（文件流）。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">数据导出</h2>
        <p class="pp-page-desc">
          选择导出类型与统计区间，点击导出即可下载 CSV（UTF-8 BOM，Excel 直接打开不乱码）。每次导出都会记录审计日志。
        </p>
      </div>
      <div class="pp-page-actions">
        <el-button :icon="TrendCharts" @click="router.push('/report/summary')">查看报表</el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="15">
        <section class="pp-card">
          <div class="pp-card-title">1. 选择导出类型</div>
          <div class="export-grid">
            <button
              v-for="t in EXPORT_TYPES"
              :key="t.value"
              type="button"
              class="export-option"
              :class="{ 'is-active': type === t.value }"
              @click="type = t.value"
            >
              <div class="export-option__icon"><el-icon :size="20"><component :is="iconOf(t.value)" /></el-icon></div>
              <div class="export-option__title">{{ t.label }}</div>
              <div class="export-option__desc">{{ t.desc }}</div>
            </button>
          </div>
        </section>

        <section class="pp-card">
          <div class="pp-card-title">2. 选择统计区间</div>
          <el-date-picker
            v-model="range"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            style="width: 320px"
          />
          <div class="quick-ranges">
            <el-button
              v-for="q in quickRanges"
              :key="q.label"
              size="small"
              :type="activeQuick === q.label ? 'primary' : 'default'"
              @click="applyQuick(q)"
            >
              {{ q.label }}
            </el-button>
          </div>
          <el-alert
            type="info"
            :closable="false"
            show-icon
            class="pp-mt-4"
            title="提示"
            :description="rangeHint"
          />
        </section>

        <section class="pp-card export-action">
          <div class="export-action__info">
            <div class="export-action__title">即将导出：{{ currentType?.label }}</div>
            <div class="export-action__desc">
              区间 {{ range?.[0] || '-' }} ~ {{ range?.[1] || '-' }} · {{ currentType?.desc }}
            </div>
          </div>
          <el-button type="primary" :icon="Download" :loading="exporting" @click="doExport">
            导出 CSV
          </el-button>
        </section>
      </el-col>

      <el-col :xs="24" :lg="9">
        <section class="pp-card">
          <div class="pp-card-title">
            本次导出预览
            <span class="pp-card-extra">
              <el-button link type="primary" @click="loadPreview">刷新</el-button>
            </span>
          </div>

          <PawLoading v-if="previewLoading" variant="bubble" text="正在统计区间数据…" />

          <template v-else-if="summary">
            <div class="preview-list">
              <div class="preview-row"><span>订单量（已确认及以上）</span><b>{{ summary.total_orders }}</b></div>
              <div class="preview-row"><span>已完成</span><b>{{ summary.completed_orders }}</b></div>
              <div class="preview-row"><span>已取消</span><b>{{ summary.cancelled_orders }}</b></div>
              <div class="preview-row"><span>爽约</span><b>{{ summary.no_show_orders }}</b></div>
              <div class="preview-row"><span>高风险报告</span><b>{{ summary.risk_high_count }}</b></div>
              <div class="preview-row"><span>流失预警宠物</span><b>{{ summary.churn_pets.length }}</b></div>
            </div>
            <el-alert
              type="success"
              :closable="false"
              show-icon
              class="pp-mt-4"
              title="区间数据已就绪，可以导出"
            />
          </template>

          <EmptyState v-else illustration="paw" title="暂无区间数据" :size="72" />
        </section>

        <section class="pp-card">
          <div class="pp-card-title">导出说明</div>
          <ul class="note-list">
            <li>CSV 已带 UTF-8 BOM，用 Excel 双击打开不会乱码。</li>
            <li>「客户档案」导出的应急电话为原始号码，请勿外传。</li>
            <li>导出动作会写入审计日志（模块 report，动作 export_csv）。</li>
            <li>预约明细最多导出区间内 5000 条，超量请缩小时间范围。</li>
          </ul>
        </section>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Download, TrendCharts } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import { reportApi } from '@/api/report'
import { EXPORT_TYPES } from '@/utils/dict'
import { addDays, downloadBlob, toDateStr, parseFilename } from '@/utils/format'
import type { ReportSummary } from '@/types'

const router = useRouter()

const type = ref('summary')
const exporting = ref(false)
const previewLoading = ref(false)
const summary = ref<ReportSummary | null>(null)

const end = new Date()
const start = new Date()
start.setDate(end.getDate() - 29)
const range = ref<[string, string]>([toDateStr(start), toDateStr(end)])
const activeQuick = ref('近 30 天')

const quickRanges = [
  { label: '近 7 天', days: 6 },
  { label: '近 30 天', days: 29 },
  { label: '近 90 天', days: 89 },
  { label: '近 365 天', days: 364 }
]

const currentType = computed(() => EXPORT_TYPES.find((t) => t.value === type.value))

const rangeHint = computed(() => {
  if (type.value === 'pets') return '客户档案导出不受时间区间影响，始终导出全部有效档案。'
  if (type.value === 'appointments') return '预约明细按「到店日期」落在这个区间内筛选。'
  if (type.value === 'wash') return '洗护记录按「到店日期」落在这个区间内筛选。'
  return '经营概览统计的订单量口径为「已确认及以上」状态的预约。'
})

function iconOf(value: string) {
  return { summary: 'DataAnalysis', appointments: 'Tickets', wash: 'Sunny', pets: 'Star' }[value] || 'Document'
}

function applyQuick(q: { label: string; days: number }) {
  activeQuick.value = q.label
  const e = new Date()
  range.value = [toDateStr(addDays(e, -q.days)), toDateStr(e)]
}

async function loadPreview() {
  previewLoading.value = true
  try {
    summary.value = await reportApi.summary({ start: range.value?.[0], end: range.value?.[1] })
  } catch {
    summary.value = null
  } finally {
    previewLoading.value = false
  }
}

async function doExport() {
  if (!range.value?.[0] || !range.value?.[1]) {
    ElMessage.warning('请选择统计区间')
    return
  }
  exporting.value = true
  try {
    const res = await reportApi.exportCsv({
      type: type.value,
      start: range.value[0],
      end: range.value[1]
    })
    const filename = parseFilename(
      res.headers['content-disposition'],
      `${currentType.value?.label}_${range.value[0]}_${range.value[1]}.csv`
    )
    downloadBlob(res.data, filename)
    ElMessage.success(`已导出：${filename}`)
  } finally {
    exporting.value = false
  }
}

watch(type, () => {
  if (type.value === 'pets') activeQuick.value = ''
})

onMounted(loadPreview)
</script>

<style scoped>
.export-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--pp-space-3);
}

.export-option {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-2);
  padding: var(--pp-space-4);
  border-radius: var(--pp-radius-lg);
  border: 1.5px solid var(--pp-border-light);
  background: var(--pp-bg-card);
  cursor: pointer;
  transition: all var(--pp-dur-fast) var(--pp-ease);
  font-family: inherit;
  text-align: left;
}

.export-option:hover {
  transform: translateY(-2px);
  box-shadow: var(--pp-shadow-sm);
  border-color: var(--pp-primary-light);
}

.export-option.is-active {
  border-color: var(--pp-primary);
  background: var(--pp-primary-lighter);
}

.export-option__icon {
  width: 40px;
  height: 40px;
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-cream);
  color: var(--pp-primary-dark);
  display: flex;
  align-items: center;
  justify-content: center;
}

.export-option.is-active .export-option__icon {
  background: #fff;
  color: var(--pp-primary);
}

.export-option__title {
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.export-option__desc {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  line-height: 1.6;
}

.quick-ranges {
  display: flex;
  gap: var(--pp-space-2);
  margin-top: var(--pp-space-3);
  flex-wrap: wrap;
}

.export-action {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--pp-space-4);
  background: linear-gradient(135deg, #fffdfa 0%, #eef5fc 100%);
}

.export-action__title {
  font-size: var(--pp-fs-md);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.export-action__desc {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  margin-top: 4px;
}

.preview-list {
  display: flex;
  flex-direction: column;
}

.preview-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--pp-space-3) 0;
  border-bottom: 1px dashed var(--pp-border-light);
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
}

.preview-row:last-child {
  border-bottom: none;
}

.preview-row b {
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-md);
  color: var(--pp-primary-dark);
}

.note-list {
  margin: 0;
  padding-left: 18px;
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
  line-height: 2;
}
</style>
