<!--
  员工账号页（店长）：账号列表、新建（随机初始密码一次性展示）、启停用。
  数据来源：GET/POST /users。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">员工账号</h2>
        <p class="pp-page-desc">
          店长可以创建店员 / 店长账号并启用或禁用。店长账号不可禁用；宠主账号由宠主自行注册。
        </p>
      </div>
      <div class="pp-page-actions">
        <el-button type="primary" :icon="Plus" @click="openCreate">新增账号</el-button>
      </div>
    </div>

    <div class="pp-filter">
      <el-form :inline="true" @submit.prevent>
        <el-form-item label="角色">
          <el-select v-model="role" placeholder="全部角色" clearable style="width: 150px" @change="reload">
            <el-option label="店长" value="manager" />
            <el-option label="店员" value="staff" />
            <el-option label="宠主" value="customer" />
          </el-select>
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="keyword" placeholder="搜索姓名" clearable style="width: 180px" @keyup.enter="reload" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="reload">查询</el-button>
        </el-form-item>
      </el-form>
    </div>

    <section class="pp-card">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        class="pp-mb-4"
        title="店长视角下可查看原始手机号，便于门店电话联系；其他角色一律仅见脱敏号码。"
      />

      <PawLoading v-if="loading" variant="paw" text="加载账号列表…" />
      <EmptyState v-else-if="!list.length" illustration="paw" title="没有符合条件的账号" />

      <div v-else class="pp-scroll-x">
        <el-table :data="list" style="width: 100%">
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="username" label="登录账号" min-width="140" />
          <el-table-column prop="real_name" label="姓名" min-width="110" />
          <el-table-column label="角色" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="roleTone(row.role)" effect="light">{{ ROLE_LABEL[row.role] }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="手机号" width="150">
            <template #default="{ row }">
              <span class="pp-num">{{ row.phone || row.phone_masked || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 1 ? 'success' : 'info'" effect="light">
                {{ row.status === 1 ? '启用' : '禁用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最后登录" width="170">
            <template #default="{ row }">
              <span class="pp-num">{{ formatDateTime(row.last_login_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.role !== 'manager'"
                link
                :type="row.status === 1 ? 'danger' : 'primary'"
                @click="toggle(row)"
              >
                {{ row.status === 1 ? '禁用' : '启用' }}
              </el-button>
              <span v-else class="pp-dim">不可操作</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div v-if="total > size" class="pp-pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @size-change="load"
          @current-change="load"
        />
      </div>
    </section>

    <el-dialog v-model="createVisible" title="新增员工账号" width="520px" align-center>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="104px">
        <el-form-item label="登录账号" prop="username">
          <el-input v-model="form.username" maxlength="50" placeholder="4-50 位" />
        </el-form-item>
        <el-form-item label="姓名" prop="real_name">
          <el-input v-model="form.real_name" maxlength="50" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-radio-group v-model="form.role">
            <el-radio-button value="staff">店员</el-radio-button>
            <el-radio-button value="manager">店长</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" maxlength="11" placeholder="选填，11 位手机号" />
        </el-form-item>
        <el-form-item label="初始密码" prop="password">
          <el-input v-model="form.password" type="password" show-password maxlength="32" placeholder="6-32 位" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">创建账号</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import { userApi } from '@/api/auth'
import { ROLE_LABEL } from '@/utils/dict'
import { formatDateTime } from '@/utils/format'
import type { UserInfo } from '@/types'

const loading = ref(true)
const submitting = ref(false)
const list = ref<UserInfo[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const role = ref('')
const keyword = ref('')

const createVisible = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({ username: '', real_name: '', role: 'staff', phone: '', password: '' })

const rules: FormRules = {
  username: [
    { required: true, message: '请输入登录账号', trigger: 'blur' },
    { min: 4, max: 50, message: '账号长度 4-50 位', trigger: 'blur' }
  ],
  real_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
  password: [
    { required: true, message: '请输入初始密码', trigger: 'blur' },
    { min: 6, max: 32, message: '密码长度 6-32 位', trigger: 'blur' }
  ]
}

function roleTone(r: string) {
  return r === 'manager' ? 'danger' : r === 'staff' ? 'primary' : 'success'
}

async function load() {
  loading.value = true
  try {
    const res = await userApi.list({
      page: page.value,
      size: size.value,
      role: role.value || undefined,
      keyword: keyword.value || undefined
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

function openCreate() {
  form.username = ''
  form.real_name = ''
  form.role = 'staff'
  form.phone = ''
  form.password = ''
  createVisible.value = true
}

async function submit() {
  await formRef.value?.validate()
  if (form.phone && !/^1\d{10}$/.test(form.phone)) {
    ElMessage.warning('手机号需为 11 位数字')
    return
  }
  submitting.value = true
  try {
    await userApi.create({ ...form, phone: form.phone || undefined })
    ElMessage.success('账号已创建')
    createVisible.value = false
    load()
  } finally {
    submitting.value = false
  }
}

async function toggle(row: UserInfo) {
  const action = row.status === 1 ? '禁用' : '启用'
  try {
    await ElMessageBox.confirm(`确认${action}账号「${row.real_name || row.username}」吗？`, `${action}确认`, {
      confirmButtonText: action,
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }
  await userApi.toggleStatus(row.id)
  ElMessage.success(`账号已${action}`)
  load()
}

onMounted(load)
</script>
