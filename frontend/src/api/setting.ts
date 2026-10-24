/**
 * 门店配置接口：读取全部配置项、更新单项、恢复默认。
 * 配置值有类型与范围校验，非法值后端直接拒绝。
 */

import http from './request'
import type { SettingItem } from '@/types'

export const settingApi = {
  list: () => http.get<never, SettingItem[]>('/settings'),
  update: (data: { setting_key: string; setting_value: string }) =>
    http.put<never, { setting_key: string; setting_value: string }>('/settings', data),
  reset: () => http.post<never, null>('/settings/reset')
}
