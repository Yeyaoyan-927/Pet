/**
 * 用户状态：当前用户、角色、Token、未读消息数。
 * 登录/登出/刷新用户信息都走这里，路由守卫与菜单都依赖它的 role。
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { authApi } from '@/api/auth'
import { messageApi } from '@/api/message'
import {
  clearAuthStorage,
  getAccessToken,
  getStoredUser,
  setStoredUser,
  setTokens
} from '@/api/request'
import type { UserInfo, UserRole } from '@/types'

export const useUserStore = defineStore('user', () => {
  const token = ref<string>(getAccessToken())
  const userInfo = ref<UserInfo | null>(getStoredUser<UserInfo>())
  const unread = ref(0)

  const isLogin = computed(() => !!token.value)
  const role = computed<UserRole>(() => userInfo.value?.role ?? 'customer')
  const isCustomer = computed(() => role.value === 'customer')
  const isStaff = computed(() => role.value === 'staff' || role.value === 'manager')
  const isManager = computed(() => role.value === 'manager')
  const displayName = computed(() => userInfo.value?.real_name || userInfo.value?.username || '-')
  /** 角色首页：登录后与访问无权限页时的回落目标 */
  const homePath = computed(() => (isCustomer.value ? '/user/home' : '/staff/home'))
  const roleLabel = computed(
    () => ({ customer: '宠主', staff: '店员', manager: '店长' })[role.value] || '用户'
  )

  function applyAuth(res: { access_token: string; refresh_token: string; user: UserInfo }) {
    token.value = res.access_token
    setTokens(res.access_token, res.refresh_token)
    userInfo.value = res.user
    setStoredUser(res.user)
  }

  async function login(username: string, password: string) {
    const res = await authApi.login({ username, password })
    applyAuth(res)
    await refreshUnread()
    return res.user
  }

  async function register(payload: {
    username: string
    password: string
    real_name?: string
    phone?: string
  }) {
    const res = await authApi.register(payload)
    applyAuth(res)
    return res.user
  }

  async function fetchMe() {
    if (!token.value) return null
    userInfo.value = await authApi.me()
    setStoredUser(userInfo.value)
    return userInfo.value
  }

  async function refreshUnread() {
    try {
      const res = await messageApi.unreadCount()
      unread.value = res.unread
    } catch {
      unread.value = 0
    }
  }

  async function logout() {
    try {
      await authApi.logout()
    } catch {
      /* 登出失败不阻塞本地清理 */
    }
    reset()
  }

  function reset() {
    token.value = ''
    userInfo.value = null
    unread.value = 0
    clearAuthStorage()
  }

  return {
    token,
    userInfo,
    unread,
    isLogin,
    role,
    roleLabel,
    isCustomer,
    isStaff,
    isManager,
    displayName,
    homePath,
    login,
    register,
    fetchMe,
    refreshUnread,
    logout,
    reset
  }
})
