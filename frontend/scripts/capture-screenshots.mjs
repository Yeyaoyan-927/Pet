/**
 * 界面截图脚本（CDP，零额外依赖）
 * 用法：node scripts/capture-screenshots.mjs [输出目录]
 * 依赖：已启动的前端 dev server（5173）与后端（8000），以及带 9222 调试端口的浏览器
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { setTimeout as sleep } from 'node:timers/promises'

const CDP = 'http://127.0.0.1:9222'
const APP = 'http://127.0.0.1:5173'
const OUT = process.argv[2] || '../docs/screenshots'

let id = 0
const pending = new Map()

function send(ws, method, params = {}) {
  const i = ++id
  ws.send(JSON.stringify({ id: i, method, params }))
  return new Promise((resolve, reject) => {
    pending.set(i, { resolve, reject })
    setTimeout(() => {
      if (pending.has(i)) {
        pending.delete(i)
        reject(new Error(`CDP timeout: ${method}`))
      }
    }, 30000)
  })
}

async function evaluate(ws, expression) {
  const res = await send(ws, 'Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
  return res.result?.value
}

async function waitLoad(ws, timeout = 15000) {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, timeout)
    const handler = (ev) => {
      if (JSON.parse(ev.data).method === 'Page.loadEventFired') {
        clearTimeout(timer)
        ws.removeEventListener('message', handler)
        resolve()
      }
    }
    ws.addEventListener('message', handler)
  })
}

async function main() {
  mkdirSync(OUT, { recursive: true })

  const list = await (await fetch(`${CDP}/json/list`)).json()
  const target = list.find((t) => t.type === 'page')
  if (!target) throw new Error('没有可用的调试目标')

  const ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((r) => ws.addEventListener('open', r))
  ws.addEventListener('message', (ev) => {
    const d = JSON.parse(ev.data)
    if (d.id && pending.has(d.id)) {
      const { resolve, reject } = pending.get(d.id)
      pending.delete(d.id)
      d.error ? reject(new Error(d.error.message)) : resolve(d.result)
    }
  })

  await send(ws, 'Page.enable')
  await send(ws, 'Runtime.enable')
  await send(ws, 'Emulation.setDeviceMetricsOverride', {
    width: 1600,
    height: 1000,
    deviceScaleFactor: 1,
    mobile: false
  })

  async function shoot(name, path, user, waitMs = 2800, beforeShot = null) {
    if (user) {
      if (!beforeShot) {
        await send(ws, 'Page.navigate', { url: `${APP}/login` })
        await waitLoad(ws)
        await sleep(1200)
      }
      await evaluate(
        ws,
        `(async () => {
          const r = await fetch('/api/v1/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: '${user[0]}', password: '${user[1]}' })
          })
          const j = await r.json()
          localStorage.setItem('pawpilot_access_token', j.data.access_token)
          localStorage.setItem('pawpilot_refresh_token', j.data.refresh_token)
          localStorage.setItem('pawpilot_user', JSON.stringify(j.data.user))
          return j.code
        })()`
      )
    }
    await send(ws, 'Page.navigate', { url: `${APP}${path}` })
    await waitLoad(ws)
    await sleep(waitMs)
    if (beforeShot) await beforeShot(ws)
    const shot = await send(ws, 'Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
    writeFileSync(`${OUT}/${name}.png`, Buffer.from(shot.data, 'base64'))
    console.log(`  saved ${OUT}/${name}.png`)
  }

  console.log('开始截图 ...')
  // 先清空登录态，否则 /login 会被路由守卫重定向到角色首页
  await send(ws, 'Page.navigate', { url: `${APP}/login` })
  await waitLoad(ws)
  await sleep(1200)
  await evaluate(ws, 'localStorage.clear()')

  await shoot('01-登录页', '/login', null, 2600)
  await shoot('02-宠主首页', '/user/home', ['demo', '123456'])
  await shoot('03-宠物档案', '/user/pets', ['demo', '123456'])
  await shoot('04-发起预约', '/user/appointment/create', ['demo', '123456'])
  await shoot('05-AI洗护助手', '/user/chat', ['demo', '123456'], 5200)
  await shoot('06-门店看板', '/staff/home', ['staff1', 'staff123'])
  await shoot('07-预约管理', '/staff/appointments', ['staff1', 'staff123'], 3200)
  await shoot('08-风险复核', '/staff/risk', ['staff1', 'staff123'])
  await shoot('09-门店排期', '/schedule', ['staff1', 'staff123'], 3200)
  await shoot('10-经营报表', '/report/summary', ['admin', 'admin123'], 3800)
  await shoot('11-数据导出', '/report/export', ['admin', 'admin123'])
  await shoot('12-门店配置', '/staff/settings', ['admin', 'admin123'])
  await shoot('13-员工账号', '/staff/users', ['admin', 'admin123'], 3000)
  await shoot('14-店员运营助理', '/staff/chat', ['staff1', 'staff123'], 5000)
  await shoot('15-店长经营助理', '/staff/chat', ['admin', 'admin123'], 5000)
  await shoot('16-店长经营助理（首页入口）', '/staff/home', ['admin', 'admin123'], 3200)
  await shoot('17-宠物寄养', '/user/boarding', ['demo', '123456'], 3200)
  await shoot('18-新建寄养', '/user/boarding/create', ['demo', '123456'], 4000)
  await shoot('19-寄养管理', '/staff/boarding', ['staff1', 'staff123'], 4000)
  await shoot('20-寄养看板', '/report/boarding', ['admin', 'admin123'], 4200)
  await shoot('21-宠物用品', '/user/goods', ['demo', '123456'], 3600)
  await shoot('22-用品订单', '/user/goods/orders', ['demo', '123456'], 3200)
  await shoot('23-用品管理', '/staff/goods', ['staff1', 'staff123'], 3800)
  await shoot('24-宠物实景', '/user/camera', ['demo', '123456'], 3400)
  await shoot('25-实景采集', '/staff/camera', ['staff1', 'staff123'], 3800)
  await shoot('26-用品看板', '/report/goods', ['admin', 'admin123'], 4200)

  ws.close()
  console.log('截图完成')
  process.exit(0)
}

main().catch((err) => {
  console.error('截图失败:', err.message)
  process.exit(1)
})
