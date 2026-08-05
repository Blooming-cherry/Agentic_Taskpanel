export default function StatusBar({ tasks, wsOk }) {
  const tokens = tasks.reduce((s, t) => s + (t.token_count || 0), 0)
  return (
    <footer className="statusbar">
      <span>任务: {tasks.length}</span>
      <span>Token: {tokens}</span>
      <span>连接: {wsOk ? '✓' : '✗'}</span>
    </footer>
  )
}
