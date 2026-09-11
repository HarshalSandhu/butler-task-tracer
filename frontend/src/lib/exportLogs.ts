import { fetchTaskFullLogs } from './api'

/** Fetches and triggers a browser download of EVERY raw log line in the
 * task's own time window, from the first line to the last -- not filtered
 * to task_id mentions, any known lift/rotation/fork marker, or even this
 * task's own butler_id (see backend's get_task_full_logs) -- the "all the
 * logs, not just the rm ones" escape hatch, alongside the Excel export. */
export async function downloadTaskFullLogs(params: {
  taskId: string
  butlerIp: string
}): Promise<void> {
  const { taskId, butlerIp } = params
  const result = await fetchTaskFullLogs({ butlerIp, taskId })

  const header = [
    `# Full raw logs for task ${result.task_id}`,
    `# Butler ID: ${result.butler_id ?? 'unknown'}`,
    `# Window: ${result.window_start ?? '?'} -> ${result.window_end ?? '?'}`,
    `# ${result.line_count} line(s)`,
    '',
  ].join('\n')
  const content = header + result.lines.join('\n') + '\n'

  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${taskId}-full-logs.log`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
