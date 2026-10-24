/**
 * AI 对话助手接口。
 *
 * 注意：SSE 使用 fetch + ReadableStream 实现（EventSource 不支持 POST 与自定义请求头）。
 * 后端事件流格式：`data: {json}\n\n`
 */
import http, { getAccessToken } from './request'
import type { AgentEvent, ChatCapabilities, ChatHistoryMessage, ChatSessionItem } from '@/types'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export const chatApi = {
  capabilities: () => http.get<never, ChatCapabilities>('/chat/capabilities'),
  sessions: () => http.get<never, ChatSessionItem[]>('/chat/sessions'),
  createSession: (title?: string) =>
    http.post<never, { id: number; title: string }>('/chat/sessions', { title }),
  messages: (sessionId: number) =>
    http.get<never, { session_id: number; title: string; messages: ChatHistoryMessage[] }>(
      `/chat/sessions/${sessionId}/messages`
    ),
  removeSession: (sessionId: number) => http.delete<never, null>(`/chat/sessions/${sessionId}`)
}

export interface StreamChatOptions {
  content: string
  sessionId?: number | null
  onEvent: (event: AgentEvent) => void
  signal?: AbortSignal
}

export async function streamChat(options: StreamChatOptions): Promise<void> {
  const { content, sessionId, onEvent, signal } = options
  const token = getAccessToken()

  const resp = await fetch(`${API_BASE}/chat/message`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify({ content, session_id: sessionId ?? null }),
    signal
  })

  if (!resp.ok) {
    let detail = `请求失败（${resp.status}）`
    try {
      const payload = await resp.json()
      detail = payload?.message || detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  if (!resp.body) throw new Error('当前环境不支持流式响应')

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let idx = buffer.indexOf('\n\n')
    while (idx !== -1) {
      const chunk = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const line = chunk.split('\n').find((l) => l.startsWith('data:'))
      if (line) {
        const raw = line.slice(5).trim()
        if (raw) {
          try {
            onEvent(JSON.parse(raw) as AgentEvent)
          } catch {
            /* 忽略无法解析的片段，保证流不中断 */
          }
        }
      }
      idx = buffer.indexOf('\n\n')
    }
  }
}
