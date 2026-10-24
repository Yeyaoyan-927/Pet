/**
 * 经营报表接口：总览、导出台账、流失宠物、审计日志。
 * 导出接口返回文件流，由页面触发下载。
 */

import http, { rawRequest } from './request'
import type { AuditLogItem, PageData, ReportSummary } from '@/types'

export const reportApi = {
  summary: (params: { start?: string; end?: string }) =>
    http.get<never, ReportSummary>('/report/summary', { params }),
  churn: () =>
    http.get<never, { churn_days: number; items: ReportSummary['churn_pets'] }>('/report/churn'),
  auditLogs: (params: { page?: number; size?: number; module?: string }) =>
    http.get<never, PageData<AuditLogItem>>('/report/audit-logs', { params }),
  /** 导出 CSV：返回 blob 与响应头（用于解析中文文件名） */
  exportCsv: (params: { type?: string; start?: string; end?: string }) =>
    rawRequest<Blob>({
      url: '/report/export',
      method: 'GET',
      params,
      responseType: 'blob'
    })
}
