import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { TaskDeepDivePage, SearchBar } from './pages/TaskDeepDivePage'
import { ComparePage } from './pages/ComparePage'
import { WindowScanPage } from './pages/WindowScanPage'

/**
 * Routing shell - PLAN.md "URL structure":
 *   /trace/:butlerIp/task/:taskId
 *   /trace/:butlerIp/window?from=...&to=...
 *   /trace/:butlerIp/scan?from=...&to=...
 *   /trace/:butlerIp/compare?a=:taskId&b=:taskId
 */
function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/trace/:butlerIp/task/:taskId" element={<TaskDeepDivePage />} />
      <Route path="/trace/:butlerIp/window" element={<WindowScanPage />} />
      <Route path="/trace/:butlerIp/scan" element={<WindowScanPage />} />
      <Route path="/trace/:butlerIp/compare" element={<ComparePage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

function Landing() {
  const navigate = useNavigate()
  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Butler Task Lifecycle Tracer</h1>
        <p className="text-sm text-gray-500">
          Read-only observability over SSH - see the README for scope. Enter a butler_ip
          and task_id to trace a task's full lifecycle.
        </p>
      </div>
      <SearchBar
        defaultButlerIp=""
        defaultTaskId=""
        onSubmit={(ip, id) => navigate(`/trace/${ip}/task/${id}`)}
      />
    </div>
  )
}

export default App
