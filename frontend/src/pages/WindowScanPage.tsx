/**
 * PLAN.md "Batch/aggregate view" (Mode 2: time range, no task_id) and
 * "Full Scan" (Mode 3: bounded unbounded-scan). Backend job bodies are
 * still TODO (see backend/app/jobs.py) - this page is wired to the real
 * /api/window and /api/scan endpoints (which already validate input and
 * return a job_id) but polling + rendering the PhaseDistribution/task-list
 * result is the next increment once run_window_scan/run_full_scan are
 * implemented server-side.
 */
export function WindowScanPage() {
  return (
    <div className="p-6 max-w-5xl mx-auto">
      <p className="text-gray-400 text-sm">
        Batch/window analysis - backend job execution not yet wired (see{' '}
        <code className="bg-gray-800 text-gray-200 px-1">backend/app/jobs.py</code>). The API contract
        (<code className="bg-gray-800 text-gray-200 px-1">POST /api/window</code>,{' '}
        <code className="bg-gray-800 text-gray-200 px-1">POST /api/scan</code>) is in place; this page
        will poll the returned <code className="bg-gray-800 text-gray-200 px-1">job_id</code> and render
        results via <code className="bg-gray-800 text-gray-200 px-1">PhaseDistribution</code> once the
        job bodies are implemented.
      </p>
    </div>
  )
}
