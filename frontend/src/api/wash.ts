/**
 * 洗护记录接口：列表、统计、详情、补录。
 */

import http from './request'
import type { WashRecord, WashStats, PageData } from '@/types'

export interface WashQuery {
  page?: number
  size?: number
  pet_id?: number
  staff_id?: number
  start?: string
  end?: string
  mine?: boolean
}

export const washApi = {
  list: (params: WashQuery) =>
    http.get<never, PageData<WashRecord>>('/wash-records', { params }),
  stats: () => http.get<never, WashStats>('/wash-records/stats'),
  update: (
    id: number,
    data: Partial<Pick<WashRecord, 'skin_condition' | 'hair_condition' | 'products' | 'staff_note'>>
  ) => http.put<never, { id: number }>(`/wash-records/${id}`, data)
}
