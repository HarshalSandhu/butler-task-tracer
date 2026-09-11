import { useElapsedSeconds } from '../hooks/useElapsedSeconds'

/**
 * Spinner + live elapsed-seconds counter + description, shown while a
 * long SSH-grep-backed request is in flight (these routinely take
 * 15-180s) -- a static "Scanning..." string with no motion reads as
 * hung; this keeps visibly ticking so it's obvious work is happening.
 */
export function LoadingIndicator({ active, label }: { active: boolean; label: string }) {
  const seconds = useElapsedSeconds(active)
  if (!active) return null

  return (
    <div className="flex items-center gap-2 text-sm text-gray-400">
      <span
        className="inline-block h-3.5 w-3.5 rounded-full border-2 border-gray-600 border-t-blue-400 animate-spin"
        aria-hidden="true"
      />
      <span>
        {label} <span className="font-mono text-gray-300">{seconds}s</span> elapsed
      </span>
    </div>
  )
}
