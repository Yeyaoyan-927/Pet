<!--
  登录页：账号密码登录，成功后写入 store 并按角色跳转默认首页。
-->

<template>
  <div class="login-page">
    <!-- 装饰光斑 -->
    <span class="pp-blob pp-blob--blue" style="width: 420px; height: 420px; left: -120px; top: -100px" />
    <span class="pp-blob pp-blob--peach" style="width: 360px; height: 360px; right: -80px; bottom: -90px" />

    <!-- 左侧品牌区 -->
    <section class="login-brand">
      <div class="login-brand__inner">
        <div class="login-brand__logo">
          <svg viewBox="0 0 32 32"><ellipse cx="16" cy="20" rx="8" ry="7" fill="#fff" /><ellipse cx="9" cy="12" rx="3" ry="3.6" fill="#fff" /><ellipse cx="14" cy="9" rx="3" ry="3.6" fill="#fff" /><ellipse cx="19.5" cy="9" rx="3" ry="3.6" fill="#fff" /><ellipse cx="24.5" cy="12" rx="3" ry="3.6" fill="#fff" /></svg>
        </div>
        <h1 class="login-brand__title">PawPilot</h1>
        <p class="login-brand__sub">宠物洗护门店智能预约与档案助手</p>

        <PetIllustration type="dog" :size="188" class="login-brand__art pp-float" />

        <ul class="login-brand__list">
          <li><span class="dot dot--blue" />预约状态机闭环，到店、洗护、完成全程可追溯</li>
          <li><span class="dot dot--peach" />洗护风险提前判别，到店前就知道要留意什么</li>
          <li><span class="dot dot--ai" />AI 洗护助手帮你查时段、看档案、约时间</li>
        </ul>
      </div>
    </section>

    <!-- 右侧登录卡片 -->
    <section class="login-panel">
      <el-card class="login-card" shadow="never">
        <h2 class="login-card__title">{{ isRegister ? '为毛孩子注册账号' : '欢迎回来 🐾' }}</h2>
        <p class="login-card__desc">
          {{ isRegister ? '注册后就可以为宠物建立档案、发起洗护预约' : '请使用门店分配的账号，或宠主账号登录' }}
        </p>

        <el-form
          v-if="!isRegister"
          ref="loginRef"
          :model="loginForm"
          :rules="loginRules"
          label-position="top"
          size="large"
          @keyup.enter="doLogin"
        >
          <el-form-item label="登录账号" prop="username">
            <el-input v-model="loginForm.username" placeholder="请输入登录账号" clearable>
              <template #prefix><el-icon><User /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-form-item label="登录密码" prop="password">
            <el-input v-model="loginForm.password" type="password" placeholder="请输入密码" show-password>
              <template #prefix><el-icon><Lock /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-button type="primary" class="login-card__submit" :loading="loading" @click="doLogin">
            登录
          </el-button>
        </el-form>

        <el-form
          v-else
          ref="registerRef"
          :model="registerForm"
          :rules="registerRules"
          label-position="top"
          size="large"
          @keyup.enter="doRegister"
        >
          <el-form-item label="登录账号" prop="username">
            <el-input v-model="registerForm.username" placeholder="4-50 位字母或数字" clearable />
          </el-form-item>
          <el-form-item label="姓名 / 昵称" prop="real_name">
            <el-input v-model="registerForm.real_name" placeholder="怎么称呼你呀" clearable />
          </el-form-item>
          <el-form-item label="手机号" prop="phone">
            <el-input v-model="registerForm.phone" maxlength="11" placeholder="11 位手机号，便于门店联系" clearable />
          </el-form-item>
          <el-form-item label="登录密码" prop="password">
            <el-input v-model="registerForm.password" type="password" placeholder="6-32 位" show-password />
          </el-form-item>
          <el-button type="primary" class="login-card__submit" :loading="loading" @click="doRegister">
            注册并进入
          </el-button>
        </el-form>

        <div class="login-card__switch">
          <el-button link type="primary" @click="toggleMode">
            {{ isRegister ? '已有账号？返回登录' : '还没有账号？宠主注册' }}
          </el-button>
        </div>

        <el-divider><span class="login-card__divider">体验账号 · 点击自动填充</span></el-divider>
        <div class="login-card__accounts">
          <button
            v-for="acc in demoAccounts"
            :key="acc.username"
            class="demo-chip"
            :class="`demo-chip--${acc.tone}`"
            type="button"
            @click="fillDemo(acc)"
          >
            <span class="demo-chip__role">{{ acc.label }}</span>
            <span class="demo-chip__account">{{ acc.username }} / {{ acc.password }}</span>
          </button>
        </div>
      </el-card>

      <p class="login-footer">PawPilot · 温暖专业地照顾每一位毛孩子</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import PetIllustration from '@/components/PetIllustration.vue'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const loading = ref(false)
const isRegister = ref(false)
const loginRef = ref<FormInstance>()
const registerRef = ref<FormInstance>()

const loginForm = reactive({ username: '', password: '' })
const registerForm = reactive({ username: '', password: '', real_name: '', phone: '' })

const loginRules: FormRules = {
  username: [{ required: true, message: '请输入登录账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入登录密码', trigger: 'blur' }]
}

const registerRules: FormRules = {
  username: [
    { required: true, message: '请输入登录账号', trigger: 'blur' },
    { min: 4, max: 50, message: '账号长度 4-50 位', trigger: 'blur' }
  ],
  real_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  phone: [
    { required: true, message: '请输入手机号', trigger: 'blur' },
    { pattern: /^1\d{10}$/, message: '手机号需为 11 位数字', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 32, message: '密码长度 6-32 位', trigger: 'blur' }
  ]
}

const demoAccounts = [
  { label: '店长', username: 'admin', password: 'admin123', tone: 'manager' },
  { label: '店员', username: 'staff1', password: 'staff123', tone: 'staff' },
  { label: '宠主', username: 'demo', password: '123456', tone: 'customer' },
  { label: '宠主', username: 'liu', password: '123456', tone: 'customer' }
]

function fillDemo(acc: { username: string; password: string }) {
  isRegister.value = false
  loginForm.username = acc.username
  loginForm.password = acc.password
}

function toggleMode() {
  isRegister.value = !isRegister.value
}

async function enter() {
  const redirect = route.query.redirect as string | undefined
  await router.replace(redirect && redirect !== '/login' ? redirect : userStore.homePath)
}

async function doLogin() {
  await loginRef.value?.validate()
  loading.value = true
  try {
    await userStore.login(loginForm.username, loginForm.password)
    ElMessage.success(`欢迎回来，${userStore.displayName} 🐾`)
    await enter()
  } finally {
    loading.value = false
  }
}

async function doRegister() {
  await registerRef.value?.validate()
  loading.value = true
  try {
    await userStore.register({ ...registerForm })
    ElMessage.success('注册成功，先为毛孩子建个温暖的小窝吧 🏠')
    await enter()
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  min-height: 100vh;
  position: relative;
  overflow: hidden;
  background: linear-gradient(135deg, #eef5fc 0%, #fbf8f3 52%, #fdf3e7 100%);
}

/* ---------------- 左侧品牌 ---------------- */
.login-brand {
  flex: 1.05;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--pp-space-7) var(--pp-space-6);
  position: relative;
  z-index: 1;
}

.login-brand__inner {
  max-width: 520px;
  text-align: center;
}

.login-brand__logo {
  width: 58px;
  height: 58px;
  margin: 0 auto var(--pp-space-3);
  border-radius: var(--pp-radius-lg);
  background: linear-gradient(135deg, var(--pp-primary-light), var(--pp-primary));
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 10px 26px rgba(91, 155, 213, 0.3);
}

.login-brand__logo svg {
  width: 34px;
  height: 34px;
}

.login-brand__title {
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-2xl);
  font-weight: var(--pp-fw-bold);
  color: var(--pp-text-primary);
  letter-spacing: 0.5px;
}

.login-brand__sub {
  margin: var(--pp-space-1) 0 var(--pp-space-4);
  font-size: var(--pp-fs-md);
  color: var(--pp-text-secondary);
}

.login-brand__art {
  margin: var(--pp-space-3) 0;
}

.login-brand__list {
  list-style: none;
  padding: 0;
  margin: var(--pp-space-4) 0 0;
  display: inline-flex;
  flex-direction: column;
  gap: var(--pp-space-2);
  text-align: left;
}

.login-brand__list li {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
  background: rgba(255, 255, 255, 0.66);
  border-radius: var(--pp-radius-pill);
  padding: 8px 16px;
  backdrop-filter: blur(6px);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}
.dot--blue {
  background: var(--pp-primary);
}
.dot--peach {
  background: var(--pp-warning);
}
.dot--ai {
  background: var(--pp-ai);
}

/* ---------------- 右侧登录卡 ---------------- */
.login-panel {
  flex: 0.95;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--pp-space-6);
  position: relative;
  z-index: 1;
}

.login-card {
  width: 100%;
  max-width: 428px;
  border-radius: var(--pp-radius-xl);
  border: 1px solid var(--pp-border-light);
  box-shadow: var(--pp-shadow-lg);
  background: #fffdfa;
}

.login-card__title {
  font-size: var(--pp-fs-xl);
  font-weight: var(--pp-fw-semibold);
}

.login-card__desc {
  margin: var(--pp-space-1) 0 var(--pp-space-5);
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-secondary);
}

.login-card__submit {
  width: 100%;
  height: 46px;
  font-size: var(--pp-fs-md);
  border-radius: var(--pp-radius-pill);
  margin-top: var(--pp-space-1);
}

.login-card__switch {
  text-align: center;
  margin-top: var(--pp-space-4);
}

.login-card__divider {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-placeholder);
}

.login-card__accounts {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--pp-space-2);
}

.demo-chip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 10px 14px;
  border-radius: var(--pp-radius-md);
  border: 1px solid var(--pp-border-light);
  background: var(--pp-bg-card);
  cursor: pointer;
  transition: all var(--pp-dur-fast) var(--pp-ease);
  text-align: left;
  font-family: inherit;
}

.demo-chip:hover {
  transform: translateY(-1px);
  box-shadow: var(--pp-shadow-sm);
  border-color: var(--pp-primary-light);
}

.demo-chip__role {
  font-size: var(--pp-fs-xs);
  font-weight: var(--pp-fw-semibold);
}

.demo-chip__account {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
  font-family: var(--pp-font-num);
}

.demo-chip--manager .demo-chip__role {
  color: #c25a3f;
}
.demo-chip--staff .demo-chip__role {
  color: var(--pp-primary-dark);
}
.demo-chip--customer .demo-chip__role {
  color: #4e8a4d;
}

.login-footer {
  margin-top: var(--pp-space-5);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-placeholder);
}

@media (max-width: 1024px) {
  .login-brand {
    display: none;
  }
  .login-panel {
    flex: 1;
  }
}
</style>
