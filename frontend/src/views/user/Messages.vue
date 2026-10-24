<!--
  消息中心（宠主）：消息列表、未读筛选、单条与全部已读。
  数据来源：GET /messages；未读数同步到 store 以驱动菜单角标。
-->

<template>
  <div class="pp-page">
    <div class="pp-page-header">
      <div>
        <h2 class="pp-page-title">消息中心</h2>
        <p class="pp-page-desc">预约状态变更、洗护风险提醒与门店通知都会汇总在这里。</p>
      </div>
      <div class="pp-page-actions">
        <el-switch v-model="onlyUnread" active-text="仅看未读" @change="reload" />
        <el-button :icon="Select" :disabled="!userStore.unread" @click="readAll">全部已读</el-button>
      </div>
    </div>

    <section class="pp-card">
      <PawLoading v-if="loading" variant="paw" text="加载消息中…" />
      <EmptyState
        v-else-if="!list.length"
        illustration="cat"
        title="暂时没有新消息"
        description="预约状态变化时我们会第一时间通知你。"
      />

      <div v-else class="msg-list">
        <transition-group name="pp-slide-down">
          <article
            v-for="item in list"
            :key="item.id"
            class="msg-item"
            :class="{ 'is-unread': item.is_read === 0 }"
          >
            <span class="msg-item__bar" />
            <div class="msg-item__body">
              <div class="msg-item__head">
                <span class="msg-item__title">{{ item.title }}</span>
                <el-tag size="small" type="info" effect="light">
                  {{ item.msg_type_label || MESSAGE_TYPE_LABEL[item.msg_type] || item.msg_type }}
                </el-tag>
                <span v-if="item.is_read === 0" class="msg-item__dot">未读</span>
              </div>
              <p class="msg-item__content">{{ item.content }}</p>
              <div class="msg-item__time">{{ relativeTime(item.created_at) }}</div>
            </div>
            <div class="msg-item__actions">
              <el-button v-if="item.is_read === 0" size="small" @click="markRead(item)">标记已读</el-button>
              <el-button size="small" type="danger" plain @click="remove(item)">删除</el-button>
            </div>
          </article>
        </transition-group>
      </div>

      <div v-if="total > size" class="pp-pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @size-change="load"
          @current-change="load"
        />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Select } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import PawLoading from '@/components/PawLoading.vue'
import { messageApi } from '@/api/message'
import { useUserStore } from '@/stores/user'
import { MESSAGE_TYPE_LABEL } from '@/utils/dict'
import { relativeTime } from '@/utils/format'
import type { MessageItem } from '@/types'

const userStore = useUserStore()

const loading = ref(true)
const list = ref<MessageItem[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const onlyUnread = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await messageApi.list({ page: page.value, size: size.value, only_unread: onlyUnread.value })
    list.value = res.items
    total.value = res.total
    await userStore.refreshUnread()
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

async function markRead(item: MessageItem) {
  await messageApi.read(item.id)
  load()
}

async function readAll() {
  await messageApi.readAll()
  ElMessage.success('已全部标记为已读')
  load()
}

async function remove(item: MessageItem) {
  try {
    await ElMessageBox.confirm('确认删除这条消息吗？删除后不再显示。', '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '再想想',
      type: 'warning'
    })
  } catch {
    return
  }
  await messageApi.remove(item.id)
  ElMessage.success('消息已删除')
  load()
}

onMounted(load)
</script>

<style scoped>
.msg-list {
  display: flex;
  flex-direction: column;
  gap: var(--pp-space-3);
}

.msg-item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: var(--pp-space-4);
  padding: var(--pp-space-4) var(--pp-space-4) var(--pp-space-4) var(--pp-space-5);
  border-radius: var(--pp-radius-lg);
  border: 1px solid var(--pp-border-light);
  background: var(--pp-bg-card);
  overflow: hidden;
  transition: all var(--pp-dur) var(--pp-ease);
}

.msg-item:hover {
  box-shadow: var(--pp-shadow-sm);
}

.msg-item.is-unread {
  background: linear-gradient(90deg, var(--pp-primary-lighter) 0%, #ffffff 42%);
  border-color: #dbeafa;
}

.msg-item__bar {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: transparent;
}

.msg-item.is-unread .msg-item__bar {
  background: linear-gradient(180deg, var(--pp-primary-light), var(--pp-primary));
}

.msg-item__body {
  flex: 1;
  min-width: 0;
}

.msg-item__head {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
  flex-wrap: wrap;
}

.msg-item__title {
  font-size: var(--pp-fs-base);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.msg-item__dot {
  font-size: var(--pp-fs-xs);
  color: var(--pp-danger);
  font-weight: var(--pp-fw-medium);
}

.msg-item__content {
  margin: var(--pp-space-2) 0 0;
  font-size: var(--pp-fs-sm);
  color: var(--pp-text-regular);
  line-height: 1.7;
}

.msg-item__time {
  margin-top: var(--pp-space-2);
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-placeholder);
  font-family: var(--pp-font-num);
}

.msg-item__actions {
  display: flex;
  gap: var(--pp-space-2);
  flex: none;
}
</style>
