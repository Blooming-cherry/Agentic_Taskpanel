import { useEffect, useState } from 'react'
import { getReview, fetchContext, runReview } from '../api.js'

function DiffPreview({ taskId, file, line, context }) {
  const [data, setData] = useState(null)
  useEffect(() => {
    fetchContext(taskId, file, line, context).then(setData).catch(() => setData(null))
  }, [taskId, file, line, context])
  if (!data) return <pre style={{ fontSize: 11, color: '#888' }}>加载中…</pre>
  return (
    <pre style={{ fontSize: 12, maxHeight: 160, overflow: 'auto' }}>
      {data.lines.map((l, i) => {
        const n = data.start + i
        return `${String(n).padStart(4, ' ')} ${n === line ? '▶' : ' '} ${l}`
      }).join('\n')}
    </pre>
  )
}

export default function ReviewPane({ task, diffContext }) {
  const [review, setReview] = useState(null)
  const [severity, setSeverity] = useState('all')
  const [expanded, setExpanded] = useState(null)

  useEffect(() => {
    getReview(task.id).then(setReview).catch(() => setReview(null))
  }, [task.id])

  async function onRunReview() {
    try {
      await runReview(task.id)
      setReview(await getReview(task.id))
    } catch {
      setReview(null)
    }
  }

  const findings = review?.findings || []
  const shown = severity === 'all' ? findings : findings.filter((f) => f.severity === severity)
  return (
    <aside className="review">
      <h3>Review</h3>
      <button onClick={onRunReview} style={{ marginBottom: 8 }}>运行 Review</button>
      <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
        <option value="all">全部</option><option value="high">High</option>
        <option value="medium">Medium</option><option value="low">Low</option>
      </select>
      {shown.length === 0 && <p style={{ color: '#888' }}>暂无发现(右栏可折叠 Esc)</p>}
      {shown.map((f, i) => (
        <div key={i} className="toolcard">
          <b>{f.severity}</b> {f.file}:{f.line}
          <p>{f.text}</p>
          <button onClick={() => setExpanded(expanded === i ? null : i)}>
            {expanded === i ? '收起' : '展开 diff'}
          </button>
          {expanded === i && (
            <DiffPreview taskId={task.id} file={f.file} line={f.line} context={diffContext} />
          )}
        </div>
      ))}
      {review?.raw && <pre style={{ fontSize: 11, color: '#900' }}>{review.raw}</pre>}
    </aside>
  )
}
