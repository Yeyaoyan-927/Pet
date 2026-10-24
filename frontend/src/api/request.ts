/**
 * Axios 统一封装
 * - 自动注入 Bearer Token
 * - 401 时用 refresh_token 静默续期，并将并发失败请求排队后自动重放（无感刷新）
 * - 统一解包 { code, message, data }；业务失败弹柔和提示
 * - 写操作自动携带幂等键，双入口（表单 / Agent）共用同一幂等规范
 */
import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig
} from 'axios'
import { ElMessage } from 'element-plus'
import { genIdempotentKey } from '@/utils/format'

const ACCESS_KEY = 'pawpilot_access_token'
const REFRESH_KEY = 'pawpilot_refresh_token'
const USER_KEY = 'pawpilot_user'

const WRITE_METHODS = ['post', 'put', 'patch', 'delete']
/** 这些路径本身就是鉴权入口，不参与静默续期逻辑 */
const AUTH_WHITELIST = ['/auth/login', '/auth/register', '/auth/refresh']

export function getAccessToken(): string {
  return localStorage.getItem(ACCESS_KEY) || ''
}

export function getRefreshToken(): string {
  return localStorage.getItem(REFRESH_KEY) || ''
}

export function setTokens(access: string, refresh?: string): void {
  localStorage.setItem(ACCESS_KEY, access)
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
}

export function clearAuthStorage(): void {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
  localStorage.removeItem(USER_KEY)
}

export function getStoredUser<T>(): T | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

export function setStoredUser(user: unknown): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

const http: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' }
})

/* ------------------------------------------------------------------ 请求拦截 */
http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken()
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  // 写操作自动补幂等键（调用方显式传入时优先）
  const method = (config.method || 'get').toLowerCase()
  if (WRITE_METHODS.includes(method) && config.data && typeof config.data === 'object') {
    const body = config.data as Record<string, unknown>
    if (!body.idempotent_key && !(config.headers as Record<string, string>)['X-Skip-Idempotent']) {
      body.idempotent_key = genIdempotentKey('web')
    }
  }
  return config
})

/* ------------------------------------------------- 401 静默续期：队列化重放 */
let refreshing = false
let waiters: ((token: string | null) => void)[] = []

function flushWaiters(token: string | null) {
  waiters.forEach((resolve) => resolve(token))
  waiters = []
}

/** 跳转登录（避免在拦截器里直接 import router 造成循环依赖） */
function gotoLogin() {
  clearAuthStorage()
  const redirect = encodeURIComponent(window.location.pathname + window.location.search)
  if (!window.location.pathname.startsWith('/login')) {
    window.location.replace(`/login?redirect=${redirect}`)
  }
}

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return null
  try {
    const resp = await axios.post(
      `${import.meta.env.VITE_API_BASE_URL || '/api/v1'}/auth/refresh`,
      { refresh_token: refreshToken },
      { headers: { 'Content-Type': 'application/json' }, timeout: 15000 }
    )
    const payload = resp.data
    if (payload?.code === 0 && payload.data?.access_token) {
      setTokens(payload.data.access_token)
      return payload.data.access_token as string
    }
    return null
  } catch {
    return null
  }
}

/* ------------------------------------------------------------------ 响应拦截 */
http.interceptors.response.use(
  (response) => {
    const payload = response.data
    if (response.config.responseType === 'blob' || !payload || typeof payload !== 'object' || !('code' in payload)) {
      return payload
    }
    if (payload.code === 0) return payload.data
    ElMessage.error(payload.message || '请求失败')
    return Promise.reject(new Error(payload.message || '请求失败'))
  },
  async (error) => {
    const status = error?.response?.status
    const original = error?.config as InternalAxiosRequestConfig & { _retried?: boolean }
    const url = String(original?.url || '')
    const isAuthApi = AUTH_WHITELIST.some((p) => url.includes(p))

    // 401 → 静默续期后重放（仅重试一次，且不处理鉴权接口自身）
    if (status === 401 && original && !original._retried && !isAuthApi) {
      original._retried = true

      if (refreshing) {
        // 已有续期在途：排队等待结果
        const token = await new Promise<string | null>((resolve) => waiters.push(resolve))
        if (!token) return Promise.reject(error)
        original.headers = original.headers || {}
        original.headers.Authorization = `Bearer ${token}`
        return http.request(original)
      }

      refreshing = true
      try {
        const token = await refreshAccessToken()
        flushWaiters(token)
        if (!token) {
          gotoLogin()
          return Promise.reject(error)
        }
        original.headers = original.headers || {}
        original.headers.Authorization = `Bearer ${token}`
        return await http.request(original)
      } finally {
        refreshing = false
      }
    }

    const message = error?.response?.data?.message || error.message || '网络开小差了，请稍后再试'
    if (status === 401) {
      gotoLogin()
      ElMessage.error('登录状态已过期，请重新登录')
    } else if (status === 403) {
      ElMessage.error(message || '当前账号没有这个权限')
    } else if (status === 404) {
      ElMessage.error(message || '没有找到对应的数据')
    } else {
      ElMessage.error(message)
    }
    return Promise.reject(error)
  }
)

/** 原始请求（用于文件下载等需要读取响应头的场景） */
export async function rawRequest<T = Blob>(config: AxiosRequestConfig): Promise<{
  data: T
  headers: Record<string, string>
}> {
  const token = getAccessToken()
  const resp = await axios.request<T>({
    baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
    ...config,
    headers: { ...(config.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) }
  })
  return { data: resp.data, headers: resp.headers as Record<string, string> }
}

export default http
