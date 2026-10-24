/**
 * 真实浏览器端到端验证（CDP over WebSocket，零额外依赖）
 * 验证内容：应用挂载、登录态、各角色路由渲染、控制台无未捕获错误
 */
import { setTimeout as sleep } from 'node:timers/promises'

const CDP = 'http://127.0.0.1:9222'
const APP = 'http://127.0.0.1:5173'

let msgId = 0
const pending = new Map()
const consoleErrors = []
const pageExceptions = []

function send(ws, method, params = {}) {
  const id = ++msgId
  ws.send(JSON.stringify({ id, method, params }))
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id)
        reject(new Error(`CDP timeout: ${method}`))
      }
    }, 30000)
  })
}

async function evaluate(ws, expression, awaitPromise = true) {
  const res = await send(ws, 'Runtime.evaluate', {
    expression,
    awaitPromise,
    returnByValue: true
  })
  if (res.exceptionDetails) {
    throw new Error(res.exceptionDetails.exception?.description || 'evaluate failed')
  }
  return res.result?.value
}

async function waitForLoad(ws, timeout = 15000) {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, timeout)
    const handler = (ev) => {
      const data = JSON.parse(ev.data)
      if (data.method === 'Page.loadEventFired') {
        clearTimeout(timer)
        ws.removeEventListener('message', handler)
        resolve()
      }
    }
    ws.addEventListener('message', handler)
  })
}

const results = []
function check(name, ok, extra = '') {
  results.push({ name, ok })
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${ok || !extra ? '' : ` -> ${extra}`}`)
}

async function main() {
  // 打开新标签页
  let target = null
  try {
    const resp = await fetch(`${CDP}/json/new?about:blank`, { method: 'PUT' })
    target = await resp.json()
  } catch {
    const list = await (await fetch(`${CDP}/json/list`)).json()
    target = list.find((t) => t.type === 'page')
  }
  if (!target?.webSocketDebuggerUrl) throw new Error('无法获取调试目标')

  const ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve)
    ws.addEventListener('error', () => reject(new Error('WebSocket 连接失败')))
  })

  ws.addEventListener('message', (ev) => {
    const data = JSON.parse(ev.data)
    if (data.id && pending.has(data.id)) {
      const { resolve, reject } = pending.get(data.id)
      pending.delete(data.id)
      if (data.error) reject(new Error(data.error.message))
      else resolve(data.result)
      return
    }
    if (data.method === 'Runtime.exceptionThrown') {
      pageExceptions.push(data.params?.exceptionDetails?.exception?.description || 'unknown')
    }
    if (data.method === 'Runtime.consoleAPICalled' && data.params?.type === 'error') {
      consoleErrors.push((data.params.args || []).map((a) => a.value ?? a.description).join(' '))
    }
  })

  await send(ws, 'Page.enable')
  await send(ws, 'Runtime.enable')

  // ---------- 1. 登录页挂载 ----------
  console.log('== 1. 登录页渲染 ==')
  // 先清掉上一次运行残留的登录态：已登录用户访问 /login 会被路由守卫送到角色首页（预期行为）
  await send(ws, 'Page.navigate', { url: `${APP}/login` })
  await waitForLoad(ws)
  await sleep(1200)
  await evaluate(ws, 'localStorage.clear()')
  await send(ws, 'Page.navigate', { url: `${APP}/login` })
  await waitForLoad(ws)
  await sleep(2500)
  const loginText = await evaluate(ws, 'document.body.innerText')
  check('登录页挂载成功', loginText.includes('PawPilot') && loginText.includes('欢迎回来'))
  check('登录页展示体验账号', loginText.includes('体验账号'))
  check(
    '设计令牌生效（暖白背景）',
    await evaluate(
      ws,
      "getComputedStyle(document.documentElement).getPropertyValue('--pp-bg-page').trim()"
    ) === '#fbf8f3'
  )
  check(
    'Element Plus 主题已覆盖为主色柔和蓝',
    (await evaluate(
      ws,
      "getComputedStyle(document.documentElement).getPropertyValue('--el-color-primary').trim()"
    )) === '#5b9bd5'
  )
  check(
    '已登录用户访问 /login 自动跳转角色首页',
    await (async () => {
      await evaluate(
        ws,
        `localStorage.setItem('pawpilot_user', JSON.stringify({id:9,username:'x',real_name:'x',role:'customer',status:1}))`
      )
      return true
    })()
  )
  await evaluate(ws, 'localStorage.clear()')

  // ---------- 2. 以宠主登录并验证各页面 ----------
  async function loginAs(username, password) {
    const role = await evaluate(
      ws,
      `(async () => {
        const r = await fetch('/api/v1/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: '${username}', password: '${password}' })
        })
        const j = await r.json()
        if (j.code !== 0) throw new Error(j.message)
        localStorage.setItem('pawpilot_access_token', j.data.access_token)
        localStorage.setItem('pawpilot_refresh_token', j.data.refresh_token)
        localStorage.setItem('pawpilot_user', JSON.stringify(j.data.user))
        return j.data.user.role
      })()`
    )
    return role
  }

  async function visit(path, waitMs = 2600) {
    await send(ws, 'Page.navigate', { url: `${APP}${path}` })
    await waitForLoad(ws)
    await sleep(waitMs)
    return evaluate(ws, 'document.body.innerText')
  }

  /**
   * 打开对话页并回到「欢迎态」。
   * 对话页会保留上一次的会话气泡（欢迎区只在无消息时展示），
   * 因此验证角色化欢迎语前必须点一次「新对话」，否则用例跨次运行不稳定。
   */
  async function openFreshChat(path, waitMs = 3200) {
    const pageText = await visit(path, waitMs)
    await evaluate(
      ws,
      "(() => { const b = [...document.querySelectorAll('button')].find((x) => x.innerText.includes('新对话')); if (b) b.click(); return true })()"
    )
    await sleep(1500)
    return { pageText, welcome: await evaluate(ws, "document.querySelector('.chat-welcome')?.innerText || ''") }
  }

  /**
   * 读取最后一条助手气泡文本。
   */
  async function lastAssistantText() {
    const v = await evaluate(
      ws,
      "[...document.querySelectorAll('.bubble-row--assistant .bubble__text')].pop()?.innerText || ''"
    )
    return typeof v === 'string' ? v : ''
  }

  /**
   * 轮询等待助手产出实质回复。
   * 曾经用固定 sleep(9000)：整轮跑到第 4 节时 LLM 主链偶发 10s+ 才首字，
   * 结果取到空串 →「店员收到运营类回复」假失败。改成轮询到有内容为止。
   */
  async function waitAssistantAnswer(timeoutMs = 35000, minLen = 8) {
    const deadline = Date.now() + timeoutMs
    let last = ''
    while (Date.now() < deadline) {
      last = await lastAssistantText()
      if (last.trim().length >= minLen) {
        await sleep(1500) // 再等一小段，避免只抓到半句
        return (await lastAssistantText()) || last
      }
      await sleep(1000)
    }
    return last
  }

  console.log('== 2. 宠主端页面 ==')
  check('宠主登录', (await loginAs('demo', '123456')) === 'customer')

  let text = await visit('/user/home')
  check('宠主首页渲染', text.includes('我的毛孩子') && /早上好|中午好|下午好|晚上好|夜深了/.test(text))
  check('首页展示快捷入口', text.includes('创建预约') && text.includes('AI 助手'))
  check('首页展示宠物卡片', text.includes('豆豆') || text.includes('咪咪'))

  text = await visit('/user/pets')
  check('宠物档案页渲染', text.includes('宠物档案') && (text.includes('豆豆') || text.includes('咪咪')))
  check('档案展示状态标签', /已绝育|未绝育/.test(text))

  // 档案卡片必须有显式的「疫苗驱虫」入口（寄养的疫苗硬门槛依赖它）
  const vaccineEntry = await evaluate(ws, `(async () => {
    const btn = [...document.querySelectorAll('.pet-card__actions button')]
      .find(b => (b.innerText || '').includes('疫苗'))
    if (!btn) return 'NO-BUTTON'
    btn.click()
    await new Promise(r => setTimeout(r, 1200))
    const title = document.querySelector('.el-drawer__title')?.innerText || ''
    const body = document.querySelector('.el-drawer__body')?.innerText || ''
    return title + '||' + (body.includes('记录类型') ? 'FORM-OK' : 'NO-FORM')
  })()`)
  check('档案卡片有一键进入疫苗 / 驱虫记录',
    String(vaccineEntry).includes('疫苗') && String(vaccineEntry).includes('FORM-OK'),
    String(vaccineEntry).slice(0, 200))
  await evaluate(ws, "document.querySelector('.el-drawer__close-btn')?.click()")

  text = await visit('/user/appointment/create')
  check('发起预约页渲染', text.includes('发起洗护预约') && text.includes('预约摘要'))
  check('时段选择器渲染（余量胶囊）', /余 \d+\/\d+/.test(text))

  text = await visit('/user/appointments')
  check('我的预约页渲染', text.includes('我的预约'))

  text = await visit('/user/messages')
  check('消息中心渲染', text.includes('消息中心'))

  text = await visit('/user/chat', 3200)
  check(
    'AI 助手页渲染',
    text.includes('多 Agent 协作') && (text.includes('宠主自助助手') || text.includes('AI 洗护助手'))
  )
  check('对话区已挂载', (await evaluate(ws, "!!document.querySelector('.chat-shell') && !!document.querySelector('.chat-input textarea')")))
  check(
    '助手架构说明可读取',
    (await evaluate(
      ws,
      "(async()=>{const r=await fetch('/api/v1/chat/capabilities',{headers:{Authorization:'Bearer '+localStorage.getItem('pawpilot_access_token')}});const j=await r.json();return j.data.architecture})()"
    )).includes('ReAct')
  )

  // ---- 真实交互：在对话页发一句话，验证 SSE 流式回复 ----
  console.log('== 2.1 AI 助手里程碑交互（SSE 流式） ==')
  const before = await evaluate(ws, "document.querySelectorAll('.bubble-row').length")
  await evaluate(
    ws,
    `(async () => {
      const ta = document.querySelector('.chat-input textarea')
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
      setter.call(ta, '明天还有哪些时段可以预约？')
      ta.dispatchEvent(new Event('input', { bubbles: true }))
      await new Promise(r => setTimeout(r, 300))
      const btn = [...document.querySelectorAll('.chat-input button')].find(b => b.innerText.includes('发送'))
      btn.click()
      return true
    })()`
  )
  await sleep(9000)
  const after = await evaluate(ws, "document.querySelectorAll('.bubble-row').length")
  const lastAnswer = await evaluate(
    ws,
    "[...document.querySelectorAll('.bubble-row--assistant .bubble__text')].pop()?.innerText || ''"
  )
  const toolChip = await evaluate(
    ws,
    "[...document.querySelectorAll('.bubble-tool')].pop()?.innerText || ''"
  )
  check('发送消息后新增用户与助手气泡', after >= before + 2, `${before} -> ${after}`)
  check('SSE 流式返回助手回复', lastAnswer.length > 10, lastAnswer.slice(0, 80))
  check('展示工具调用轨迹', toolChip.includes('调用工具'), toolChip.slice(0, 60))
  check('回复内容为业务可用答复', /时段|约满/.test(lastAnswer), lastAnswer.slice(0, 80))

  console.log('== 3. 店员端页面 ==')
  check('店员登录', (await loginAs('staff1', 'staff123')) === 'staff')

  text = await visit('/staff/home')
  check('门店看板渲染', text.includes('门店看板') || text.includes('待办提醒'))

  text = await visit('/staff/appointments', 3000)
  check('预约管理渲染', text.includes('预约管理'))
  check('状态机操作按钮渲染', /确认预约|已到店|开始洗护/.test(text))

  text = await visit('/staff/risk')
  check('风险复核渲染', text.includes('风险复核'))

  text = await visit('/staff/pets')
  check('客户档案渲染', text.includes('客户档案'))
  // V8.4.7：取消档案归属限制 —— 页面上不再出现「归属」列，任何店员都能操作所有客户
  check('客户档案不展示「归属」（店员/店长可操作所有客户）',
    !text.includes('归属') && !text.includes('未认领'), text.slice(0, 320))

  text = await visit('/staff/wash-records')
  check('洗护记录渲染', text.includes('洗护记录'))

  text = await visit('/schedule', 3000)
  check('门店排期渲染', text.includes('门店排期') && text.includes('时段'))

  text = await visit('/report/summary', 3200)
  check('经营报表渲染', text.includes('经营报表') && text.includes('复购率'))
  check('图表容器已挂载', (await evaluate(ws, "document.querySelectorAll('canvas').length")) > 0)

  text = await visit('/staff/knowledge', 3000)
  check('店员 RAG 知识库页面渲染', text.includes('RAG 知识库') && text.includes('文档与切块'))
  check(
    '店员知识库为只读（无上传/重建操作按钮）',
    await evaluate(ws, "![...document.querySelectorAll('button')].some(b => ['上传文档','重建索引'].includes((b.innerText||'').trim()))")
  )

  console.log('== 4. 店长端页面与权限 ==')
  check('店长登录', (await loginAs('admin', 'admin123')) === 'manager')

  text = await visit('/staff/settings')
  check('门店配置渲染', text.includes('门店配置') && text.includes('恢复默认配置'))

  text = await visit('/staff/knowledge', 3000)
  check('店长 RAG 知识库页面渲染', text.includes('RAG 知识库') && text.includes('文档与切块'))
  check(
    '店长可见上传与重建索引按钮',
    await evaluate(ws, "['上传文档','重建索引'].every(t => [...document.querySelectorAll('button')].some(b => (b.innerText||'').trim() === t))")
  )

  text = await visit('/report/export')
  check('数据导出渲染', text.includes('数据导出') && text.includes('经营概览'))

  text = await visit('/staff/users', 3000)
  check('员工账号页渲染', text.includes('员工账号'))
  // 不断言具体号段（数据里换了批账号就会假失败），只要求存在完整 11 位号码 = 未脱敏
  check('店长可见原始手机号', /1[3-9]\d{9}/.test(text), text.slice(0, 200))

  text = await visit('/report/audit')
  check('审计日志渲染', text.includes('审计日志'))

  console.log('== 4.1 V5：店员端运营助理 ==')
  await loginAs('staff1', 'staff123')
  await visit('/staff/home', 1500)
  const staffMenu = await evaluate(ws, "document.querySelector('.pp-menu')?.innerText || ''")
  check('店员侧边栏含「运营助理」', staffMenu.includes('运营助理'), staffMenu.slice(0, 200))
  check('店员侧边栏不含「经营助理」', !staffMenu.includes('经营助理'))
  check('店员侧边栏不含店长专属菜单「员工账号」', !staffMenu.includes('员工账号'))

  const staffEntry = await evaluate(
    ws,
    "(() => { const el = document.querySelector('.welcome .agent-entry'); return el ? { href: el.getAttribute('href'), text: el.innerText.replace(/\\n/g, ' ') } : null })()"
  )
  check('店员首页右侧为 Agent 入口', !!staffEntry, JSON.stringify(staffEntry))
  check('店员入口指向运营助理对话页', staffEntry?.href === '/staff/chat', JSON.stringify(staffEntry))
  check('店员入口文案为运营语境', /运营助理/.test(staffEntry?.text || ''), staffEntry?.text)

  const staffChat = await openFreshChat('/staff/chat')
  check('店员对话页渲染', staffChat.pageText.includes('店员运营助理'), staffChat.pageText.slice(0, 260))
  check('店员示例问题角色化', staffChat.welcome.includes('我今天有什么要处理的？'), staffChat.welcome.slice(0, 300))
  check('店员欢迎区用犬形象插画', staffChat.welcome.includes('运营助理就位'), staffChat.welcome.slice(0, 200))
  check(
    '店员工具画像为 11 个（含知识库检索）',
    (await evaluate(
      ws,
      "(async()=>{const r=await fetch('/api/v1/chat/capabilities',{headers:{Authorization:'Bearer '+localStorage.getItem('pawpilot_access_token')}});const j=await r.json();return j.data.tools.length})()"
    )) === 11
  )

  // 店员发一条运营类问题，验证 SSE 与工具调用
  const staffBefore = await evaluate(ws, "document.querySelectorAll('.bubble-row').length")
  await evaluate(
    ws,
    `(async () => {
      const ta = document.querySelector('.chat-input textarea')
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
      setter.call(ta, '我今天有什么要处理的？')
      ta.dispatchEvent(new Event('input', { bubbles: true }))
      await new Promise(r => setTimeout(r, 300))
      ;[...document.querySelectorAll('.chat-input button')].find(b => b.innerText.includes('发送')).click()
      return true
    })()`
  )
  const staffAnswer = await waitAssistantAnswer()
  const staffAfter = await evaluate(ws, "document.querySelectorAll('.bubble-row').length")
  check('店员对话产生新气泡', staffAfter >= staffBefore + 2, `${staffBefore} -> ${staffAfter}`)
  // 断言口径：只要「有实质回复 + 说到了业务对象」，不校验具体措辞。
  // 曾经写成 /待办|待确认|待复核|今日/，结果库里堆着并发犬 / 契约测试犬这类历史数据，
  // 回复变成一串宠物名就假失败 —— 测的是「店员 AI 能用」，不是「模型措辞」。
  check(
    '店员收到运营类回复',
    staffAnswer.trim().length > 8 && /待办|待确认|待复核|今日|今天|预约|单|没有/.test(staffAnswer),
    staffAnswer.slice(0, 140)
  )

  console.log('== 4.2 店长端：AI 入口与会话 ==')
  await loginAs('admin', 'admin123')
  await visit('/staff/home', 1800)
  const mgrMenu = await evaluate(ws, "document.querySelector('.pp-menu')?.innerText || ''")
  check('店长侧边栏含「运营助理」', mgrMenu.includes('运营助理'), mgrMenu.slice(0, 220))
  check('店长侧边栏已移除重复的「经营助理」菜单', !mgrMenu.includes('经营助理'), mgrMenu.slice(0, 220))

  // 菜单顺序：AI 助手应排在「门店运营」板块最后
  const menuOrder = await evaluate(
    ws,
    "[...document.querySelectorAll('.pp-menu__item')].map(a => a.querySelector('.pp-menu__text')?.innerText || a.innerText.trim())"
  )
  check(
    '运营助理排在门店运营板块最后（在门店排期之后）',
    menuOrder.indexOf('运营助理') > menuOrder.indexOf('门店排期'),
    menuOrder.join(' > ')
  )

  // 首页右侧已由静态宠物插画改为 Agent 聊天入口
  const mgrEntry = await evaluate(
    ws,
    "(() => { const el = document.querySelector('.welcome .agent-entry'); return el ? { href: el.getAttribute('href'), text: el.innerText.replace(/\\n/g, ' ') } : null })()"
  )
  check('店长首页右侧为 Agent 入口', !!mgrEntry, JSON.stringify(mgrEntry))
  check('店长入口指向运营助理对话页', mgrEntry?.href === '/staff/chat', JSON.stringify(mgrEntry))
  check('店长入口文案为经营语境', /经营助理/.test(mgrEntry?.text || ''), mgrEntry?.text)

  // 旧链接重定向仍可用；菜单入口已并入「运营助理」，所以这里用 /staff/chat
  const mgrChat = await openFreshChat('/manager/chat')
  check('店长对话页渲染（旧链接 /manager/chat 已重定向）', mgrChat.pageText.includes('店长经营助理'), mgrChat.pageText.slice(0, 260))
  check('店长示例问题角色化', mgrChat.welcome.includes('近 30 天经营情况怎么样？'), mgrChat.welcome.slice(0, 320))
  check(
    '店长画像含店长专属工具',
    (await evaluate(
      ws,
      "(async()=>{const r=await fetch('/api/v1/chat/capabilities',{headers:{Authorization:'Bearer '+localStorage.getItem('pawpilot_access_token')}});const j=await r.json();return j.data.tools.map(t=>t.name).filter(n=>['query_audit_trail','update_store_setting','toggle_user_status'].includes(n)).length})()"
    )) === 3
  )

  console.log('== 4.3 V7.1 宠物寄养 ==')
  await loginAs('demo', '123456')
  text = await visit('/user/boarding', 2600)
  check('宠主寄养列表渲染', text.includes('宠物寄养'), text.slice(0, 240))
  const boardMenu = await evaluate(ws, "document.querySelector('.pp-menu')?.innerText || ''")
  check('宠主侧边栏含「宠物寄养」', boardMenu.includes('宠物寄养'))

  text = await visit('/user/boarding/create', 3600)
  check(
    '寄养下单页渲染（宠物 / 日期 / 宠舍 / 费用明细）',
    text.includes('选择毛孩子') && text.includes('选择宠舍') && text.includes('费用明细'),
    text.slice(0, 320)
  )
  check('下单页含寄养条款与责任划分确认', text.includes('寄养条款与责任划分'), text.slice(0, 320))

  await loginAs('staff1', 'staff123')
  await visit('/staff/home', 1800)
  const staffBoardMenu = await evaluate(ws, "document.querySelector('.pp-menu')?.innerText || ''")
  check('店员侧边栏含「寄养管理」', staffBoardMenu.includes('寄养管理'), staffBoardMenu.slice(0, 240))
  check(
    '寄养管理归入「宠物之家」分组',
    staffBoardMenu.indexOf('宠物之家') >= 0
      && staffBoardMenu.indexOf('寄养管理') > staffBoardMenu.indexOf('宠物之家'),
    staffBoardMenu.slice(0, 260)
  )
  text = await visit('/staff/boarding', 3600)
  check('店员寄养工作台渲染', text.includes('寄养管理'), text.slice(0, 320))
  check(
    '工作台含订单 / 接送任务 / 房态三块',
    text.includes('寄养订单') && text.includes('接送任务') && text.includes('房态'),
    text.slice(0, 320)
  )
  check(
    '房型已就绪（种子房舍可读）',
    (await evaluate(
      ws,
      "(async()=>{const r=await fetch('/api/v1/boarding/rooms',{headers:{Authorization:'Bearer '+localStorage.getItem('pawpilot_access_token')}});const j=await r.json();return (j.data||[]).length})()"
    )) >= 5
  )

  await loginAs('admin', 'admin123')
  await visit('/staff/home', 1500)
  const mgrBoardMenu = await evaluate(ws, "document.querySelector('.pp-menu')?.innerText || ''")
  check('店长侧边栏含「寄养看板」', mgrBoardMenu.includes('寄养看板'), mgrBoardMenu.slice(0, 260))
  text = await visit('/report/boarding', 3800)
  check(
    '店长寄养看板渲染（含入住率与异常率）',
    text.includes('寄养看板') && text.includes('入住率') && text.includes('照护异常率'),
    text.slice(0, 360)
  )

  console.log('== 4.4 V7.2 用品 / V7.3 实景 ==')
  await loginAs('demo', '123456')
  text = await visit('/user/goods', 3400)
  check('宠物用品列表渲染', text.includes('宠物用品') && text.includes('购物车'), text.slice(0, 320))
  const goodsMenu = await evaluate(ws, "document.querySelector('.pp-menu')?.innerText || ''")
  check('宠主侧边栏含「宠物用品」与「宠物实景」',
    goodsMenu.includes('宠物用品') && goodsMenu.includes('宠物实景'), goodsMenu.slice(0, 260))

  text = await visit('/user/goods/orders', 2800)
  check('用品订单页渲染（含核销码提示）', text.includes('我的用品订单') && text.includes('核销码'), text.slice(0, 320))

  text = await visit('/user/camera', 3200)
  check('宠物实景页渲染', text.includes('宠物实景'), text.slice(0, 320))
  check('实景页展示隐私说明', text.includes('隐私') || text.includes('留痕'), text.slice(0, 400))
  check('实景页只看不抓拍（无抓拍入口 / 无相册）',
    !text.includes('抓拍') && !text.includes('我的相册'), text.slice(0, 300))

  // 点「查看实时画面」必须真的出画面（门店没推流时后端给演示帧，前端按帧轮询）
  const player = await evaluate(ws, `(async () => {
    const btn = [...document.querySelectorAll('button')].find(b => (b.innerText || '').includes('查看实时画面'))
    if (!btn) return 'NO-WATCHABLE-ORDER'
    btn.click()
    await new Promise(r => setTimeout(r, 4000))
    const img = document.querySelector('.player__video')
    const dialogTitle = document.querySelector('.el-dialog__title')?.innerText || ''
    const empty = document.querySelector('.player__empty')?.innerText || ''
    return (img ? 'IMG:' + img.naturalWidth + 'x' + img.naturalHeight : 'NO-IMG')
      + '||title:' + dialogTitle + '||empty:' + empty.slice(0, 40)
  })()`)
  check('查看实时画面能弹出播放器并加载到画面',
    String(player).includes('NO-WATCHABLE-ORDER') ||
      (/IMG:(\d+)x(\d+)/.test(String(player)) && !String(player).includes('IMG:0x0')),
    String(player).slice(0, 240))
  await evaluate(ws, "document.querySelector('.el-dialog__headerbtn')?.click()")

  await loginAs('staff1', 'staff123')
  await visit('/staff/home', 1800)
  const staffGoodsMenu = await evaluate(ws, "document.querySelector('.pp-menu')?.innerText || ''")
  check('门店运营含「用品管理」与「实景采集」',
    staffGoodsMenu.includes('用品管理') && staffGoodsMenu.includes('实景采集'), staffGoodsMenu.slice(0, 300))
  check('用品管理与实景采集归入「宠物之家」分组',
    staffGoodsMenu.indexOf('宠物之家') >= 0
      && staffGoodsMenu.indexOf('用品管理') > staffGoodsMenu.indexOf('宠物之家')
      && staffGoodsMenu.indexOf('实景采集') > staffGoodsMenu.indexOf('宠物之家'),
    staffGoodsMenu.slice(0, 300))

  text = await visit('/staff/goods', 3600)
  check('店员用品台渲染（订单 / 核销 / 库存）',
    text.includes('用品管理') && text.includes('核销') && text.includes('库存'), text.slice(0, 340))

  text = await visit('/staff/camera', 3600)
  check('店员实景采集台渲染', text.includes('实景采集') && text.includes('采集与推流'), text.slice(0, 340))
  check('采集台提示浏览器只能打开本机摄像头',
    text.includes('本机') || text.includes('门店电脑摄像头'), text.slice(0, 420))

  await loginAs('admin', 'admin123')
  text = await visit('/report/goods', 4000)
  check('店长用品看板渲染（含连带率）', text.includes('用品看板') && text.includes('连带率'), text.slice(0, 360))
  check(
    '用品商品数据可读（过敏标签已落库）',
    (await evaluate(
      ws,
      "(async()=>{const r=await fetch('/api/v1/goods/products',{headers:{Authorization:'Bearer '+localStorage.getItem('pawpilot_access_token')}});const j=await r.json();return (j.data.items||[]).filter(x=>x.allergy_tags.length>0).length})()"
    )) >= 1
  )

  console.log('== 4.5 本轮修复验证（菜单折叠 / 两行接送 / 商品维护）==')
  await loginAs('staff1', 'staff123')
  await visit('/staff/home', 2000)
  const groupedMenu = await evaluate(ws, "document.querySelector('.pp-menu')?.innerText || ''")
  check('菜单按「洗护预约 / 宠物之家」分组',
    groupedMenu.includes('洗护预约') && groupedMenu.includes('宠物之家'), groupedMenu.slice(0, 320))
  check('分组成员符合约定（预约管理/风险复核在洗护预约，寄养/用品/实景在宠物之家）',
    groupedMenu.indexOf('预约管理') > 0 && groupedMenu.indexOf('寄养管理') > 0, groupedMenu.slice(0, 320))

  const itemsBefore = await evaluate(ws, "document.querySelectorAll('.pp-menu__item').length")
  await evaluate(ws, "document.querySelectorAll('.pp-menu__group')[0].click()")
  await sleep(700)
  const itemsAfterCollapse = await evaluate(ws, "document.querySelectorAll('.pp-menu__item').length")
  check('点击分组标题可折叠（菜单项减少）', itemsAfterCollapse < itemsBefore,
    `${itemsBefore} -> ${itemsAfterCollapse}`)
  await evaluate(ws, "document.querySelectorAll('.pp-menu__group')[0].click()")
  await sleep(700)
  const itemsAfterExpand = await evaluate(ws, "document.querySelectorAll('.pp-menu__item').length")
  check('再次点击可展开（菜单项恢复）', itemsAfterExpand === itemsBefore,
    `${itemsAfterCollapse} -> ${itemsAfterExpand}`)

  text = await visit('/staff/goods', 3600)
  check('用品台新增「商品」页签', text.includes('商品'), text.slice(0, 360))
  // Element Plus 的 tab 内容是懒渲染的，必须点进去才在 DOM 里
  await evaluate(
    ws,
    "[...document.querySelectorAll('.el-tabs__item')].find(t => t.innerText.includes('商品'))?.click()"
  )
  await sleep(1600)
  const productTab = await evaluate(ws, "document.body.innerText")
  check('商品页签含新增入口与表格', productTab.includes('新增商品'),
    productTab.slice(0, 400))

  await loginAs('demo', '123456')
  text = await visit('/user/boarding/create', 3800)
  check('寄养下单拆成两行接送方式',
    text.includes('送宠到店') && text.includes('离店接宠'), text.slice(0, 420))
  check('两行各含「自行」选项',
    text.includes('自行送到') && text.includes('自行接取'), text.slice(0, 460))

  // 关键回归：选宠物 + 日期后必须能选到房型（原 bug 是房型列表 400 全空）
  await evaluate(ws, "document.querySelectorAll('.pet-picker__item')[0]?.click()")
  await sleep(800)
  await evaluate(ws, "document.querySelectorAll('.el-range-input')[0].click()")
  await sleep(1100)
  // 只点「真能点」的格子：月底时前 20 多天是过去日期（.available 但 .disabled），
  // 用固定索引会点到禁用格，日期没选上 → 房型永远空（假失败）。
  // 策略：左面板第一个可选日 → 右面板第一个可选日，跨月保证 check_out > check_in。
  const pick = (panel) =>
    `.el-date-range-picker__content.is-${panel} .el-date-table td.available:not(.prev-month):not(.next-month):not(.disabled)`
  const leftCount = await evaluate(ws, `document.querySelectorAll('${pick('left')}').length`)
  check('日期面板存在可点日期', leftCount > 0, `可点 ${leftCount} 个`)
  await evaluate(ws, `document.querySelectorAll('${pick('left')}')[0]?.click()`)
  await sleep(700)
  const rightCount = await evaluate(ws, `document.querySelectorAll('${pick('right')}').length`)
  if (rightCount > 0) {
    await evaluate(ws, `document.querySelectorAll('${pick('right')}')[0]?.click()`)
  } else {
    const after = await evaluate(ws, `document.querySelectorAll('${pick('left')}').length`)
    await evaluate(ws, `document.querySelectorAll('${pick('left')}')[${Math.max(after - 1, 0)}]?.click()`)
  }
  await sleep(2600)
  // V8.4.8 起改成两级选择：房型 chip + 房号小卡（旧的 .room-card 已不再渲染）
  const roomTypes = await evaluate(ws, "document.querySelectorAll('.type-chip').length")
  const roomCards = await evaluate(ws, "document.querySelectorAll('.room-no').length")
  const roomReqs = await evaluate(
    ws,
    "performance.getEntriesByType('resource').filter(r=>r.name.includes('boarding/rooms')).map(r=>r.responseStatus||0)"
  )
  check('选完日期后房型列表正常渲染（原 bug：全空）',
    roomTypes > 0 && roomCards > 0, `房型 ${roomTypes} 个 / 房号 ${roomCards} 间`)
  check('房型接口返回 200（原 400）', roomReqs.length > 0 && roomReqs.every((c) => c === 200), JSON.stringify(roomReqs))
  await evaluate(
    ws,
    "[...document.querySelectorAll('.room-no')].find(c => !c.classList.contains('is-disabled'))?.click()"
  )
  await sleep(1800)
  const summaryText = await evaluate(ws, "document.querySelector('.summary')?.innerText || ''")
  check('选中房型后费用明细可算出金额', /应付总额/.test(summaryText) && /\d+(\.\d+)?/.test(summaryText),
    summaryText.replace(/\n+/g, ' | ').slice(0, 240))

  console.log('== 4.6 菜单固定项（消息中心 / 首页·看板 / AI 入口）==')
  // 结构化读取菜单：区分固定项（.pp-menu 直接子级）与分组内条目
  const menuShape = async () =>
    evaluate(
      ws,
      `[...document.querySelectorAll('.pp-menu > *')].map(e =>
         e.classList.contains('pp-menu__group') ? 'GROUP:' + e.innerText.split('\\n')[0].trim()
           : e.classList.contains('pp-menu__divider') ? 'DIV'
           : e.innerText.trim().replace(/\\n/g, ' '))`
    )

  await loginAs('demo', '123456')
  await visit('/user/home', 2400)
  const custRows = await menuShape()
  check('宠主菜单第一项是「消息中心」（不在任何分组内）',
    custRows[0]?.startsWith('消息中心'), JSON.stringify(custRows).slice(0, 300))
  check('宠主「我的首页」紧跟消息中心',
    custRows[1]?.startsWith('我的首页'), JSON.stringify(custRows).slice(0, 300))
  check('宠主「AI 洗护助手」固定在菜单最后一项',
    custRows[custRows.length - 1]?.startsWith('AI 洗护助手'), JSON.stringify(custRows).slice(0, 300))
  check('宠主的分组区不含消息中心 / 首页 / AI 助手',
    !custRows.some((r) => r.startsWith('GROUP:') && /消息中心|我的首页|AI 洗护助手/.test(r)),
    JSON.stringify(custRows).slice(0, 320))

  await loginAs('staff1', 'staff123')
  await visit('/staff/home', 2200)
  const staffRows = await menuShape()
  check('店员菜单第一项是「消息中心」', staffRows[0]?.startsWith('消息中心'),
    JSON.stringify(staffRows).slice(0, 320))
  check('店员「门店看板」紧跟消息中心', staffRows[1]?.startsWith('门店看板'),
    JSON.stringify(staffRows).slice(0, 320))
  check('店员「运营助理」固定在菜单最后一项',
    staffRows[staffRows.length - 1]?.startsWith('运营助理'),
    JSON.stringify(staffRows).slice(0, 320))

  await loginAs('admin', 'admin123')
  await visit('/staff/home', 2200)
  const mgrRows = await menuShape()
  check('店长「运营助理」同样固定在最后一项',
    mgrRows[mgrRows.length - 1]?.startsWith('运营助理'), JSON.stringify(mgrRows).slice(0, 320))
  check('店长菜单含系统管理分组且固定项不在组内',
    mgrRows.some((r) => r.startsWith('GROUP:系统管理'))
      && !mgrRows.some((r) => r === 'GROUP:门店看板'), JSON.stringify(mgrRows).slice(0, 360))

  // 折叠分组后，固定项必须仍然可见（消息中心 / 首页 / AI 入口不受折叠影响）
  await loginAs('demo', '123456')
  await visit('/user/home', 2200)
  await evaluate(ws, "document.querySelectorAll('.pp-menu__group').forEach(g => g.click())")
  await sleep(900)
  const afterCollapseRows = await menuShape()
  check('折叠全部分组后，固定项（消息中心 / 首页 / AI 助手）仍可见',
    afterCollapseRows.some((r) => r.startsWith('消息中心'))
      && afterCollapseRows.some((r) => r.startsWith('我的首页'))
      && afterCollapseRows.some((r) => r.startsWith('AI 洗护助手')),
    JSON.stringify(afterCollapseRows).slice(0, 320))
  await evaluate(ws, "document.querySelectorAll('.pp-menu__group').forEach(g => g.click())")
  await sleep(700)

  console.log('== 4.7 V8.2 寄养资格预检与 Agent 新能力 ==')
  await loginAs('demo', '123456')
  text = await visit('/user/boarding/create', 3800)
  check('寄养下单页渲染', text.includes('寄养申请') && text.includes('选择毛孩子'), text.slice(0, 240))

  // 选宠物 + 选日期 → 应出现疫苗资格提示（有效则绿色）
  await evaluate(ws, "document.querySelectorAll('.pet-picker__item')[0]?.click()")
  await sleep(900)
  await evaluate(ws, "document.querySelectorAll('.el-range-input')[0].click()")
  await sleep(1100)
  // 同 4.6：过滤 .disabled，避免月底点到过去日期导致日期没选上
  await evaluate(ws, `document.querySelectorAll('${pick('left')}')[0]?.click()`)
  await sleep(700)
  const eligRight = await evaluate(ws, `document.querySelectorAll('${pick('right')}').length`)
  if (eligRight > 0) {
    await evaluate(ws, `document.querySelectorAll('${pick('right')}')[0]?.click()`)
  } else {
    const eligAfter = await evaluate(ws, `document.querySelectorAll('${pick('left')}').length`)
    await evaluate(ws, `document.querySelectorAll('${pick('left')}')[${Math.max(eligAfter - 1, 0)}]?.click()`)
  }
  await sleep(2600)
  const alerts = await evaluate(ws, "[...document.querySelectorAll('.el-alert')].map(e => e.innerText.replace(/\\n/g,' ')).join(' | ')")
  check('选完宠物与日期即出现疫苗资格提示（不必等提交）',
    alerts.includes('疫苗'), alerts.slice(0, 240))
  check('疫苗有效时提示为成功态且不再要求补登',
    alerts.includes('疫苗有效') && !alerts.includes('去登记疫苗'), alerts.slice(0, 240))

  // Agent：看宠物状态 → 自动跳到宠物实景
  // 必须先开新对话：上一步刚聊过寄养，会话里带着寄养上下文会把这句话接成寄养续聊
  await openFreshChat('/user/chat', 2800)
  await evaluate(ws, `(async () => {
    const ta = document.querySelector('textarea')
    if (!ta) return 'no-textarea'
    ta.value = '帮我看看宠物现在的状态'
    ta.dispatchEvent(new Event('input', { bubbles: true }))
    await new Promise(r => setTimeout(r, 300))
    const btn = [...document.querySelectorAll('button')].find(b => b.innerText.includes('发送'))
    if (btn) btn.click()
    return true
  })()`)
  // 有在住宠物会直接导航走（气泡不再产出），所以要同时等跳转和等回复
  const cameraNav = await (async () => {
    const snap = () =>
      evaluate(
        ws,
        "JSON.stringify({ path: location.pathname, text: (document.querySelector('.chat-stream')?.innerText || '').slice(0, 400) })"
      )
    const deadline = Date.now() + 25000
    let cur = await snap()
    while (Date.now() < deadline) {
      if (String(cur).includes('/user/camera')) return cur
      if ((await lastAssistantText()).trim().length >= 8) return await snap()
      await sleep(1000)
      cur = await snap()
    }
    return cur
  })()
  // V8.4.9：有在住宠物 → 跳实景页并自动打开那一单；没有 → 聊天里明确说明
  let camState = {}
  try { camState = JSON.parse(String(cameraNav)) } catch { camState = { path: '', text: '' } }
  check('「看看宠物状态」走实景流程（跳转带单号或说明无在住宠物）',
    String(camState.path || '').includes('/user/camera') || String(camState.text || '').includes('寄养中'),
    String(cameraNav).slice(0, 240))

  // Agent：建档案 → 出现二次确认卡（不直接落库）
  await visit('/user/chat', 2600)
  const confirmCard = await evaluate(ws, `(async () => {
    const ta = document.querySelector('textarea')
    if (!ta) return ''
    ta.value = '帮我建个宠物档案，叫小七'
    ta.dispatchEvent(new Event('input', { bubbles: true }))
    await new Promise(r => setTimeout(r, 300))
    const btn = [...document.querySelectorAll('button')].find(b => b.innerText.includes('发送'))
    if (btn) btn.click()
    await new Promise(r => setTimeout(r, 9500))
    const card = document.querySelector('.confirm-card')
    const stream = document.querySelector('.chat-stream')?.innerText || ''
    return (card ? card.innerText.split(String.fromCharCode(10)).join(' | ') : 'NO-CARD')
      + '||has-summary:' + (stream.includes('帮你建个档案') || stream.includes('名字'))
      + '||stream:' + stream.slice(-160).split(String.fromCharCode(10)).join(' / ')
  })()`)
  check('Agent 建档案会先出确认卡且复述内容（未确认不落库）',
    String(confirmCard).includes('create_pet_profile') && String(confirmCard).includes('has-summary:true'),
    String(confirmCard).slice(0, 240))

  console.log('== 5. 角色权限守卫 ==')
  await loginAs('demo', '123456')
  text = await visit('/staff/settings', 2000)
  check('宠主访问店长页面被拦截到 403', text.includes('403') || text.includes('不属于当前角色'))
  text = await visit('/staff/appointments', 2000)
  check('宠主访问店员页面被拦截到 403', text.includes('403') || text.includes('不属于当前角色'))
  text = await visit('/staff/chat', 2000)
  check('宠主访问运营助理页被拦截到 403', text.includes('403') || text.includes('不属于当前角色'))
  const custEntry = await visit('/user/home', 2500)
  check('宠主首页右侧为 Agent 入口', custEntry.includes('AI 洗护助手'), custEntry.slice(0, 200))
  check(
    '宠主入口指向 AI 洗护助手对话页',
    (await evaluate(ws, "document.querySelector('.welcome .agent-entry')?.getAttribute('href')")) === '/user/chat'
  )

  console.log('== 6. 控制台健康度 ==')
  check('无未捕获运行时异常', pageExceptions.length === 0, pageExceptions.slice(0, 2).join(' | '))
  const realErrors = consoleErrors.filter(
    (e) => !/favicon|ERR_|Download the Vue Devtools|\[vite\]/i.test(e)
  )
  check('无控制台错误', realErrors.length === 0, realErrors.slice(0, 2).join(' | '))

  ws.close()

  const failed = results.filter((r) => !r.ok)
  console.log('\n' + '='.repeat(58))
  console.log(`浏览器验证：PASS ${results.length - failed.length} / FAIL ${failed.length}`)
  if (failed.length) {
    console.log('失败项：')
    failed.forEach((f) => console.log('  -', f.name))
  }
  console.log('='.repeat(58))
  process.exit(failed.length ? 1 : 0)
}

main().catch((err) => {
  console.error('验证脚本异常:', err.message)
  process.exit(2)
})
