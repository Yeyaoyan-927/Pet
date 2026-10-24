/**
 * 门店排期接口：周视图与店员负载。
 */

import http from './request'
import type { ScheduleData } from '@/types'

export const scheduleApi = {
  week: (params: { start?: string; days?: number; staff_id?: number }) =>
    http.get<never, ScheduleData>('/schedule', { params }),
  staffLoad: (start: string, end: string) =>
    http.get<never, { staff_id: number; staff_name: string; count: number }[]>(
      '/schedule/staff-load',
      { params: { start, end } }
    )
}
