/** Single source of truth for the trace page's URL shape (PLAN.md "URL
 * structure") -- used both for same-tab navigation and for building an
 * href/window.open target when opening a task in a new tab. */
export function buildTraceUrl(butlerIp: string, taskId: string, sshUser?: string): string {
  const qs = sshUser ? `?ssh_user=${encodeURIComponent(sshUser)}` : ''
  return `/trace/${butlerIp}/task/${taskId}${qs}`
}
