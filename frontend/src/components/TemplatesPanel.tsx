import { useEffect, useState } from 'react'
import { listTemplates } from '../api'
import type { ClauseTemplate } from '../types'

export function TemplatesPanel() {
  const [templates, setTemplates] = useState<ClauseTemplate[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listTemplates()
      .then((lib) => setTemplates(lib.templates))
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load templates'))
  }, [])

  if (error) return <div className="error">{error}</div>

  return (
    <section className="risk-panel">
      <h3>Template library</h3>
      <p className="risk-summary">
        Bundled baseline clause sets for diffing an incoming agreement against a
        known-good structure (P3).
      </p>
      {templates.length === 0 ? (
        <p className="risk-summary">Loading…</p>
      ) : (
        <ul className="tpl-list">
          {templates.map((t) => (
            <li key={t.id} className="tpl">
              <div className="tpl__head">
                <span className="tpl__name">{t.name}</span>
                <code className="tpl__id">{t.id}</code>
              </div>
              <p className="tpl__desc">{t.description}</p>
              <div className="tpl__meta">
                {t.paragraph_count} paragraphs ·{' '}
                {t.sections.map((s) => (
                  <span key={s} className="tpl__section">
                    {s}
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
