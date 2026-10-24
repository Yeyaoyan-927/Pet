<!--
  宠舍管理（店员/店长）：维护房型与具体房号 —— 房号、适配物种、体重上限、定价系数、设施与房态。
  删除仅在「没有任何寄养单引用」时可用；有历史订单的宠舍只能改「维护中」停用（否则订单会指向空房间）。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">宠舍管理</h2>
        <p class="pp-page-desc">
          维护门店的房型与具体房号。房号全店唯一；删除仅在该宠舍没有任何寄养单时可用。
        </p>
      </div>
      <div class="pp-page-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新增宠舍</el-button>
      </div>
    </div>

    <div class="pp-filter">
      <el-form :inline="true" @submit.prevent>
        <el-form-item label="房型">
          <el-select v-model="filterType" clearable placeholder="全部房型" style="width: 160px">
            <el-option v-for="(label, key) in roomTypeOptions" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="房态">
          <el-select v-model="filterStatus" clearable placeholder="全部房态" style="width: 140px">
            <el-option v-for="(label, key) in STATUS_OPTIONS" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键词">
          <el-input v-model="keyword" placeholder="房号 / 名称" clearable style="width: 180px" />
        </el-form-item>
      </el-form>
    </div>

    <section class="pp-card">
      <el-table v-loading="loading" :data="filtered" stripe>
        <el-table-column prop="room_no" label="房号" width="96" />
        <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
        <el-table-column label="房型" width="112">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.room_type_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="适配" width="140">
          <template #default="{ row }">
            {{ SPECIES_LABEL[row.species_limit] || '不限' }}
            <span v-if="row.weight_limit" class="pp-dim">· ≤{{ row.weight_limit }}kg</span>
          </template>
        </el-table-column>
        <el-table-column label="系数" width="76">
          <template #default="{ row }">{{ row.ratio_percent / 100 }}×</template>
        </el-table-column>
        <el-table-column prop="capacity" label="容量" width="70" />
        <el-table-column label="设施" min-width="170">
          <template #default="{ row }">
            <div class="cell-tags">
              <el-tag v-for="f in row.facilities" :key="f" size="small" effect="plain">{{ f }}</el-tag>
              <span v-if="!row.facilities.length" class="pp-dim">—</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="房态" width="104">
          <template #default="{ row }">
            <el-tag size="small" :type="ROOM_STATUS_TONE[row.status] || 'info'" effect="light">
              {{ row.status_label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button
              v-if="row.status !== 'maintenance'"
              link
              type="warning"
              :disabled="row.status === 'occupied'"
              @click="setStatus(row, 'maintenance')"
            >停用</el-button>
            <el-button v-else link type="success" @click="setStatus(row, 'idle')">启用</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="table-foot pp-dim">
        共 {{ filtered.length }} 间（全部 {{ rooms.length }} 间）
      </div>
    </section>

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑宠舍' : '新增宠舍'" width="580px">
      <el-form label-position="top">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="房号" required>
              <el-input v-model="form.room_no" maxlength="32" placeholder="如 A111" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="房型" required>
              <el-select v-model="form.room_type" style="width: 100%">
                <el-option
                  v-for="(label, key) in roomTypeOptions"
                  :key="key"
                  :label="label"
                  :value="key"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" maxlength="50" placeholder="如 标准单间 A111" />
        </el-form-item>
        <el-form-item label="适配物种">
          <el-radio-group v-model="form.species_limit">
            <el-radio-button value="all">不限</el-radio-button>
            <el-radio-button value="dog">仅犬</el-radio-button>
            <el-radio-button value="cat">仅猫</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="最大体重(kg)">
              <el-input-number v-model="form.weight_limit" :min="1" :max="99" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="定价系数(%)">
              <el-input-number
                v-model="form.ratio_percent"
                :min="50"
                :max="500"
                :step="10"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="可容纳数">
              <el-input-number v-model="form.capacity" :min="1" :max="10" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="设施（逗号分隔）">
          <el-input v-model="facilitiesText" placeholder="独立通风,24h监控" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="255" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { boardingApi } from '@/api/boarding'
import { ROOM_STATUS_TONE, SPECIES_LABEL } from '@/utils/dict'
import type { BoardingRoom } from '@/types'

/** 可手工调整的房态（占用中由入住流程自动设置，不在下拉里给） */
const STATUS_OPTIONS: Record<string, string> = {
  idle: '空闲',
  cleaning: '清洁中',
  maintenance: '维护中',
  occupied: '占用中'
}

const rooms = ref<BoardingRoom[]>([])
const roomTypeOptions = ref<Record<string, string>>({})
const loading = ref(false)
const dialogVisible = ref(false)
const submitting = ref(false)
const filterType = ref('')
const filterStatus = ref('')
const keyword = ref('')
const facilitiesText = ref('')
const form = ref(emptyForm())

function emptyForm() {
  return {
    id: undefined as number | undefined,
    room_no: '',
    room_type: 'standard',
    name: '',
    species_limit: 'all',
    weight_limit: 10 as number | undefined,
    ratio_percent: 100,
    capacity: 1,
    remark: ''
  }
}

const filtered = computed(() => {
  const kw = keyword.value.trim()
  return rooms.value.filter(
    (r) =>
      (!filterType.value || r.room_type === filterType.value) &&
      (!filterStatus.value || r.status === filterStatus.value) &&
      (!kw || r.room_no.includes(kw) || r.name.includes(kw))
  )
})

async function load() {
  loading.value = true
  try {
    const [list, meta] = await Promise.all([boardingApi.rooms(), boardingApi.meta()])
    rooms.value = [...list].sort((a, b) => a.room_no.localeCompare(b.room_no))
    roomTypeOptions.value = meta.room_type || {}
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = emptyForm()
  facilitiesText.value = '独立通风,24h监控'
  dialogVisible.value = true
}

function openEdit(row: BoardingRoom) {
  form.value = {
    id: row.id,
    room_no: row.room_no,
    room_type: row.room_type,
    name: row.name,
    species_limit: row.species_limit,
    weight_limit: row.weight_limit ?? undefined,
    ratio_percent: row.ratio_percent,
    capacity: row.capacity,
    remark: row.remark || ''
  }
  facilitiesText.value = (row.facilities || []).join(',')
  dialogVisible.value = true
}

async function submit() {
  if (!form.value.room_no.trim()) {
    ElMessage.warning('请填写房号')
    return
  }
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  submitting.value = true
  try {
    await boardingApi.upsertRoom({
      ...form.value,
      room_no: form.value.room_no.trim().toUpperCase(),
      name: form.value.name.trim(),
      facilities: facilitiesText.value
        .split(/[,，]/)
        .map((f) => f.trim())
        .filter(Boolean)
        .join(',')
    })
    ElMessage.success(form.value.id ? '宠舍已保存' : '宠舍已新增')
    dialogVisible.value = false
    await load()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.message || '保存失败')
  } finally {
    submitting.value = false
  }
}

async function setStatus(row: BoardingRoom, status: string) {
  try {
    await boardingApi.updateRoomStatus(row.id, status)
    ElMessage.success(status === 'maintenance' ? '已停用（维护中）' : '已恢复空闲')
    await load()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.message || '房态更新失败')
  }
}

async function remove(row: BoardingRoom) {
  try {
    await ElMessageBox.confirm(
      `删除「${row.room_no} ${row.name}」后不可恢复；有寄养单记录的宠舍不能删除。`,
      '删除宠舍',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await boardingApi.deleteRoom(row.id)
    ElMessage.success('宠舍已删除')
    await load()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.message || '删除失败')
  }
}

onMounted(load)
</script>

<style scoped>
.pp-page-actions {
  display: flex;
  gap: var(--pp-space-2);
}

.cell-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.table-foot {
  margin-top: var(--pp-space-3);
  font-size: var(--pp-fs-xs);
  text-align: right;
}
</style>
