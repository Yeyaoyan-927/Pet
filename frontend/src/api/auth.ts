/**
 * 认证接口：登录、刷新令牌、当前用户信息。
 * 刷新由 request.ts 的 401 拦截器自动调用，业务代码一般不直接调。
 */

import http from './request'
import type { LoginResult, UserInfo } from '@/types'

export const authApi = {
  login: (data: { username: string; password: string }) =>
    http.post<never, LoginResult>('/auth/login', data),
  register: (data: { username: string; password: string; real_name?: string; phone?: string }) =>
    http.post<never, LoginResult>('/auth/register', data),
  refresh: (refresh_token: string) =>
    http.post<never, { access_token: string }>('/auth/refresh', { refresh_token }),
  me: () => http.get<never, UserInfo>('/auth/me'),
  updateProfile: (data: { real_name?: string; phone?: string }) =>
    http.put<never, UserInfo>('/auth/me', data),
  changePassword: (data: { old_password: string; new_password: string }) =>
    http.post<never, null>('/auth/change-password', data),
  logout: () => http.post<never, null>('/auth/logout')
}

export const userApi = {
  list: (params: { page?: number; size?: number; role?: string; keyword?: string }) =>
    http.get<never, { items: UserInfo[]; total: number; page: number; size: number }>('/users', { params }),
  create: (data: {
    username: string
    password: string
    real_name: string
    role: string
    phone?: string
  }) => http.post<never, UserInfo>('/users', data),
  toggleStatus: (id: number) =>
    http.post<never, { id: number; status: number }>(`/users/${id}/status`)
}
