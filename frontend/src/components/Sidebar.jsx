import { useState } from 'react'
import { createTask } from '../api.js'

export default function Sidebar({ tasks, selectedId, onSelect, onTasksChanged }) {
  const [showForm, setShowForm] = useState(false)
  const [kind, setKind] = useState('chat')
  const [prompt, setPrompt] = useState('')
  const [cwd, setCwd] = useState('')
  const [wt, setWt] = useState(false)

  async function submit(e) {
    e.preventDefault()
    await createTask({ kind, prompt, cwd: cwd || null, use_worktree: wt })
    setPrompt(''); setShowForm(false); onTasksChanged()
  }

  const byKind = (k) => tasks.filter((t) => t.kind === k)

  return (
    <aside className="sidebar">
      <button id="new-task-btn" onClick={() => setShowForm((v) => !v)} style={{ width: '100%' }}>
        {showForm ? '收起' : '+ 新建任务 (Ctrl+N)'}
      </button>
      {showForm && (
        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="chat">Chat(不绑定仓库)</option>
            <option value="project">Project(绑定仓库)</option>
          </select>
          {kind === 'project' && (
            <>
              <input placeholder="仓库路径" value={cwd} onChange={(e) => setCwd(e.target.value)} />
              <label><input type="checkbox" checked={wt} onChange={(e) => setWt(e.target.checked)} /> worktree 隔离</label>
            </>
          )}
          <textarea rows={3} placeholder="任务描述" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          <button disabled={!prompt}>派发</button>
        </form>
      )}
      <h4>Project</h4>
      {byKind('project').map((t) => <TaskItem key={t.id} t={t} sel={selectedId === t.id} onSelect={onSelect} />)}
      <h4>Chat</h4>
      {byKind('chat').map((t) => <TaskItem key={t.id} t={t} sel={selectedId === t.id} onSelect={onSelect} />)}
    </aside>
  )
}

function TaskItem({ t, sel, onSelect }) {
  return (
    <div className={`task-item${sel ? ' selected' : ''}`} onClick={() => onSelect(t.id)}>
      <span className={`badge ${t.status}`} />
      <strong>{t.title}</strong>
    </div>
  )
}
