<!--
  AI 对话页：三角色共用（/user/chat、/staff/chat）。
  欢迎语、示例问题、输入框提示与可用工具全部由后端 capabilities 按角色下发；
  SSE 逐字输出思考链、工具调用胶囊与写操作二次确认卡，确认前不会落库。
-->

<template>
  <div class="pp-page chat-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">
          {{ capabilities?.role_profile || 'AI 洗护助手' }}
          <el-tag v-if="capabilities?.llm_available" size="small" class="pp-tag-ai" effect="light">
            {{ capabilities.model }}
          </el-tag>
          <el-tag v-else size="small" type="info" effect="light">规则模式</el-tag>
        </h2>
        <p class="pp-page-desc">
          多 Agent 协作：{{ capabilities?.capability_summary || '帮你查时段、看档案、约时间' }}；
          路由调度按问题分派给对应领域 Agent，所有写操作都会先跟你确认，再由门店业务系统执行。
        </p>
      </div>
      <div class="pp-page-actions">
        <el-button :icon="Plus" @click="newSession">新对话</el-button>
      </div>
    </div>

    <!-- 当前端可激活的 Agent（由后端 capabilities 按角色下发） -->
    <div v-if="capabilities?.agents?.length" class="agent-strip">
      <span class="agent-strip__label">当前可用</span>
      <el-tooltip
        v-for="agent in capabilities.agents"
        :key="agent.key"
        :content="agent.summary"
        placement="top"
      >
        <el-tag size="small" effect="plain" class="agent-chip">{{ agent.name }}</el-tag>
      </el-tooltip>
    </div>

    <div class="chat-shell">
      <!-- 会话列表 -->
      <aside class="chat-sessions">
        <div class="chat-sessions__title">对话记录</div>
        <PawLoading v-if="sessionLoading" variant="paw" />
        <EmptyState v-else-if="!sessions.length" illustration="paw" title="还没有对话" :size="64" />
        <div v-else class="chat-sessions__list">
          <div
            v-for="s in sessions"
            :key="s.id"
            class="session-item"
            :class="{ 'is-active': s.id === sessionId }"
            @click="switchSession(s.id)"
          >
            <el-icon :size="14"><ChatDotRound /></el-icon>
            <div class="session-item__body">
              <div class="session-item__title">{{ s.title }}</div>
              <div class="session-item__preview">{{ s.preview || '暂无消息' }}</div>
            </div>
            <el-icon class="session-item__del" :size="13" @click.stop="removeSession(s.id)"><Delete /></el-icon>
          </div>
        </div>
      </aside>

      <!-- 对话主区 -->
      <section class="chat-main">
        <div ref="scrollRef" class="chat-stream">
          <!-- 欢迎 / 示例 -->
          <div v-if="!bubbles.length" class="chat-welcome">
            <PetIllustration :type="welcomeIllustration" :size="120" class="pp-float" />
            <h3 class="chat-welcome__title">{{ welcomeTitle }}</h3>
            <p class="chat-welcome__desc">{{ welcomeDesc }}</p>
            <div class="chat-welcome__examples">
              <button
                v-for="ex in capabilities?.examples || defaultExamples"
                :key="ex"
                type="button"
                class="example-chip"
                @click="input = ex"
              >
                {{ ex }}
              </button>
            </div>
          </div>

          <div v-for="bubble in bubbles" :key="bubble.id" class="bubble-row" :class="`bubble-row--${bubble.role}`">
            <div v-if="bubble.role === 'assistant'" class="bubble-avatar">
              <el-icon :size="16"><MagicStick /></el-icon>
            </div>

            <div class="bubble-col">
              <!-- 思考过程 -->
              <div v-if="bubble.thoughts?.length" class="bubble-thoughts">
                <span v-for="(t, i) in bubble.thoughts" :key="i" class="thought-chip">
                  <el-icon :size="11"><Loading /></el-icon>{{ t }}
                </span>
              </div>

              <!-- 工具调用 -->
              <div v-if="bubble.tool" class="bubble-tool">
                <el-icon :size="12"><Connection /></el-icon>
                调用工具：{{ TOOL_LABEL[bubble.tool] || bubble.tool }}
              </div>

              <!-- 气泡 -->
              <div class="bubble" :class="{ 'bubble--error': bubble.error }">
                <span class="bubble__text">{{ bubble.content }}</span>
                <span v-if="bubble.streaming" class="pp-caret" />
              </div>

              <!-- 可选回答：像「看豆豆的实景」这种，点一下就行，不用自己组织句子 -->
              <div v-if="bubble.choices?.length" class="bubble-choices">
                <button
                  v-for="choice in bubble.choices"
                  :key="choice"
                  type="button"
                  class="choice-chip"
                  :disabled="busy"
                  @click="sendText(choice)"
                >{{ choice }}</button>
              </div>

              <!-- 检索依据：答案由模型基于这些片段生成，默认收起，需要时展开核对 -->
              <details v-if="bubble.refs?.length" class="refs">
                <summary class="refs__summary">
                  检索到的片段（{{ bubble.refs.length }}）
                  <span class="refs__tip">点击展开核对原文</span>
                </summary>
                <ol class="refs__list">
                  <li v-for="(ref, i) in bubble.refs" :key="i" class="refs__item">
                    <div class="refs__title">
                      {{ ref.title }}<template v-if="ref.section"> · {{ ref.section }}</template>
                    </div>
                    <p class="refs__body">{{ ref.content }}</p>
                    <div class="refs__meta">
                      <span v-if="ref.matched">{{ ref.matched }}</span>
                      <span>来源：{{ ref.source }}</span>
                    </div>
                  </li>
                </ol>
              </details>

              <!-- 写操作二次确认 -->
              <div v-if="bubble.confirm" class="confirm-card">
                <div class="confirm-card__head">
                  <el-icon :size="14"><WarnTriangleFilled /></el-icon>
                  需要你确认后才会提交
                </div>
                <div class="confirm-card__tool">{{ TOOL_LABEL[bubble.confirm.tool] || bubble.confirm.tool }}</div>
                <!-- 复述关键字段：写操作确认前必须让用户看清「要提交什么」 -->
                <div v-if="bubble.confirm.prompt" class="confirm-card__body">{{ bubble.confirm.prompt }}</div>
                <div class="confirm-card__actions">
                  <el-button size="small" type="primary" :disabled="busy" @click="sendText('确认')">确认提交</el-button>
                  <el-button size="small" :disabled="busy" @click="sendText('取消')">放弃</el-button>
                </div>
              </div>

              <div v-if="bubble.intent || bubble.agent" class="bubble-intent">
                <span v-if="bubble.agent" class="bubble-agent">{{ bubble.agent.name }}</span>
                <span v-if="bubble.intent">
                  意图识别：{{ INTENT_LABEL[bubble.intent] || bubble.intent }}
                </span>
              </div>
            </div>

            <div v-if="bubble.role === 'user'" class="bubble-avatar bubble-avatar--user">
              {{ userStore.displayName.slice(0, 1) }}
            </div>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="chat-input">
          <el-input
            v-model="input"
            type="textarea"
            :rows="2"
            resize="none"
            maxlength="500"
            :placeholder="inputPlaceholder"
            @keydown.enter.exact.prevent="send"
          />
          <div class="chat-input__actions">
            <span class="chat-input__hint">
              {{ busy ? '助手正在思考…' : `${input.length}/500` }}
            </span>
            <el-button v-if="busy" size="small" @click="abort">停止</el-button>
            <el-button type="primary" :icon="Promotion" :disabled="!input.trim() || busy" @click="send">
              发送
            </el-button>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatDotRound,
  Connection,
  Delete,
  Loading,
  MagicStick,
  Plus,
  Promotion,
  WarnTriangleFilled
} from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import PetIllustration from '@/components/PetIllustration.vue'
import { chatApi, streamChat } from '@/api/chat'
import { useUserStore } from '@/stores/user'
import { INTENT_LABEL, TOOL_LABEL } from '@/utils/dict'
import type { AgentEvent, ChatBubble, ChatCapabilities, ChatSessionItem } from '@/types'

const userStore = useUserStore()
const router = useRouter()

const defaultExamples = [
  '明天还有哪些时段可以预约？',
  '帮我看看豆豆的档案',
  '我最近的预约到哪一步了？'
]

/** 按角色定制的欢迎文案（角色的工具画像由后端 capabilities 下发） */
const WELCOME: Record<string, { title: string; desc: string; art: 'cat' | 'dog' | 'paw' }> = {
  customer: {
    title: '你好呀，我是洗护小助手 🐾',
    desc: '我可以帮你查可预约时段、读取宠物档案、查看预约进度与洗护风险，也可以直接帮你预约 —— 但提交前一定会先跟你确认。',
    art: 'cat'
  },
  staff: {
    title: '运营助理就位，先看今天要处理什么？',
    desc: '我可以帮你查看今日排期与待办、按手机号或宠物名查客户档案与洗护历史、推进订单状态、复核风险报告，也可以代客下单 —— 所有写操作都会先跟你确认。',
    art: 'dog'
  },
  manager: {
    title: '经营助理就位，想先看哪块数据？',
    desc: '我可以帮你查经营概览、时段饱和度、流失预警、员工业绩与审计日志，也可以调整门店配置与账号状态 —— 改配置必须先确认，且会做范围校验。',
    art: 'paw'
  }
}

const roleKey = computed(() => userStore.role)
const PLACEHOLDER: Record<string, string> = {
  customer: '说说你的需求，例如：帮我给豆豆预约明天 15:00 洗澡（Enter 发送，Shift + Enter 换行）',
  staff: '试试：我今天有什么要处理的？ / 帮我查客户 138xxxx 的档案 / PGxxxx 这单确认（Enter 发送）',
  manager: '试试：近 30 天经营情况怎么样？ / 这周哪个时段还能加单？ / 把流失预警天数改成 60（Enter 发送）'
}
const inputPlaceholder = computed(() => PLACEHOLDER[roleKey.value] || PLACEHOLDER.customer)
const welcomeTitle = computed(() => WELCOME[roleKey.value]?.title || WELCOME.customer.title)
const welcomeDesc = computed(() => WELCOME[roleKey.value]?.desc || WELCOME.customer.desc)
const welcomeIllustration = computed(() => WELCOME[roleKey.value]?.art || 'cat')

const capabilities = ref<ChatCapabilities | null>(null)
const sessions = ref<ChatSessionItem[]>([])
const sessionLoading = ref(false)
const sessionId = ref<number | null>(null)
const bubbles = ref<ChatBubble[]>([])
const input = ref('')
const busy = ref(false)
const scrollRef = ref<HTMLDivElement>()
let controller: AbortController | null = null
let seq = 0

function uid() {
  seq += 1
  return `b${Date.now()}-${seq}`
}

async function scrollToBottom() {
  await nextTick()
  const el = scrollRef.value
  if (el) el.scrollTop = el.scrollHeight
}

async function loadSessions() {
  sessionLoading.value = true
  try {
    sessions.value = await chatApi.sessions()
  } finally {
    sessionLoading.value = false
  }
}

async function switchSession(id: number) {
  if (busy.value) {
    ElMessage.warning('助手正在回复，请稍候切换')
    return
  }
  sessionId.value = id
  const res = await chatApi.messages(id)
  bubbles.value = res.messages.map((m) => ({
    id: uid(),
    role: m.role,
    content: m.content,
    intent: m.intent || undefined,
    tool: m.tool_name || undefined,
    refs: m.refs || undefined
  }))
  await scrollToBottom()
}

async function newSession() {
  if (busy.value) return
  const res = await chatApi.createSession('新的对话')
  sessionId.value = res.id
  bubbles.value = []
  await loadSessions()
}

async function removeSession(id: number) {
  try {
    await ElMessageBox.confirm('确认删除这条对话记录吗？', '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '再想想',
      type: 'warning'
    })
  } catch {
    return
  }
  await chatApi.removeSession(id)
  if (sessionId.value === id) {
    sessionId.value = null
    bubbles.value = []
  }
  await loadSessions()
  ElMessage.success('对话已删除')
}

function send() {
  const text = input.value.trim()
  if (!text) return
  input.value = ''
  void sendText(text)
}

async function sendText(text: string) {
  if (busy.value) return

  bubbles.value.push({ id: uid(), role: 'user', content: text })
  const assistant: ChatBubble = { id: uid(), role: 'assistant', content: '', streaming: true, thoughts: [] }
  bubbles.value.push(assistant)
  busy.value = true
  await scrollToBottom()

  controller = new AbortController()
  try {
    await streamChat({
      content: text,
      sessionId: sessionId.value,
      signal: controller.signal,
      onEvent: (event: AgentEvent) => handleEvent(event, assistant)
    })
  } catch (err) {
    const message = err instanceof Error ? err.message : '连接中断'
    if (message.includes('abort')) {
      assistant.content = assistant.content || '已停止生成。'
    } else {
      assistant.error = message
      if (!assistant.content) assistant.content = `抱歉，助手暂时连不上：${message}`
    }
  } finally {
    assistant.streaming = false
    busy.value = false
    controller = null
    await loadSessions()
    await scrollToBottom()
  }
}

function handleEvent(event: AgentEvent, target: ChatBubble) {
  switch (event.type) {
    case 'meta':
      if (event.session_id) sessionId.value = event.session_id
      break
    case 'thought':
      target.thoughts = [...(target.thoughts || []), event.content]
      break
    case 'intent':
      target.intent = event.intent
      if (event.agent) target.agent = event.agent
      break
    case 'action':
      target.tool = event.tool
      break
    case 'observation':
      if (event.ok === false && event.error) target.error = event.error
      break
    case 'confirm':
      target.confirm = { tool: event.tool, args: event.args, prompt: event.prompt }
      break
    case 'navigate':
      // 服务端建议跳转：只做导航（例如「看豆豆的实景」→ 宠物实景页并自动打开该单画面）
      if (event.path) {
        void router.push(event.path)
        ElMessage.success(`已为你打开「${event.label || '页面'}」`)
      }
      break
    case 'choices':
      // 多只宠物时给可点选项，避免用户自己打字说不清
      target.choices = event.items
      break
    case 'camera_error':
      // 摄像头没开 / 停用 / 离线：不跳转（跳过去也是空的），小窗说清原因
      ElMessageBox.alert(event.reason || '摄像头暂时不可用', `${event.pet_name || '宠物'}的实景看不了`, {
        type: 'warning',
        confirmButtonText: '知道了'
      }).catch(() => undefined)
      break
    case 'answer':
      target.content += event.delta
      void scrollToBottom()
      break
    case 'refs':
      // 知识问答的检索依据：挂在气泡下方，折叠展示
      target.refs = event.items
      break
    case 'error':
      target.error = event.message
      target.content = target.content || event.message
      break
    default:
      break
  }
}

function abort() {
  controller?.abort()
}

onMounted(async () => {
  try {
    capabilities.value = await chatApi.capabilities()
  } catch {
    capabilities.value = null
  }
  await loadSessions()
  // 若有历史会话，载入最近一条
  if (sessions.value.length) await switchSession(sessions.value[0].id)
})

onUnmounted(() => controller?.abort())
</script>

<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.chat-shell {
  display: grid;
  grid-template-columns: 268px 1fr;
  gap: var(--pp-space-4);
  flex: 1;
  min-height: 0;
}

/* ---------------- 会话列表 ---------------- */
.chat-sessions {
  background: var(--pp-bg-card);
  border: 1px solid var(--pp-border-light);
  border-radius: var(--pp-radius-lg);
  box-shadow: var(--pp-shadow-xs);
  padding: var(--pp-space-4);
  overflow-y: auto;
}

.chat-sessions__title {
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-secondary);
  margin-bottom: var(--pp-space-3);
}

.chat-sessions__list {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-2);
}

.session-item {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  padding: var(--pp-space-3);
  border-radius: var(--pp-radius-md);
  cursor: pointer;
  transition: all var(--pp-dur-fast) var(--pp-ease);
  color: var(--pp-text-secondary);
}

.session-item:hover {
  background: var(--pp-bg-cream);
}

.session-item.is-active {
  background: var(--pp-primary-lighter);
  color: var(--pp-primary-dark);
}

.session-item__body {
  flex: 1;
  min-width: 0;
}

.session-item__title {
  font-size: var(--pp-fs-sm);
  font-weight: var(--pp-fw-medium);
  color: var(--pp-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-item__preview {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-placeholder);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-item__del {
  opacity: 0;
  transition: opacity var(--pp-dur-fast) var(--pp-ease);
}

.session-item:hover .session-item__del {
  opacity: 1;
}

/* ---------------- 对话主区 ---------------- */
.chat-main {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--pp-bg-card);
  border: 1px solid var(--pp-border-light);
  border-radius: var(--pp-radius-lg);
  box-shadow: var(--pp-shadow-sm);
  overflow: hidden;
}

.chat-stream {
  flex: 1;
  overflow-y: auto;
  padding: var(--pp-space-5);
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-4);
}

/* 欢迎区 */
.chat-welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: var(--pp-space-6) var(--pp-space-4);
}

.chat-welcome__title {
  margin-top: var(--pp-space-3);
  font-size: var(--pp-fs-lg);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.chat-welcome__desc {
  margin: var(--pp-space-2) 0 var(--pp-space-5);
  max-width: 520px;
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
  line-height: 1.8;
}

.chat-welcome__examples {
  display: flex;
  flex-wrap: wrap;
  gap: var(--pp-space-2);
  justify-content: center;
}

.example-chip {
  padding: 8px 16px;
  border-radius: var(--pp-radius-pill);
  border: 1px solid var(--pp-border-light);
  background: var(--pp-bg-sunken);
  color: var(--pp-text-regular);
  font-size: var(--pp-fs-sm);
  font-family: inherit;
  cursor: pointer;
  transition: all var(--pp-dur-fast) var(--pp-ease);
}

.example-chip:hover {
  background: var(--pp-primary-lighter);
  border-color: var(--pp-primary-light);
  color: var(--pp-primary-dark);
  transform: translateY(-1px);
}

/* 气泡行 */
.bubble-row {
  display: flex;
  gap: var(--pp-space-3);
  align-items: flex-start;
}

.bubble-row--user {
  justify-content: flex-end;
}

.bubble-avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--pp-ai-bg), #e4dbf6);
  color: #7361a4;
}

.bubble-avatar--user {
  background: linear-gradient(135deg, var(--pp-primary-light), var(--pp-primary));
  color: #fff;
  font-weight: var(--pp-fw-semibold);
  font-size: var(--pp-fs-sm);
}

.bubble-col {
  max-width: 74%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.bubble-row--user .bubble-col {
  align-items: flex-end;
}

.bubble {
  padding: var(--pp-space-3) var(--pp-space-4);
  border-radius: var(--pp-radius-lg);
  background: var(--pp-bg-sunken);
  color: var(--pp-text-regular);
  font-size: var(--pp-fs-base);
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
  box-shadow: var(--pp-shadow-xs);
}

.bubble-row--user .bubble {
  background: linear-gradient(135deg, var(--pp-primary) 0%, #6fa9dc 100%);
  color: #fff;
  border-radius: var(--pp-radius-lg) var(--pp-radius-lg) var(--pp-radius-xs) var(--pp-radius-lg);
}

.bubble-row--assistant .bubble {
  border-radius: var(--pp-radius-lg) var(--pp-radius-lg) var(--pp-radius-lg) var(--pp-radius-xs);
}

.bubble--error {
  background: var(--pp-danger-bg);
  color: #b8503a;
}

.bubble__text {
  white-space: pre-wrap;
}

/* 思考与工具 */
.bubble-thoughts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.thought-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: var(--pp-radius-pill);
  background: var(--pp-ai-bg);
  color: #7361a4;
  font-size: var(--pp-fs-xs);
}

.thought-chip .el-icon {
  animation: pp-spin 1.2s linear infinite;
}

@keyframes pp-spin {
  to {
    transform: rotate(360deg);
  }
}

.bubble-tool {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: var(--pp-radius-pill);
  background: var(--pp-info-bg);
  color: #4e7d9f;
  font-size: var(--pp-fs-xs);
  align-self: flex-start;
}

/* 可选回答 chip：点了直接发出去 */
.bubble-choices {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 2px;
}

.choice-chip {
  padding: 5px 14px;
  border: 1px solid var(--pp-border-light);
  border-radius: var(--pp-radius-pill);
  background: var(--pp-bg-card);
  color: var(--pp-primary-dark);
  font-size: var(--pp-fs-sm);
  font-family: inherit;
  cursor: pointer;
  transition: all var(--pp-dur-fast) var(--pp-ease);
}

.choice-chip:hover:not(:disabled) {
  border-color: var(--pp-primary);
  background: var(--pp-primary-lighter);
  box-shadow: var(--pp-shadow-sm);
}

.choice-chip:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.bubble-intent {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-placeholder);
  align-self: flex-start;
}

/* 本轮接手的领域 Agent：让用户知道是哪个 Agent 在答，而不是一个黑盒 */
.bubble-agent {
  padding: 0 var(--pp-space-2);
  border-radius: var(--pp-radius-pill);
  background: var(--pp-primary-lighter);
  color: var(--pp-primary);
  font-weight: 500;
}

.agent-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--pp-space-2);
  margin-bottom: var(--pp-space-4);
}

.agent-strip__label {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-secondary);
}

.agent-chip {
  cursor: default;
}

/* 检索依据（可折叠）：默认收起，展开后能看到答案依据的原文片段 */
.refs {
  align-self: stretch;
  border: 1px solid var(--pp-border-color);
  border-radius: var(--pp-radius-md);
  background: var(--pp-bg-page);
  overflow: hidden;
}

.refs__summary {
  padding: 6px 12px;
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-regular);
  cursor: pointer;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 8px;
  user-select: none;
}

.refs__summary::-webkit-details-marker {
  display: none;
}

.refs__summary::before {
  content: '▸';
  color: var(--pp-text-placeholder);
  transition: transform 0.2s;
}

.refs[open] .refs__summary::before {
  transform: rotate(90deg);
}

.refs__tip {
  color: var(--pp-text-placeholder);
}

.refs__list {
  margin: 0;
  padding: 0 12px 10px 28px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.refs__item {
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-regular);
  line-height: 1.7;
}

.refs__title {
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.refs__body {
  margin: 2px 0 0;
}

.refs__meta {
  margin-top: 2px;
  display: flex;
  gap: 10px;
  color: var(--pp-text-placeholder);
}

/* 二次确认卡 */
.confirm-card {
  border: 1.5px dashed var(--pp-warning);
  background: var(--pp-warning-bg);
  border-radius: var(--pp-radius-md);
  padding: var(--pp-space-3) var(--pp-space-4);
  min-width: 280px;
}

.confirm-card__head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--pp-fs-sm);
  font-weight: var(--pp-fw-semibold);
  color: #a8681f;
}

.confirm-card__tool {
  margin: var(--pp-space-1) 0 var(--pp-space-3);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-regular);
}

/* 复述内容：保留后端 prompt 里的换行，让「名字 / 性别 / 金额」逐行可读 */
.confirm-card__body {
  margin-bottom: var(--pp-space-3);
  padding: var(--pp-space-2) var(--pp-space-3);
  border-radius: var(--pp-radius-sm);
  background: rgba(255, 255, 255, 0.6);
  font-size: var(--pp-fs-sm);
  line-height: 1.7;
  color: var(--pp-text-primary);
  white-space: pre-line;
}

.confirm-card__actions {
  display: flex;
  gap: var(--pp-space-2);
}

/* 输入区 */
.chat-input {
  border-top: 1px solid var(--pp-border-light);
  padding: var(--pp-space-4);
  background: #fffdfa;
}

.chat-input__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--pp-space-3);
  margin-top: var(--pp-space-2);
}

.chat-input__hint {
  margin-right: auto;
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-placeholder);
}

@media (max-width: 1100px) {
  .chat-shell {
    grid-template-columns: 1fr;
  }
  .chat-sessions {
    display: none;
  }
}
</style>
