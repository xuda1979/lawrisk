import { useCallback, useEffect, useRef, useState } from 'react'

type View = 'rendered' | 'source'

/**
 * Renders the backend-generated, self-contained HTML report inline in a
 * sandboxed iframe (the report markup is fully entity-escaped upstream and
 * carries no scripts, so no execution is possible). A toggle switches to the
 * raw Markdown source for anyone who prefers the text form.
 */
export function ReportView({ html, markdown }: { html: string; markdown: string }) {
  const [view, setView] = useState<View>('rendered')
  const frame = useRef<HTMLIFrameElement>(null)
  const [height, setHeight] = useState(320)

  const resize = useCallback(() => {
    const doc = frame.current?.contentDocument
    if (doc) setHeight(Math.max(doc.documentElement.scrollHeight, 320))
  }, [])

  useEffect(() => {
    resize()
  }, [html, markdown, resize])

  const hasHtml = html.length > 0
  const showRendered = view === 'rendered' && hasHtml
  const showSource = view === 'source' || !hasHtml

  return (
    <div className="report-view">
      <div className="report-view__toggle" role="tablist" aria-label="Report view">
        <button
          type="button"
          className={showRendered ? 'active' : ''}
          onClick={() => setView('rendered')}
          disabled={!hasHtml}
          aria-selected={showRendered}
        >
          Rendered
        </button>
        <button
          type="button"
          className={showSource ? 'active' : ''}
          onClick={() => setView('source')}
          aria-selected={showSource}
        >
          Markdown source
        </button>
      </div>
      {showRendered ? (
        <iframe
          ref={frame}
          className="report-view__frame"
          srcDoc={html}
          sandbox="allow-same-origin"
          title="Risk report"
          onLoad={resize}
          style={{ height }}
        />
      ) : (
        <pre className="markdown">{markdown}</pre>
      )}
    </div>
  )
}
