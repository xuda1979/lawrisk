import { useEffect, useRef, useState } from 'react'
import { compareWithTemplate as apiCompareWithTemplate, listTemplates } from '../api'
import type { ClauseTemplate, CompareResult } from '../types'

export function TemplatesPanel({
  onCompare,
}: {
  onCompare: (result: CompareResult) => void
}) {
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading')
  const [templates, setTemplates] = useState<ClauseTemplate[]>([])
  const [selected, setSelected] = useState<ClauseTemplate | null>(null)
  const [document, setDocument] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let active = true
    listTemplates()
      .then((lib) => {
        if (!active) return
        setTemplates(lib.templates)
        setSelected(lib.templates[0] ?? null)
        setPhase('ready')
      })
      .catch((e) => {
        if (!active) return
        setError(e instanceof Error ? e.message : 'Failed to load templates')
        setPhase('error')
      })
    return () => {
      active = false
    }
  }, [])

  const run = async () => {
    if (!selected || !document) {
      setError('Choose a baseline and a document first.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const res = await apiCompareWithTemplate(selected.id, document, document.name)
      onCompare(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Template compare failed')
    } finally {
      setBusy(false)
    }
  }

  if (phase === 'error') return <div className="error">{error}</div>

  return (
    <section className="risk-panel">
      <h3>Compare vs baseline</h3>
      <p className="risk-summary">
        Diff one document against a bundled baseline clause set, with both sides
        scored.
      </p>
      <div className="tpl-form">
        <select
          className="tpl-select"
          value={selected?.id ?? ''}
          onChange={(e) => setSelected(templates.find((t) => t.id === e.target.value) ?? null)}
        >
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} ({t.id})
            </option>
          ))}
        </select>
        <label className="drop drop--b">
          <input
            ref={input}
            type="file"
            accept=".docx,.pdf,.txt"
            onClick={(e) => {
              e.currentTarget.value = ''
            }}
            onChange={(e) => e.target.files?.[0] && setDocument(e.target.files[0])}
          />
          <span className="drop__title">Document</span>
          <span className="drop__hint">{document ? document.name : 'Click to choose DOCX / PDF / TXT'}</span>
        </label>
        <button className="run" onClick={run} disabled={busy || !selected || !document}>
          {busy ? 'Comparing…' : 'Compare vs baseline'}
        </button>
      </div>
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
    </section>
  )
}
