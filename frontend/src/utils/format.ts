/** 通用格式化与工具函数。 */

export function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 19)
}

export function formatDate(value?: string | null): string {
  if (!value) return '-'
  return String(value).slice(0, 10)
}

export function formatTime(value?: string | null): string {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(11, 16)
}

export function formatAge(months?: number | null): string {
  if (months === null || months === undefined) return '未知'
  if (months < 12) return `${months} 个月`
  return `${Math.floor(months / 12)} 岁 ${months % 12} 个月`
}

export function formatDuration(start?: string | null, end?: string | null): string {
  if (!start || !end) return '-'
  const s = new Date(String(start).replace(' ', 'T')).getTime()
  const e = new Date(String(end).replace(' ', 'T')).getTime()
  if (Number.isNaN(s) || Number.isNaN(e) || e <= s) return '-'
  const minutes = Math.round((e - s) / 60000)
  return minutes >= 60 ? `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟` : `${minutes} 分钟`
}

export function toDateStr(d: Date): string {
  const m = `${d.getMonth() + 1}`.padStart(2, '0')
  const day = `${d.getDate()}`.padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

export function addDays(d: Date, days: number): Date {
  const next = new Date(d)
  next.setDate(next.getDate() + days)
  return next
}

/** 相对时间：刚刚 / 5 分钟前 / 昨天 14:20 */
export function relativeTime(value?: string | null): string {
  if (!value) return '-'
  const target = new Date(String(value).replace(' ', 'T')).getTime()
  if (Number.isNaN(target)) return formatDateTime(value)
  const diff = Date.now() - target
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  if (diff < 172_800_000) return `昨天 ${String(value).slice(11, 16)}`
  return formatDate(value)
}

/** 生成写操作幂等键：同一表单实例复用同一个 key */
export function genIdempotentKey(prefix = 'form'): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}

/** 从 Content-Disposition 解析文件名（兼容 filename* UTF-8 编码） */
export function parseFilename(disposition: string | undefined, fallback: string): string {
  if (!disposition) return fallback
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1])
    } catch {
      /* ignore */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain?.[1] || fallback
}

export function truncate(text: string, length = 40): string {
  if (!text) return ''
  return text.length > length ? `${text.slice(0, length)}…` : text
}
