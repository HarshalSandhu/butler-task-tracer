import { useEffect, useRef, useState } from 'react'

/**
 * Ticks up once a second while `active` is true, resets to 0 the moment it
 * goes false -> true again. Purely a UX signal for long SSH-grep-backed
 * requests (can take 60-180s) so the UI visibly keeps moving instead of
 * looking hung on a static "Scanning..." string.
 */
export function useElapsedSeconds(active: boolean): number {
  const [seconds, setSeconds] = useState(0)
  const startRef = useRef<number | null>(null)

  useEffect(() => {
    if (!active) {
      startRef.current = null
      setSeconds(0)
      return
    }
    startRef.current = Date.now()
    setSeconds(0)
    const id = setInterval(() => {
      if (startRef.current !== null) {
        setSeconds(Math.floor((Date.now() - startRef.current) / 1000))
      }
    }, 1000)
    return () => clearInterval(id)
  }, [active])

  return seconds
}
