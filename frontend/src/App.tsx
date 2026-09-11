import { Navigate, Route, Routes } from 'react-router-dom'
import { TaskDeepDivePage } from './pages/TaskDeepDivePage'
import { ComparePage } from './pages/ComparePage'
import { WindowScanPage } from './pages/WindowScanPage'
import { TaskScanPage } from './pages/TaskScanPage'
import { TaskListPage } from './pages/TaskListPage'

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
      <Route path="/" element={<TaskListPage />} />
      <Route path="/trace/:butlerIp/task/:taskId" element={<TaskDeepDivePage />} />
      <Route path="/trace/:butlerIp/window" element={<WindowScanPage />} />
      <Route path="/trace/:butlerIp/scan" element={<TaskScanPage />} />
      <Route path="/trace/:butlerIp/compare" element={<ComparePage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
