/** RAG 知识库管理：店员只读查看，店长上传/删除/重建。检索统一走 AI 对话，此页不提供搜索接口。 */
import http from './request'
import type {
  KnowledgeChunk,
  KnowledgeDocument,
  KnowledgeMeta,
  KnowledgeTask,
  KnowledgeUploadResult,
  PageData
} from '@/types'

export interface KnowledgeDocumentQuery {
  keyword?: string
  status?: string
  page?: number
  size?: number
}

export interface KnowledgeTaskQuery {
  status?: string
  page?: number
  size?: number
}

export interface UploadKnowledgeOptions {
  strategy: 'fixed' | 'paragraph' | 'heading'
  chunkSize: number
  chunkOverlap: number
  onProgress?: (percent: number) => void
}

export const knowledgeApi = {
  meta: () => http.get<any, KnowledgeMeta>('/knowledge/meta'),
  documents: (params?: KnowledgeDocumentQuery) =>
    http.get<any, PageData<KnowledgeDocument>>('/knowledge/documents', { params }),
  chunks: (documentId: number, page = 1, size = 20) =>
    http.get<any, PageData<KnowledgeChunk>>(`/knowledge/documents/${documentId}/chunks`, {
      params: { page, size }
    }),
  tasks: (params?: KnowledgeTaskQuery) =>
    http.get<any, PageData<KnowledgeTask>>('/knowledge/tasks', { params }),
  task: (taskId: number) => http.get<any, KnowledgeTask>(`/knowledge/tasks/${taskId}`),
  upload: (files: File[], options: UploadKnowledgeOptions) => {
    const form = new FormData()
    files.forEach((file) => form.append('files', file, file.name))
    form.append('strategy', options.strategy)
    form.append('chunk_size', String(options.chunkSize))
    form.append('chunk_overlap', String(options.chunkOverlap))
    return http.post<any, KnowledgeUploadResult>('/knowledge/documents/upload', form, {
      headers: {
        'Content-Type': 'multipart/form-data',
        'X-Skip-Idempotent': '1'
      },
      timeout: 120000,
      onUploadProgress: (event) => {
        if (!event.total) return
        options.onProgress?.(Math.round((event.loaded / event.total) * 100))
      }
    })
  },
  deleteDocument: (documentId: number) =>
    http.delete<any, { deleted_id: number; rebuild_task: KnowledgeTask }>(
      `/knowledge/documents/${documentId}`
    ),
  rebuild: () => http.post<any, KnowledgeTask>('/knowledge/index/rebuild', {})
}
