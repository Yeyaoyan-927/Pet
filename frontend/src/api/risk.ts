/**
 * 风险报告接口：列表、按预约查询、重跑判别、复核确认。
 */

import http from './request'
import type { PageData, RiskReport } from '@/types'

export const riskApi = {
  list: (params: { page?: number; size?: number; only_unconfirmed?: boolean }) =>
    http.get<never, PageData<RiskReport>>('/risks', { params }),
  byAppointment: (appointmentId: number) =>
    http.get<never, RiskReport>(`/risks/appointment/${appointmentId}`),
  rerun: (appointmentId: number) =>
    http.post<never, RiskReport>(`/risks/appointment/${appointmentId}/rerun`),
  confirm: (appointmentId: number, data: { handle_measure?: string; manual_level?: string }) =>
    http.post<never, RiskReport>(`/risks/appointment/${appointmentId}/confirm`, data)
}
