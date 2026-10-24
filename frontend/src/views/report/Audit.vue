<!--
  审计日志页（店长）：按模块与时间筛选写操作记录，展示操作人、前后快照与 IP。
  数据来源：GET /report/audit。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">审计日志</h2>
        <p class="pp-page-desc">
          所有写操作都会留痕（模块、动作、操作人、业务 ID、来源 IP）。日志层已对手机号等敏感字段自动脱敏。
        </p>
      </div>
      <div class="pp-page-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="pp-filter">
      <el-form :inline="true" @submit.prevent>
        <el-form-item label="业务模块">
          <el-select v-model="module" placeholder="全部模块" clearable style="width: 170px" @change="reload">
            <el-option v-for="m in MODULES" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="reload">查询</el-button>
        </el-form-item>
      </el-form>
    </div>

    <section class="pp-card">
      <PawLoading v-if="loading" variant="paw" text="加载日志中…" />
      <EmptyState v-else-if="!list.length" illustration="paw" title="暂无日志记录" />

      <div v-else class="pp-scroll-x">
        <el-table :data="list" style="width: 100%">
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="module" label="模块" width="110">
            <template #default="{ row }">
              <el-tag size="small" effect="light">{{ MODULE_LABEL[row.module] || row.module }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="action" label="操作" min-width="180" show-overflow-tooltip />
          <el-table-column label="操作人" width="120">
            <template #default="{ row }">
              <span class="pp-num">
                {{ row.staff_id ? `店员#${row.staff_id}` : row.user_id ? `用户#${row.user_id}` : '系统' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="biz_id" label="业务 ID" width="100">
            <template #default="{ row }">
              <span class="pp-num">{{ row.biz_id ?? '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="ip" label="来源 IP" width="140">
            <template #default="{ row }">
              <span class="pp-num">{{ row.ip || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="结果" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 1 ? 'success' : 'danger'" effect="light">
                {{ row.status === 1 ? '成功' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="detail" label="说明" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.detail || '-' }}</template>
          </el-table-column>
          <el-table-column label="时间" width="170">
            <template #default="{ row }">
              <span class="pp-num">{{ formatDateTime(row.created_at) }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div v-if="total > size" class="pp-pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @size-change="load"
          @current-change="load"
        />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import { reportApi } from '@/api/report'
import { formatDateTime } from '@/utils/format'
import type { AuditLogItem } from '@/types'

const MODULES = ['auth', 'user', 'pet', 'appointment', 'risk', 'wash', 'message', 'setting', 'report', 'agent', 'chat']
const MODULE_LABEL: Record<string, string> = {
  auth: '鉴权',
  user: '用户',
  pet: '宠物档案',
  appointment: '预约',
  risk: '风险判别',
  wash: '洗护记录',
  message: '站内消息',
  setting: '门店配置',
  report: '报表',
  agent: 'AI 助手',
  chat: 'AI 会话'
}

const loading = ref(true)
const list = ref<AuditLogItem[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const module = ref('')

async function load() {
  loading.value = true
  try {
    const res = await reportApi.auditLogs({
      page: page.value,
      size: size.value,
      module: module.value || undefined
    })
    list.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

onMounted(load)
</script>
