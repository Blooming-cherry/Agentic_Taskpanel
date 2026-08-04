let TOKEN = null
let LAST_EVENT_ID = 0

async function jsonFetch(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) }
  if (TOKEN) headers['X-Auth-Token'] = TOKEN
  const res = await fetch(path, { ...opts, headers })
  if (res.status === 401) throw new Error('auth failed')
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

export async function bootstrap() {
  const data = await jsonFetch('/api/bootstrap')
  TOKEN = data.token
  return data
}
export const createTask = (body) => jsonFetch('/api/tasks', { method: 'POST', body: JSON.stringify(body) })
export const listTasks = () => jsonFetch('/api/tasks')
export const getTask = (id) => jsonFetch(`/api/tasks/${id}`)
export const sendMessage = (id, text) => jsonFetch(`/api/tasks/${id}/messages`, { method: 'POST', body: JSON.stringify({ text }) })
export const stopTask = (id) => jsonFetch(`/api/tasks/${id}/stop`, { method: 'POST' })
export const deleteTask = (id) => jsonFetch(`/api/tasks/${id}`, { method: 'DELETE' })
export const fetchEvents = (id, since) => jsonFetch(`/api/tasks/${id}/events?since=${since}`)

export function connectWS(onEvent) {
  let ws, closed = false, retry = 0, timer = null
  function open() {
    // 每次(重)连都用实时 TOKEN/LAST_EVENT_ID 构造 URL,避免水位冻结重复回放
    const url = `ws://${location.host}/ws/tasks?token=${encodeURIComponent(TOKEN)}&last_event_id=${LAST_EVENT_ID}`
    ws = new WebSocket(url)
    ws.onmessage = (ev) => {
      const e = JSON.parse(ev.data)
      if (e.seq <= LAST_EVENT_ID) return // 客户端去重: 旧水位重复回放的事件直接丢弃
      LAST_EVENT_ID = e.seq
      onEvent(e)
    }
    ws.onclose = () => { if (!closed) timer = setTimeout(reconnect, Math.min(1000 * 2 ** retry++, 15000)) }
    ws.onopen = () => { retry = 0 }
  }
  function reconnect() {
    if (closed) return // close() 后不再重连
    // 用 REST 补齐可能错过的增量(断线期间的事件由服务端 events_since 补)
    onEvent({ type: 'reconnect' })
    open()
  }
  open()
  return { close() { closed = true; if (timer) clearTimeout(timer); ws?.close() } }
}

window.__api = {
  bootstrap, createTask, listTasks, getTask, sendMessage, stopTask, deleteTask, fetchEvents, connectWS,
}
