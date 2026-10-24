<!--
  主体框架：侧边栏（可折叠）+ 顶栏（面包屑 / 消息 / 用户菜单）+ 内容区。
  所有业务页面都嵌在它的 router-view 里，页面自身不画框架。
-->

<template>
  <el-container class="pp-layout">
    <!-- 顶栏 -->
    <el-header class="pp-header">
      <div class="pp-brand" @click="router.push(userStore.homePath)">
        <div class="pp-brand__logo">
          <svg viewBox="0 0 32 32" aria-hidden="true">
            <ellipse cx="16" cy="20" rx="8" ry="7" fill="#fff" opacity=".95" />
            <ellipse cx="9" cy="12" rx="3" ry="3.6" fill="#fff" opacity=".95" />
            <ellipse cx="14" cy="9" rx="3" ry="3.6" fill="#fff" opacity=".95" />
            <ellipse cx="19.5" cy="9" rx="3" ry="3.6" fill="#fff" opacity=".95" />
            <ellipse cx="24.5" cy="12" rx="3" ry="3.6" fill="#fff" opacity=".95" />
          </svg>
        </div>
        <div class="pp-brand__text">
          <span class="pp-brand__name">PawPilot</span>
          <span class="pp-brand__sub">宠物洗护 · 智能预约与档案助手</span>
        </div>
      </div>

      <el-icon class="pp-collapse" @click="appStore.toggleCollapse()">
        <component :is="appStore.collapsed ? 'Expand' : 'Fold'" />
      </el-icon>

      <div class="pp-header__right">
        <div class="pp-role-chip">
          <el-icon :size="13"><component :is="roleIcon" /></el-icon>
          {{ userStore.roleLabel }}视角
        </div>

        <el-tooltip content="消息中心" placement="bottom">
          <el-badge :value="userStore.unread" :hidden="!userStore.unread" :max="99">
            <el-button circle text :icon="Bell" @click="router.push('/user/messages')" />
          </el-badge>
        </el-tooltip>

        <el-dropdown trigger="click" @command="onCommand">
          <div class="pp-user">
            <div class="pp-user__avatar">{{ avatarText }}</div>
            <div class="pp-user__meta">
              <span class="pp-user__name">{{ userStore.displayName }}</span>
              <span class="pp-user__phone">{{ userStore.userInfo?.phone_masked || '未绑定手机号' }}</span>
            </div>
            <el-icon :size="12"><ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">个人资料</el-dropdown-item>
              <el-dropdown-item command="password">修改密码</el-dropdown-item>
              <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-header>

    <el-container class="pp-body">
      <!-- 侧边菜单（≥1024 常驻；<1024 抽屉） -->
      <el-aside
        v-if="!isNarrow"
        :width="appStore.collapsed ? 'var(--pp-sidebar-collapsed-w)' : 'var(--pp-sidebar-w)'"
        class="pp-aside"
      >
        <SideMenu :collapsed="appStore.collapsed" />
      </el-aside>

      <el-drawer
        v-model="drawerVisible"
        direction="ltr"
        :with-header="false"
        size="260px"
        class="pp-drawer"
      >
        <SideMenu :collapsed="false" @navigate="appStore.closeDrawer()" />
      </el-drawer>

      <el-container direction="vertical" class="pp-main-wrap">
        <div class="pp-crumb">
          <el-breadcrumb separator="/">
            <el-breadcrumb-item v-for="(item, i) in crumbs" :key="i">{{ item }}</el-breadcrumb-item>
          </el-breadcrumb>
          <span class="pp-crumb__date">{{ todayText }}</span>
        </div>

        <el-main class="pp-main">
          <router-view v-slot="{ Component, route }">
            <transition name="pp-fade" mode="out-in">
              <component :is="Component" :key="route.path" />
            </transition>
          </router-view>
        </el-main>
      </el-container>
    </el-container>

    <!-- 个人资料 -->
    <el-dialog v-model="profileVisible" title="个人资料" width="480px" align-center>
      <el-form :model="profileForm" label-width="92px">
        <el-form-item label="登录账号">
          <el-input :model-value="userStore.userInfo?.username" disabled />
        </el-form-item>
        <el-form-item label="姓名 / 昵称">
          <el-input v-model="profileForm.real_name" maxlength="50" placeholder="请输入姓名" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="profileForm.phone" maxlength="11" placeholder="11 位手机号" />
          <div class="pp-form-hint">当前绑定：{{ userStore.userInfo?.phone_masked || '未绑定' }}</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="profileVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveProfile">保存</el-button>
      </template>
    </el-dialog>

    <!-- 修改密码 -->
    <el-dialog v-model="pwdVisible" title="修改密码" width="480px" align-center>
      <el-form ref="pwdRef" :model="pwdForm" :rules="pwdRules" label-width="92px">
        <el-form-item label="原密码" prop="old_password">
          <el-input v-model="pwdForm.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="6-32 位" />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm">
          <el-input v-model="pwdForm.confirm" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="savePassword">确认修改</el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { ArrowDown, Bell } from '@element-plus/icons-vue'
import SideMenu from './components/SideMenu.vue'
import { authApi } from '@/api/auth'
import { useAppStore } from '@/stores/app'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const userStore = useUserStore()

const saving = ref(false)
const profileVisible = ref(false)
const pwdVisible = ref(false)
const pwdRef = ref<FormInstance>()
const windowWidth = ref(window.innerWidth)

const profileForm = reactive({ real_name: '', phone: '' })
const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })

const pwdRules: FormRules = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, max: 32, message: '密码长度 6-32 位', trigger: 'blur' }
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_r, value, cb) =>
        value === pwdForm.new_password ? cb() : cb(new Error('两次输入的密码不一致')),
      trigger: 'blur'
    }
  ]
}

const isNarrow = computed(() => windowWidth.value < 1024)
const drawerVisible = computed({
  get: () => appStore.drawerOpen,
  set: (v: boolean) => (v ? appStore.openDrawer() : appStore.closeDrawer())
})

const crumbs = computed<string[]>(() => {
  const meta = route.meta.breadcrumb as string[] | undefined
  return meta && meta.length ? meta : [String(route.meta.title || '首页')]
})

const avatarText = computed(() => userStore.displayName.slice(0, 1))
const roleIcon = computed(() =>
  userStore.role === 'manager' ? 'Medal' : userStore.role === 'staff' ? 'Suitcase' : 'User'
)
const todayText = computed(() => {
  const d = new Date()
  const weeks = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${weeks[d.getDay()]}`
})

function onResize() {
  windowWidth.value = window.innerWidth
  if (window.innerWidth < 1024) appStore.closeDrawer()
}

watch(isNarrow, (narrow) => {
  if (!narrow) appStore.closeDrawer()
})

watch(
  () => route.path,
  () => {
    if (isNarrow.value) appStore.closeDrawer()
    userStore.refreshUnread()
  }
)

async function onCommand(command: string) {
  if (command === 'profile') {
    profileForm.real_name = userStore.userInfo?.real_name || ''
    profileForm.phone = ''
    profileVisible.value = true
  } else if (command === 'password') {
    pwdForm.old_password = ''
    pwdForm.new_password = ''
    pwdForm.confirm = ''
    pwdVisible.value = true
  } else if (command === 'logout') {
    try {
      await ElMessageBox.confirm('确认退出当前账号吗？', '退出登录', {
        confirmButtonText: '退出',
        cancelButtonText: '再想想',
        type: 'warning'
      })
    } catch {
      return
    }
    await userStore.logout()
    ElMessage.success('已安全退出，期待下次见 🐾')
    router.replace('/login')
  }
}

async function saveProfile() {
  saving.value = true
  try {
    const payload: { real_name?: string; phone?: string } = { real_name: profileForm.real_name }
    if (profileForm.phone) payload.phone = profileForm.phone
    await authApi.updateProfile(payload)
    await userStore.fetchMe()
    ElMessage.success('资料已更新')
    profileVisible.value = false
  } finally {
    saving.value = false
  }
}

async function savePassword() {
  await pwdRef.value?.validate()
  saving.value = true
  try {
    await authApi.changePassword({
      old_password: pwdForm.old_password,
      new_password: pwdForm.new_password
    })
    ElMessage.success('密码已更新，请重新登录')
    pwdVisible.value = false
    await userStore.logout()
    router.replace('/login')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  window.addEventListener('resize', onResize)
  onResize()
  userStore.refreshUnread()
})

onUnmounted(() => window.removeEventListener('resize', onResize))
</script>

<style scoped>
.pp-layout {
  height: 100vh;
  background: var(--pp-bg-page);
}

/* ---------------- 顶栏 ---------------- */
.pp-header {
  height: var(--pp-header-h);
  display: flex;
  align-items: center;
  gap: var(--pp-space-4);
  padding: 0 var(--pp-space-5);
  background: var(--pp-bg-card);
  border-bottom: 1px solid var(--pp-border-light);
  position: sticky;
  top: 0;
  z-index: 20;
}

.pp-brand {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  cursor: pointer;
  min-width: 0;
}

.pp-brand__logo {
  width: 38px;
  height: 38px;
  border-radius: var(--pp-radius-md);
  background: linear-gradient(135deg, var(--pp-primary-light), var(--pp-primary));
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 6px 16px rgba(91, 155, 213, 0.28);
  flex: none;
}

.pp-brand__logo svg {
  width: 24px;
  height: 24px;
}

.pp-brand__text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
  min-width: 0;
}

.pp-brand__name {
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-md);
  font-weight: var(--pp-fw-bold);
  color: var(--pp-text-primary);
  letter-spacing: 0.3px;
}

.pp-brand__sub {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  white-space: nowrap;
}

.pp-collapse {
  font-size: 18px;
  color: var(--pp-text-secondary);
  cursor: pointer;
  padding: 8px;
  border-radius: var(--pp-radius-sm);
  transition: all var(--pp-dur-fast) var(--pp-ease);
}

.pp-collapse:hover {
  background: var(--pp-bg-cream);
  color: var(--pp-primary-dark);
}

.pp-header__right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--pp-space-3);
}

.pp-role-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 12px;
  border-radius: var(--pp-radius-pill);
  background: var(--pp-primary-lighter);
  color: var(--pp-primary-dark);
  font-size: var(--pp-fs-xs);
  font-weight: var(--pp-fw-medium);
}

.pp-user {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  padding: 5px 12px 5px 5px;
  border-radius: var(--pp-radius-pill);
  cursor: pointer;
  transition: background var(--pp-dur-fast) var(--pp-ease);
  outline: none;
}

.pp-user:hover {
  background: var(--pp-bg-cream);
}

.pp-user__avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--pp-primary-light), var(--pp-primary));
  color: #fff;
  font-weight: var(--pp-fw-semibold);
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
}

.pp-user__meta {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}

.pp-user__name {
  font-size: var(--pp-fs-sm);
  font-weight: var(--pp-fw-medium);
  color: var(--pp-text-primary);
}

.pp-user__phone {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  font-family: var(--pp-font-num);
}

/* ---------------- 主体 ---------------- */
.pp-body {
  height: calc(100vh - var(--pp-header-h));
}

.pp-aside {
  background: var(--pp-bg-card);
  border-right: 1px solid var(--pp-border-light);
  transition: width var(--pp-dur) var(--pp-ease);
  overflow-x: hidden;
}

.pp-main-wrap {
  overflow: hidden;
}

.pp-crumb {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px var(--pp-space-5);
  background: var(--pp-bg-card);
  border-bottom: 1px solid var(--pp-border-light);
  flex: none;
}

.pp-crumb :deep(.el-breadcrumb__inner) {
  color: var(--pp-text-secondary);
  font-weight: var(--pp-fw-normal);
  font-size: var(--pp-fs-sm);
}

.pp-crumb :deep(.el-breadcrumb__item:last-child .el-breadcrumb__inner) {
  color: var(--pp-text-primary);
  font-weight: var(--pp-fw-medium);
}

.pp-crumb__date {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-placeholder);
  font-family: var(--pp-font-num);
}

.pp-main {
  background-color: var(--pp-bg-page);
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'%3E%3Cg fill='%235B9BD5' fill-opacity='0.028'%3E%3Cellipse cx='30' cy='38' rx='7' ry='9'/%3E%3Cellipse cx='18' cy='28' rx='3.4' ry='4.4'/%3E%3Cellipse cx='26' cy='22' rx='3.4' ry='4.4'/%3E%3Cellipse cx='35' cy='22' rx='3.4' ry='4.4'/%3E%3Cellipse cx='42' cy='28' rx='3.4' ry='4.4'/%3E%3C/g%3E%3C/svg%3E");
  padding: 0;
  overflow-y: auto;
}

.pp-form-hint {
  margin-top: 4px;
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

:deep(.pp-drawer .el-drawer__body) {
  padding: 0;
}
</style>
