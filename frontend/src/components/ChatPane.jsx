import { useState } from 'react'
import { sendMessage, stopTask, deleteTask } from '../api.js'

export default function ChatPane({ task, events, onEventsChanged }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    if (!text.trim() || busy) return
    setBusy(true)
    await sendMessage(task.id, text)
    setText('')
    setTimeout(() => setBusy(false), 100)
    onEventsChanged()
  }

  const msgs = task?.messages || []
  return (
    <section className="pane">
      <div className="msgs">
        {msgs.map((m, i) => (
          <div key={i} className="msg">
            <b>{m.role}</b>: {m.content.map((c) => (c.type === 'text' ? c.text : `[tool: ${c.type}]`)).join(' ')}
          </div>
        ))}
        {(events.filter((e) => e.type === 'text_delta')).slice(-200).map((e, i) => (
          <span key={i}>{e.text}</span>
        ))}
      </div>
      <form className="inputbar" onSubmit={submit}>
        <input value={text} placeholder="继续对话…" onChange={(e) => setText(e.target.value)} />
        <button disabled={!text.trim() || busy}>发送</button>
        <button type="button" onClick={async () => { await stopTask(task.id) }}>停止</button>
        <button type="button" onClick={async () => { if (confirm('删除任务?')) await deleteTask(task.id); onEventsChanged() }}>删除</button>
      </form>
    </section>
  )
}
