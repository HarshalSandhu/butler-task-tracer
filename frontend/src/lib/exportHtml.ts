/** Builds and triggers a browser download of the CURRENTLY RENDERED trace
 * view (the deep-dive page: stat cards, swimlane chart, legends, raw-log
 * toggle) as a single self-contained .html file.
 *
 * This is a WYSIWYG snapshot: it serializes the live DOM (`#root`) that
 * React/recharts already rendered, so the saved file shows exactly what was
 * on screen at click time (recharts draw real <path>/<text> elements, so the
 * timeline survives serialization as static, non-interactive SVG). Tailwind
 * is captured the same way the browser sees it -- every <style> the dev
 * server injected plus any external stylesheets -- so the offline file keeps
 * the same dark theme without fetching anything (no network, no build step,
 * works straight off disk via file:// or a mail attachment).
 *
 * All app scripts are deliberately dropped: the snapshot is a static report,
 * so embedding the whole JS bundle would only add weight and re-run hydration
 * against a possibly-edited DOM. Companion to exportExcel.ts (timing sheet)
 * and exportLogs.ts (raw log lines) -- same shared-row-data philosophy: this
 * one exports the rendered result itself rather than re-deriving numbers. */
export async function downloadViewAsHtml(params: {
  taskId: string
  title?: string
}): Promise<void> {
  const { taskId, title } = params

  const root = document.getElementById('root')
  const snapshot = root ? (root.cloneNode(true) as HTMLElement).innerHTML : ''

  // Collect every stylesheet the browser currently applies -- inline <style>
  // tags (how Vite's dev server injects Tailwind) plus any <link> stylesheets
  // -- so the offline file renders identically without network access.
  const css: string[] = []
  document.querySelectorAll('style').forEach((s) => {
    if (s.textContent) css.push(s.textContent)
  })
  for (const link of Array.from(document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]'))) {
    try {
      const res = await fetch(link.href)
      if (res.ok) css.push(await res.text())
    } catch {
      // Same-origin dev-server stylesheets always fetch cleanly; a failed
      // external stylesheet is not worth failing the whole export over.
    }
  }

  const html = [
    '<!doctype html>',
    '<html lang="en">',
    '<head>',
    '  <meta charset="utf-8" />',
    '  <meta name="viewport" content="width=device-width, initial-scale=1.0" />',
    `  <title>${escapeHtml(title ?? taskId)} - Butler Task Lifecycle Tracer</title>`,
    '  <style>' + css.join('\n') + '</style>',
    '</head>',
    // Inline fallback palette so the report stays legible even if no CSS
    // could be collected at all (it mirrors src/index.css's body).
    '<body style="margin:0;background-color:#0f172a;color:#e5e7eb;font-family:system-ui,-apple-system,sans-serif">',
    '  <div id="root">' + snapshot + '</div>',
    '</body>',
    '</html>',
  ].join('\n')

  const blob = new Blob([html], { type: 'text/html' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${taskId}-report.html`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}