/**
 * 预约接口：时段查询、下单、改期、状态流转、代客预约。
 * 对应后端 /api/v1/appointments/*；写操作都带 idempotent_key，避免重复提交落两笔。
 */

import http from './request'
import type { Appointment, DictOption, OverviewStats, PageData, SlotItem } from '@/types'

export interface AppointmentQuery {
  page?: number
  size?: number
  status?: string
  appoint_date?: string
  keyword?: string
  mine?: boolean
}

export const appointmentApi = {
  list: (params: AppointmentQuery) =>
    http.get<never, PageData<Appointment>>('/appointments', { params }),
  detail: (id: number) => http.get<never, Appointment>(`/appointments/${id}`),
  create: (data: Record<string, unknown>) => http.post<never, Appointment>('/appointments', data),
  createByStaff: (data: Record<string, unknown>) =>
    http.post<never, { id: number; order_no: string }>('/appointments/staff', data),
  changeStatus: (id: number, data: { status: string; reason?: string }) =>
    http.post<never, Appointment>(`/appointments/${id}/status`, data),
  reschedule: (id: number, data: { appoint_date: string; slot_time: string; reason?: string }) =>
    http.post<never, Appointment>(`/appointments/${id}/reschedule`, data),
  slots: (appointDate: string) =>
    http.get<never, { appoint_date: string; slots: SlotItem[]; capacity: number }>(
      '/appointments/slots',
      { params: { appoint_date: appointDate } }
    ),
  options: () => http.get<never, { services: DictOption[]; statuses: DictOption[] }>(
    '/appointments/options'
  ),
  overview: () => http.get<never, OverviewStats>('/appointments/stats/overview'),
  slaScan: () => http.post<never, Record<string, unknown>>('/appointments/sla/scan')
}
