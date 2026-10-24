<!--
  门店配置页（店长）：按分组展示配置项，带类型校验、范围提示与恢复默认。
  数据来源：GET/PUT /settings。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">门店配置</h2>
        <p class="pp-page-desc">
          门店级业务参数统一在这里维护。超出取值范围会被拒绝保存；配置异常时业务会自动回退默认值，保证门店运转不中断。
        </p>
      </div>
      <div class="pp-page-actions">
        <el-button :icon="RefreshLeft" @click="resetAll">恢复默认配置</el-button>
      </div>
    </div>

    <PawLoading v-if="loading" variant="paw" text="加载配置中…" />

    <template v-else>
      <section v-for="group in groups" :key="group.name" class="pp-card">
        <div class="pp-card-title">{{ group.name }}</div>

        <div class="setting-list">
          <div v-for="item in group.items" :key="item.setting_key" class="setting-item">
            <div class="setting-item__info">
              <div class="setting-item__label">{{ item.setting_desc || item.setting_key }}</div>
              <div class="setting-item__key">{{ item.setting_key }}</div>
            </div>

            <div class="setting-item__control">
              <el-switch
                v-if="item.value_type === 'bool'"
                v-model="item.setting_value"
                active-value="true"
                inactive-value="false"
              />
              <el-input-number
                v-else-if="item.value_type === 'int'"
                v-model="item.setting_value"
                :min="item.min_value ?? undefined"
                :max="item.max_value ?? undefined"
                controls-position="right"
                style="width: 160px"
              />
              <el-input v-else v-model="item.setting_value" maxlength="255" style="width: 220px" />
            </div>

            <div class="setting-item__range">
              <span v-if="item.value_type === 'int'">{{ item.min_value }} ~ {{ item.max_value }}</span>
              <span v-else-if="item.value_type === 'bool'">true / false</span>
              <span v-else>文本</span>
            </div>

            <el-button
              size="small"
              type="primary"
              plain
              :loading="savingKey === item.setting_key"
              @click="save(item)"
            >
              保存
            </el-button>
          </div>
        </div>
      </section>

      <section class="pp-card">
        <div class="pp-card-title">参数影响说明</div>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="cancel_window_hours">宠主自助取消的时间窗口，窗口外的取消需要联系门店</el-descriptions-item>
          <el-descriptions-item label="default_slot_capacity">单个 1 小时时段的最大接待量，满员时段在预约页会置灰</el-descriptions-item>
          <el-descriptions-item label="no_show_threshold">累计爽约次数阈值，达到后进入限制名单</el-descriptions-item>
          <el-descriptions-item label="max_reschedule_times">单笔预约的最大改期次数，超出后需要取消重约</el-descriptions-item>
          <el-descriptions-item label="staff_confirm_timeout_hours">待确认预约的 SLA 时限，超时触发升级提醒</el-descriptions-item>
          <el-descriptions-item label="auto_cancel_on_timeout">SLA 超时后是否自动取消（自动取消不计入爽约）</el-descriptions-item>
          <el-descriptions-item label="churn_days">超过该天数没有洗护记录会进入流失预警名单</el-descriptions-item>
          <el-descriptions-item label="session_retention_days">AI 会话数据留存天数，到期由异步任务清理</el-descriptions-item>
        </el-descriptions>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RefreshLeft } from '@element-plus/icons-vue'
import PawLoading from '@/components/PawLoading.vue'
import { settingApi } from '@/api/setting'
import type { SettingItem } from '@/types'

const loading = ref(true)
const savingKey = ref('')
const list = ref<SettingItem[]>([])

/** 按业务语义分组展示，避免一长条配置堆在一起 */
const GROUP_MAP: Record<string, string[]> = {
  '预约与时段': ['default_slot_capacity', 'cancel_window_hours', 'max_reschedule_times'],
  '履约与提醒': ['staff_confirm_timeout_hours', 'auto_cancel_on_timeout', 'no_show_threshold'],
  '运营与留存': ['churn_days', 'session_retention_days']
}

const groups = computed(() => {
  const used = new Set<string>()
  const result: { name: string; items: SettingItem[] }[] = []
  for (const [name, keys] of Object.entries(GROUP_MAP)) {
    const items = list.value.filter((i) => keys.includes(i.setting_key))
    items.forEach((i) => used.add(i.setting_key))
    if (items.length) result.push({ name, items })
  }
  const others = list.value.filter((i) => !used.has(i.setting_key))
  if (others.length) result.push({ name: '其他', items: others })
  return result
})

async function load() {
  loading.value = true
  try {
    list.value = await settingApi.list()
  } finally {
    loading.value = false
  }
}

async function save(item: SettingItem) {
  const value = String(item.setting_value)
  if (item.value_type === 'int') {
    const num = Number(value)
    if (Number.isNaN(num)) {
      ElMessage.warning('请输入整数')
      return
    }
    if (item.min_value !== null && num < item.min_value) {
      ElMessage.warning(`不能小于 ${item.min_value}`)
      return
    }
    if (item.max_value !== null && num > item.max_value) {
      ElMessage.warning(`不能大于 ${item.max_value}`)
      return
    }
  }
  savingKey.value = item.setting_key
  try {
    await settingApi.update({ setting_key: item.setting_key, setting_value: value })
    ElMessage.success('配置已保存')
    load()
  } finally {
    savingKey.value = ''
  }
}

async function resetAll() {
  try {
    await ElMessageBox.confirm('确认把全部配置恢复为系统默认值吗？', '恢复默认配置', {
      confirmButtonText: '恢复',
      cancelButtonText: '再想想',
      type: 'warning'
    })
  } catch {
    return
  }
  await settingApi.reset()
  ElMessage.success('已恢复默认配置')
  load()
}

onMounted(load)
</script>

<style scoped>
.setting-list {
  display: flex;
  flex-direction: column;
}

.setting-item {
  display: flex;
  align-items: center;
  gap: var(--pp-space-4);
  padding: var(--pp-space-4) 0;
  border-bottom: 1px dashed var(--pp-border-light);
}

.setting-item:last-child {
  border-bottom: none;
}

.setting-item__info {
  flex: 1;
  min-width: 0;
}

.setting-item__label {
  font-size: var(--pp-fs-base);
  color: var(--pp-text-primary);
  font-weight: var(--pp-fw-medium);
}

.setting-item__key {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-placeholder);
  font-family: var(--pp-font-num);
  margin-top: 2px;
}

.setting-item__control {
  flex: none;
}

.setting-item__range {
  width: 110px;
  flex: none;
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  font-family: var(--pp-font-num);
  text-align: right;
}

@media (max-width: 900px) {
  .setting-item {
    flex-wrap: wrap;
  }
  .setting-item__range {
    text-align: left;
  }
}
</style>
