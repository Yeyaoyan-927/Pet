<!--
  疫苗 / 驱虫记录抽屉（可复用）：档案卡片与档案编辑页共用同一个抽屉，避免两处各写一套。

  为什么抽成组件：寄养下单的「疫苗硬门槛」依赖这里的记录，
  如果入口只藏在卡片的「更多」下拉里，用户找不到登记入口就会以为寄养功能坏了。

  数据来源：GET /pets/{id}/vaccines、POST /pets/{id}/vaccines。
-->
<template>
  <el-drawer
    :model-value="modelValue"
    :title="`疫苗 / 驱虫记录 · ${petName || ''}`"
    size="540px"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
    @open="load"
  >
    <el-form :model="form" label-width="96px">
      <el-form-item label="记录类型">
        <el-select v-model="form.record_type" style="width: 100%">
          <el-option v-for="(label, value) in VACCINE_TYPE_LABEL" :key="value" :label="label" :value="value" />
        </el-select>
      </el-form-item>
      <el-form-item label="名称">
        <el-input v-model="form.name" maxlength="100" placeholder="如：狂犬疫苗 / 拜宠清" />
      </el-form-item>
      <el-form-item label="本次日期">
        <el-date-picker v-model="form.record_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
      </el-form-item>
      <el-form-item label="下次日期">
        <el-date-picker
          v-model="form.next_date"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="寄养要求入住当天仍在有效期内"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="saving" @click="add">添加记录</el-button>
      </el-form-item>
    </el-form>

    <PawLoading v-if="loading" variant="tail" text="加载记录中…" />
    <EmptyState v-else-if="!records.length" illustration="cat" title="还没有疫苗 / 驱虫记录" />
    <el-table v-else :data="records" size="small">
      <el-table-column label="类型" width="100">
        <template #default="{ row }">{{ VACCINE_TYPE_LABEL[row.record_type] }}</template>
      </el-table-column>
      <el-table-column prop="name" label="名称" min-width="130" show-overflow-tooltip />
      <el-table-column prop="record_date" label="本次" width="110" />
      <el-table-column prop="next_date" label="下次" width="110">
        <template #default="{ row }">
          <span :class="{ 'is-expiring': isExpiring(row.next_date) }">{{ row.next_date || '-' }}</span>
        </template>
      </el-table-column>
    </el-table>
  </el-drawer>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import { petApi } from '@/api/pet'
import { VACCINE_TYPE_LABEL } from '@/utils/dict'
import { toDateStr } from '@/utils/format'
import type { VaccineRecord } from '@/types'

const props = defineProps<{
  modelValue: boolean
  petId: number | null
  petName?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'changed'): void
}>()

const loading = ref(false)
const saving = ref(false)
const records = ref<VaccineRecord[]>([])
const form = reactive({
  record_type: 'vaccine' as VaccineRecord['record_type'],
  name: '',
  record_date: toDateStr(new Date()),
  next_date: ''
})

function isExpiring(next?: string | null) {
  if (!next) return false
  const diff = (new Date(next).getTime() - Date.now()) / 86_400_000
  return diff <= 30
}

async function load() {
  if (!props.petId) return
  loading.value = true
  try {
    records.value = await petApi.vaccines(props.petId)
  } finally {
    loading.value = false
  }
}

async function add() {
  if (!props.petId) return
  if (!form.record_date) {
    ElMessage.warning('请选择本次接种 / 驱虫日期')
    return
  }
  saving.value = true
  try {
    await petApi.addVaccine(props.petId, { ...form, next_date: form.next_date || null })
    ElMessage.success('记录已添加')
    records.value = await petApi.vaccines(props.petId)
    form.name = ''
    form.next_date = ''
    emit('changed')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.is-expiring {
  color: var(--pp-danger);
  font-weight: var(--pp-fw-medium);
}
</style>
