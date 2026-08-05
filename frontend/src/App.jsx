import { useEffect, useState, useCallback, useRef } from 'react'
import * as api from './api.js'
import Sidebar from './components/Sidebar.jsx'
import ChatPane from './components/ChatPane.jsx'
import StatusBar from './components/StatusBar.jsx'
import ReviewPane from './components/ReviewPane.jsx'
import './styles.css'

export default function App() {
  const [tasks, setTasks] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [events, setEvents] = useState([])
  const [wsOk, setWsOk] = useState(false)
  const [showReview, setShowReview] = useState(true)
  const wsRef = useRef(null)

  const refresh = useCallback(async () => {
    const data = await api.listTasks()
    setTasks(data)
    setSelectedId((cur) => cur || null)
    // 终态(done/error/stopped)任务的 text_delta 已被 REST 吸收进 task.messages,
    // 从直播缓冲中清除,避免与最终消息重复渲染
    const terminal = new Set(data.filter((t) => ['done', 'error', 'stopped'].includes(t.status)).map((t) => t.id))
    if (terminal.size) {
      setEvents((prev) => prev.filter((e) => !(e.type === 'text_delta' && terminal.has(e.task_id))))
    }
  }, [])

  useEffect(() => {
    api.bootstrap().then(refresh)
  }, [refresh])

  useEffect(() => {
    wsRef.current = api.connectWS((e) => {
      if (e.type === 'reconnect') { refresh(); return }
      setWsOk(true)
      setEvents((prev) => [...prev.slice(-500), e])
    })
    return () => wsRef.current?.close()
  }, [refresh])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'n' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        document.getElementById('new-task-btn')?.click()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') setShowReview((v) => !v) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const selected = tasks.find((t) => t.id === selectedId) || null
  return (
    <>
      <div className="main">
        <Sidebar tasks={tasks} selectedId={selectedId} onSelect={setSelectedId} onTasksChanged={refresh} />
        {selected ? <ChatPane task={selected} events={events} onEventsChanged={refresh} />
                  : <div className="pane" style={{ placeContent: 'center', textAlign: 'center', color: '#888' }}>选择左侧任务开始</div>}
        {selected && showReview && <ReviewPane task={selected} diffContext={8} />}
      </div>
      <StatusBar tasks={tasks} wsOk={wsOk} />
    </>
  )
}
