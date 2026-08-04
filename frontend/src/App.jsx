import { useEffect, useState, useCallback, useRef } from 'react'
import * as api from './api.js'
import Sidebar from './components/Sidebar.jsx'
import ChatPane from './components/ChatPane.jsx'
import StatusBar from './components/StatusBar.jsx'
import './styles.css'

export default function App() {
  const [tasks, setTasks] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [events, setEvents] = useState([])
  const [wsOk, setWsOk] = useState(false)
  const wsRef = useRef(null)

  const refresh = useCallback(async () => {
    setTasks(await api.listTasks())
    setSelectedId((cur) => cur || null)
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

  const selected = tasks.find((t) => t.id === selectedId) || null
  return (
    <>
      <div className="main">
        <Sidebar tasks={tasks} selectedId={selectedId} onSelect={setSelectedId} onTasksChanged={refresh} />
        {selected ? <ChatPane task={selected} events={events} onEventsChanged={refresh} />
                  : <div className="pane" style={{ placeContent: 'center', textAlign: 'center', color: '#888' }}>选择左侧任务开始</div>}
      </div>
      <StatusBar tasks={tasks} wsOk={wsOk} />
    </>
  )
}
