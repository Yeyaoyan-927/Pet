<!-- 店员/店长共用 RAG 知识库：本页只做文档治理（上传/切块/任务/删除/重建），检索统一在 AI 对话里。 -->
<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">RAG 知识库</h2>
        <p class="pp-page-desc">上传门店规范并切成可追溯片段，作为 AI 对话的知识底座。</p>
      </div>
      <div class="pp-page-actions">
        <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
        <el-button v-if="canManage" :icon="RefreshRight" :loading="rebuilding" @click="rebuildIndex">
          重建索引
        </el-button>
        <el-button v-if="canManage" type="primary" :icon="UploadFilled" @click="openUpload">
          上传文档
        </el-button>
      </div>
    </div>

    <el-alert
      :type="canManage ? 'success' : 'info'"
      :closable="false"
      show-icon
      class="role-tip"
      :title="canManage
        ? '店长权限：可上传、删除文档并重建索引。知识检索请在 AI 对话中提问，本页不设搜索入口。'
        : '店员权限：可查看文档、切块和任务状态；上传、删除和重建索引由店长操作。检索请在 AI 对话中提问。'"
    />

    <div class="summary-grid">
      <div class="summary-card">
        <span>文档</span><strong>{{ meta?.documents ?? 0 }}</strong><small>已上传来源</small>
      </div>
      <div class="summary-card summary-card--ai">
        <span>文本块</span><strong>{{ meta?.chunks ?? 0 }}</strong><small>可追溯片段</small>
      </div>
      <div class="summary-card summary-card--warning">
        <span>处理中</span><strong>{{ meta?.active_tasks ?? 0 }}</strong><small>待处理 / 处理中</small>
      </div>
      <div class="summary-card summary-card--danger">
        <span>失败文档</span><strong>{{ meta?.failed_documents ?? 0 }}</strong><small>可查看失败原因</small>
      </div>
    </div>

    <section class="pp-card content-card">
      <el-tabs v-model="activeTab" @tab-change="onTabChange">
        <el-tab-pane label="文档与切块" name="documents">
          <div class="toolbar">
            <el-input
              v-model="documentQuery.keyword"
              clearable
              placeholder="搜索文件名"
              style="width: 240px"
              @keyup.enter="loadDocuments()"
            />
            <el-select v-model="documentQuery.status" clearable placeholder="全部状态" style="width: 150px">
              <el-option label="待处理" value="pending" />
              <el-option label="处理中" value="processing" />
              <el-option label="已完成" value="completed" />
              <el-option label="失败" value="failed" />
            </el-select>
            <el-button type="primary" plain @click="loadDocuments()">查询</el-button>
          </div>

          <el-table v-loading="documentLoading" :data="documents" stripe>
            <el-table-column label="文件" min-width="230">
              <template #default="{ row }">
                <div class="file-cell">
                  <el-tag size="small" effect="plain">{{ row.file_ext.toUpperCase() }}</el-tag>
                  <div>
                    <div class="file-name">{{ row.original_name }}</div>
                    <div class="pp-dim">{{ formatBytes(row.size_bytes) }} · {{ row.uploader_name || `用户 #${row.uploaded_by}` }}</div>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="切块配置" min-width="170">
              <template #default="{ row }">
                {{ row.chunk_strategy_label }}
                <div class="pp-dim">块 {{ row.chunk_size }} · 重叠 {{ row.chunk_overlap }}</div>
              </template>
            </el-table-column>
            <el-table-column label="结果" width="120">
              <template #default="{ row }">
                <strong>{{ row.total_chunks }}</strong> 块
                <div class="pp-dim">{{ row.text_length }} 字符</div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tooltip v-if="row.error_message" :content="row.error_message" placement="top">
                  <el-tag :type="statusTone(row.status)" effect="light">{{ row.status_label }}</el-tag>
                </el-tooltip>
                <el-tag v-else :type="statusTone(row.status)" effect="light">{{ row.status_label }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="上传时间" width="168">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" :disabled="!row.total_chunks" @click="openChunks(row)">查看切块</el-button>
                <el-button v-if="canManage" link type="danger" @click="removeDocument(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="pagination-row">
            <el-pagination
              v-model:current-page="documentQuery.page"
              v-model:page-size="documentQuery.size"
              layout="total, prev, pager, next"
              :total="documentTotal"
              @current-change="loadDocuments()"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane name="tasks">
          <template #label>
            处理任务
            <el-badge v-if="meta?.active_tasks" :value="meta.active_tasks" class="task-badge" />
          </template>
          <el-table v-loading="taskLoading" :data="tasks" stripe>
            <el-table-column prop="id" label="任务" width="80">
              <template #default="{ row }">#{{ row.id }}</template>
            </el-table-column>
            <el-table-column label="类型" width="110">
              <template #default="{ row }">{{ row.task_type === 'rebuild' ? '重建索引' : '解析入库' }}</template>
            </el-table-column>
            <el-table-column prop="document_name" label="文档" min-width="210" show-overflow-tooltip />
            <el-table-column label="进度" min-width="210">
              <template #default="{ row }">
                <el-progress
                  :percentage="row.progress"
                  :status="row.status === 'failed' ? 'exception' : row.status === 'completed' ? 'success' : undefined"
                />
                <div class="pp-dim task-message">{{ row.error_message || row.message || '—' }}</div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="statusTone(row.status)" effect="light">{{ row.status_label }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="168">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>
          <div class="pagination-row">
            <el-pagination
              v-model:current-page="taskQuery.page"
              v-model:page-size="taskQuery.size"
              layout="total, prev, pager, next"
              :total="taskTotal"
              @current-change="loadTasks()"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>

    <el-dialog v-model="uploadVisible" title="上传知识文档" width="720px" :close-on-click-modal="!uploading">
      <el-alert
        type="info"
        :closable="false"
        :title="uploadHint"
        class="upload-hint"
      />
      <el-upload
        v-model:file-list="uploadFiles"
        drag
        multiple
        :auto-upload="false"
        :accept="acceptTypes"
        :limit="limits.max_batch_files"
        :disabled="uploading"
        :on-change="validateSelectedFile"
        :on-exceed="onUploadExceed"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">拖入文件，或 <em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">系统会按内容哈希识别重复文件，重复文件不会再次入库。</div>
        </template>
      </el-upload>

      <el-divider content-position="left">文本切块配置</el-divider>
      <el-form label-position="top">
        <el-row :gutter="16">
          <el-col :span="10">
            <el-form-item label="切块策略">
              <el-select v-model="uploadForm.strategy" style="width: 100%">
                <el-option label="按标题切分" value="heading" />
                <el-option label="按段落切分" value="paragraph" />
                <el-option label="固定长度切分" value="fixed" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="7">
            <el-form-item label="块大小（字符）">
              <el-input-number
                v-model="uploadForm.chunkSize"
                :min="limits.min_chunk_size"
                :max="limits.max_chunk_size"
                :step="50"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="7">
            <el-form-item label="重叠长度">
              <el-input-number
                v-model="uploadForm.chunkOverlap"
                :min="0"
                :max="Math.min(limits.max_chunk_overlap, uploadForm.chunkSize - 1)"
                :step="10"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <div class="strategy-note">{{ strategyNote }}</div>
      </el-form>

      <el-progress v-if="uploading || uploadProgress" :percentage="uploadProgress" :status="uploadProgress === 100 ? 'success' : undefined" />
      <div v-if="uploadResults.length" class="upload-results">
        <div v-for="(result, index) in uploadResults" :key="index" class="upload-result">
          <el-tag :type="result.accepted ? 'success' : result.duplicate ? 'warning' : 'danger'" size="small">
            {{ result.accepted ? '已排队' : result.duplicate ? '重复' : '失败' }}
          </el-tag>
          <span>{{ result.document?.original_name || result.file_name || `文件 ${index + 1}` }}：{{ result.message }}</span>
        </div>
      </div>
      <template #footer>
        <el-button :disabled="uploading" @click="uploadVisible = false">关闭</el-button>
        <el-button type="primary" :loading="uploading" @click="submitUpload">开始上传</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="chunkVisible" :title="chunkDocument ? `文本切块 · ${chunkDocument.original_name}` : '文本切块'" size="720px">
      <div v-loading="chunkLoading" class="chunk-list">
        <article v-for="chunk in chunks" :key="chunk.id" class="chunk-item">
          <div class="chunk-head">
            <strong>块 {{ chunk.chunk_index + 1 }}</strong>
            <span>{{ chunk.source_label }}</span>
          </div>
          <p>{{ chunk.content }}</p>
          <div class="pp-dim">字符位置 {{ chunk.char_start }}—{{ chunk.char_end }}</div>
        </article>
        <el-empty v-if="!chunkLoading && !chunks.length" description="该文档暂时没有可查看的切块" />
      </div>
      <div class="pagination-row">
        <el-pagination
          v-model:current-page="chunkPage"
          layout="total, prev, pager, next"
          :total="chunkTotal"
          :page-size="20"
          @current-change="loadChunks"
        />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { TabsPaneContext, UploadFile, UploadUserFile } from 'element-plus'
import { Refresh, RefreshRight, UploadFilled } from '@element-plus/icons-vue'
import { knowledgeApi } from '@/api/knowledge'
import { useUserStore } from '@/stores/user'
import { formatDateTime } from '@/utils/format'
import type {
  KnowledgeChunk,
  KnowledgeDocument,
  KnowledgeLimits,
  KnowledgeMeta,
  KnowledgeTask,
  KnowledgeUploadItem
} from '@/types'

const userStore = useUserStore()
const canManage = computed(() => userStore.isManager)
const activeTab = ref('documents')
const meta = ref<KnowledgeMeta | null>(null)
const documents = ref<KnowledgeDocument[]>([])
const documentTotal = ref(0)
const documentLoading = ref(false)
const tasks = ref<KnowledgeTask[]>([])
const taskTotal = ref(0)
const taskLoading = ref(false)
const uploadVisible = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadFiles = ref<UploadUserFile[]>([])
const uploadResults = ref<KnowledgeUploadItem[]>([])
const rebuilding = ref(false)
const chunkVisible = ref(false)
const chunkLoading = ref(false)
const chunkDocument = ref<KnowledgeDocument | null>(null)
const chunks = ref<KnowledgeChunk[]>([])
const chunkPage = ref(1)
const chunkTotal = ref(0)
let pollTimer: number | undefined

const defaultLimits: KnowledgeLimits = {
  max_file_mb: 20,
  max_batch_files: 5,
  allowed_extensions: ['pdf', 'docx', 'txt', 'md', 'markdown'],
  default_strategy: 'heading',
  default_chunk_size: 500,
  default_chunk_overlap: 50,
  min_chunk_size: 100,
  max_chunk_size: 4000,
  max_chunk_overlap: 1000
}
const limits = computed(() => meta.value?.limits || defaultLimits)
const documentQuery = reactive({ keyword: '', status: '', page: 1, size: 20 })
const taskQuery = reactive({ page: 1, size: 20 })
const uploadForm = reactive({
  strategy: defaultLimits.default_strategy,
  chunkSize: defaultLimits.default_chunk_size,
  chunkOverlap: defaultLimits.default_chunk_overlap
})

const acceptTypes = computed(() => limits.value.allowed_extensions.map((ext) => `.${ext}`).join(','))
const uploadHint = computed(
  () => `单文件不超过 ${limits.value.max_file_mb}MB，单次最多 ${limits.value.max_batch_files} 个；支持 ${limits.value.allowed_extensions.map((x) => x.toUpperCase()).join(' / ')}。`
)
const strategyNote = computed(() => ({
  heading: '优先按 Markdown/Word 标题或 PDF 中识别出的标题分段，超长小节再按块大小切分。',
  paragraph: '尽量在自然段边界结束文本块，长段落仍会按块大小拆分。',
  fixed: '严格按字符长度切分，适合结构不明显的纯文本。'
}[uploadForm.strategy]))

function statusTone(status: string) {
  return ({ pending: 'info', processing: 'warning', completed: 'success', failed: 'danger' } as const)[status as 'pending'] || 'info'
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

async function loadMeta() {
  meta.value = await knowledgeApi.meta()
}

async function loadDocuments(silent = false) {
  if (!silent) documentLoading.value = true
  try {
    const data = await knowledgeApi.documents(documentQuery)
    documents.value = data.items
    documentTotal.value = data.total
  } finally {
    if (!silent) documentLoading.value = false
  }
}

async function loadTasks(silent = false) {
  if (!silent) taskLoading.value = true
  try {
    const data = await knowledgeApi.tasks(taskQuery)
    tasks.value = data.items
    taskTotal.value = data.total
  } finally {
    if (!silent) taskLoading.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadMeta(), loadDocuments(), loadTasks()])
}

function onTabChange(tab: TabsPaneContext['paneName']) {
  if (tab === 'tasks') loadTasks()
}

function openUpload() {
  uploadFiles.value = []
  uploadResults.value = []
  uploadProgress.value = 0
  uploadForm.strategy = limits.value.default_strategy
  uploadForm.chunkSize = limits.value.default_chunk_size
  uploadForm.chunkOverlap = limits.value.default_chunk_overlap
  uploadVisible.value = true
}

function validateSelectedFile(file: UploadFile) {
  const raw = file.raw
  if (!raw) return
  const ext = raw.name.split('.').pop()?.toLowerCase() || ''
  if (!limits.value.allowed_extensions.includes(ext)) {
    uploadFiles.value = uploadFiles.value.filter((item) => item.uid !== file.uid)
    ElMessage.warning(`${raw.name} 格式不支持`)
    return
  }
  if (raw.size > limits.value.max_file_mb * 1024 * 1024) {
    uploadFiles.value = uploadFiles.value.filter((item) => item.uid !== file.uid)
    ElMessage.warning(`${raw.name} 超过 ${limits.value.max_file_mb}MB 上限`)
  }
}

function onUploadExceed() {
  ElMessage.warning(`单次最多选择 ${limits.value.max_batch_files} 个文件`)
}

async function submitUpload() {
  const files: File[] = uploadFiles.value.flatMap((item) => item.raw ? [item.raw as File] : [])
  if (!files.length) {
    ElMessage.warning('请先选择文件')
    return
  }
  if (uploadForm.chunkOverlap >= uploadForm.chunkSize) {
    ElMessage.warning('重叠长度必须小于块大小')
    return
  }
  uploading.value = true
  uploadProgress.value = 0
  uploadResults.value = []
  try {
    const result = await knowledgeApi.upload(files, {
      strategy: uploadForm.strategy,
      chunkSize: uploadForm.chunkSize,
      chunkOverlap: uploadForm.chunkOverlap,
      onProgress: (value) => { uploadProgress.value = value }
    })
    uploadResults.value = result.items
    ElMessage.success(result.accepted ? `${result.accepted} 个文件已进入处理队列` : '没有文件进入处理队列')
    uploadFiles.value = []
    await refreshAll()
    activeTab.value = 'tasks'
  } finally {
    uploading.value = false
  }
}

async function openChunks(row: KnowledgeDocument) {
  chunkDocument.value = row
  chunkPage.value = 1
  chunkVisible.value = true
  await loadChunks()
}

async function loadChunks() {
  if (!chunkDocument.value) return
  chunkLoading.value = true
  try {
    const data = await knowledgeApi.chunks(chunkDocument.value.id, chunkPage.value, 20)
    chunks.value = data.items
    chunkTotal.value = data.total
  } finally {
    chunkLoading.value = false
  }
}

async function removeDocument(row: KnowledgeDocument) {
  try {
    await ElMessageBox.confirm(
      `删除「${row.original_name}」会同时删除 ${row.total_chunks} 个文本块，并异步重建索引。此操作不可恢复。`,
      '删除知识文档',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  await knowledgeApi.deleteDocument(row.id)
  ElMessage.success('文档已删除，索引重建任务已排队')
  await refreshAll()
}

async function rebuildIndex() {
  try {
    await ElMessageBox.confirm('将根据当前全部内置知识和已完成文档重建向量索引，是否继续？', '重建索引', {
      type: 'warning', confirmButtonText: '开始重建', cancelButtonText: '取消'
    })
  } catch {
    return
  }
  rebuilding.value = true
  try {
    const task = await knowledgeApi.rebuild()
    ElMessage.success(`重建任务 #${task.id} 已提交`)
    activeTab.value = 'tasks'
    await refreshAll()
  } finally {
    rebuilding.value = false
  }
}

async function pollActiveTasks() {
  const hasActive = (meta.value?.active_tasks || 0) > 0 || tasks.value.some((task) =>
    task.status === 'pending' || task.status === 'processing'
  )
  if (!hasActive) return
  await Promise.all([loadMeta(), loadDocuments(true), loadTasks(true)])
}

onMounted(async () => {
  await refreshAll()
  pollTimer = window.setInterval(pollActiveTasks, 3000)
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<style scoped>
.pp-page-actions,
.toolbar,
.file-cell,
.chunk-head {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
}

.role-tip,
.content-card,
.upload-hint {
  margin-bottom: var(--pp-space-4);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--pp-space-4);
  margin-bottom: var(--pp-space-4);
}

.summary-card {
  padding: var(--pp-space-4);
  border: 1px solid var(--pp-border);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-card);
  box-shadow: var(--pp-shadow-xs);
}

.summary-card span,
.summary-card small {
  display: block;
  color: var(--pp-text-secondary);
}

.summary-card strong {
  display: block;
  margin: var(--pp-space-1) 0;
  color: var(--pp-primary);
  font-family: var(--pp-font-num);
  font-size: var(--pp-fs-2xl);
}

.summary-card--ai strong { color: var(--pp-ai); }
.summary-card--warning strong { color: var(--pp-warning); }
.summary-card--danger strong { color: var(--pp-danger); }

.toolbar {
  margin-bottom: var(--pp-space-4);
}

.file-cell {
  align-items: flex-start;
}

.file-name {
  margin-bottom: var(--pp-space-1);
  color: var(--pp-text-primary);
  font-weight: var(--pp-fw-medium);
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--pp-space-4);
}

.chunk-list,
.upload-results {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-3);
}

.chunk-item {
  padding: var(--pp-space-4);
  border: 1px solid var(--pp-border);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-sunken);
}

.chunk-head {
  justify-content: space-between;
  color: var(--pp-text-primary);
}

.chunk-item p {
  margin: var(--pp-space-3) 0;
  line-height: var(--pp-lh);
  white-space: pre-wrap;
}

.chunk-head span,
.strategy-note,
.task-message {
  color: var(--pp-text-secondary);
  font-size: var(--pp-fs-sm);
}

.task-message {
  margin-top: var(--pp-space-1);
}

.task-badge {
  margin-left: var(--pp-space-2);
}

.strategy-note {
  padding: var(--pp-space-3);
  border-radius: var(--pp-radius-sm);
  background: var(--pp-ai-bg);
}

.upload-results {
  max-height: 180px;
  margin-top: var(--pp-space-4);
  overflow: auto;
}

.upload-result {
  display: flex;
  align-items: flex-start;
  gap: var(--pp-space-2);
  color: var(--pp-text-regular);
}

@media (max-width: 1024px) {
  .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
