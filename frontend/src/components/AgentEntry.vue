<!--
  AI 入口卡（三端首页复用）：形象 + 「AI 在线」脉冲标签 + 一行能力说明 + 整卡跳转。
  文案由父组件按角色传入，组件本身不判断角色、不发请求。
-->
<template>
  <router-link class="agent-entry" :to="to">
    <div class="agent-entry__body">
      <div class="agent-entry__head">
        <span class="agent-entry__name">{{ title }}</span>
        <span class="agent-entry__online">
          <i class="agent-entry__dot" />
          AI 在线
        </span>
      </div>
      <p class="agent-entry__desc">{{ desc }}</p>
      <span class="agent-entry__cta">
        点我开始对话
        <el-icon :size="12"><ArrowRight /></el-icon>
      </span>
    </div>
    <img class="agent-entry__mascot" :src="mascot" :alt="`${title}形象`" />
  </router-link>
</template>

<script setup lang="ts">
import { ArrowRight } from '@element-plus/icons-vue'
import mascot from '@/assets/agent-mascot.png'

withDefaults(
  defineProps<{
    /** 对话页路由，点击整块卡片即进入 */
    to: string
    /** 角色化的助手名称，如「AI 洗护助手」「运营助理」 */
    title?: string
    /** 一句话能力说明 */
    desc?: string
  }>(),
  {
    title: 'AI 助手',
    desc: '有问题随时问我'
  }
)
</script>

<style scoped>
/* 首页欢迎区右侧的 Agent 聊天入口：形象 + 说明，整块可点击 */
.agent-entry {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--pp-space-3);
  /* 底部多留一点空间，让形象与卡片下缘之间透气（不然爪子会贴边） */
  padding: var(--pp-space-3) var(--pp-space-4) 18px;
  border-radius: var(--pp-radius-lg);
  background: rgba(255, 255, 255, 0.74);
  border: 1px solid rgba(155, 138, 196, 0.26);
  box-shadow: var(--pp-shadow-sm);
  backdrop-filter: blur(6px);
  text-decoration: none;
  cursor: pointer;
  transition: all var(--pp-dur) var(--pp-ease);
}

.agent-entry:hover {
  transform: translateY(-2px);
  background: rgba(255, 255, 255, 0.92);
  border-color: var(--pp-ai);
  box-shadow: var(--pp-shadow-md);
}

.agent-entry__body {
  min-width: 0;
}

.agent-entry__head {
  display: flex;
  align-items: center;
  gap: var(--pp-space-2);
}

.agent-entry__name {
  font-size: var(--pp-fs-md);
  font-weight: var(--pp-fw-semibold);
  color: var(--pp-text-primary);
}

.agent-entry__online {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border-radius: var(--pp-radius-pill);
  background: var(--pp-ai-bg);
  color: var(--pp-ai);
  font-size: var(--pp-fs-xs);
  line-height: 18px;
}

.agent-entry__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--pp-ai);
  animation: agent-pulse 2.2s var(--pp-ease) infinite;
}

.agent-entry__desc {
  margin: var(--pp-space-1) 0 var(--pp-space-2);
  max-width: 200px;
  font-size: var(--pp-fs-xs);
  color: var(--pp-text-regular);
  line-height: 1.6;
}

.agent-entry__cta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--pp-fs-xs);
  color: var(--pp-ai);
}

.agent-entry__mascot {
  flex: none;
  height: 104px;
  width: auto;
  animation: pp-float 4.2s var(--pp-ease) infinite;
  transition: transform var(--pp-dur) var(--pp-ease-bounce);
}

.agent-entry:hover .agent-entry__mascot {
  transform: scale(1.04);
}

@keyframes agent-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.45;
    transform: scale(0.82);
  }
}

/* 窄屏：保留入口（不隐藏），仅收小形象与内边距 */
@media (max-width: 1100px) {
  .agent-entry__mascot {
    height: 84px;
  }

  .agent-entry__desc {
    max-width: 170px;
  }
}

@media (max-width: 768px) {
  .agent-entry {
    width: 100%;
    justify-content: space-between;
  }

  .agent-entry__desc {
    max-width: none;
  }
}
</style>
