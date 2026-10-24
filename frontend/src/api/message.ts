/**
 * 站内信接口：列表、未读数、单条已读、全部已读、删除。
 */

import http from './request'
import type { MessageItem, PageData } from '@/types'

export const messageApi = {
  list: (params: { page?: number; size?: number; only_unread?: boolean }) =>
    http.get<never, PageData<MessageItem>>('/messages', { params }),
  unreadCount: () => http.get<never, { unread: number }>('/messages/unread-count'),
  readAll: () => http.post<never, { updated: number }>('/messages/read-all'),
  read: (id: number) => http.post<never, null>(`/messages/${id}/read`),
  remove: (id: number) => http.delete<never, null>(`/messages/${id}`)
}
