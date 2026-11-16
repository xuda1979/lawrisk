import { useCallback, useEffect, useRef, useState } from 'react'
import './index.css'
import { compareFiles, health } from './api'
import { DiffTree } from './components/DiffTree'
import { DiffView } from './components/DiffView'
import { RiskPanel } from './components/RiskPanel'
import { TemplatesPanel } from './components/TemplatesPanel'
import type { CompareResult } from './types'

type Tab = 'diff' | 'tree' | 'report'

function FileDrop({
  label,
  file,
  onFile,
  accent,
}: {
  label: string
  file: File | null
  onFile: (f: File) => void
  accent: string
}) {
  const input = useRef<HTMLInputElement>(null)
  return (
    <label className={`drop drop--${accent}`}>
      <input
        ref={input}
        type="file"
        accept=".docx,.pdf,.txt"
        onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
      />
      <span className="drop__title">{label}</span>
      <span className="drop__hint">{file ? file.name : 'Click to choose DOCX / PDF / TXT'}</span>
    </label>
  )
}

export default function App() {
  const [a, setA] = useState<File | null>(null)
  const [b, setB] = useState<File | null>(null)
  const [result, setResult] = useState<CompareResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('diff')
  const [apiOk, setApiOk] = useState(false)
  const [llm, setLlm] = useState(false)

  useEffect(() => {
    health()
      .then((h) => {
        setApiOk(true)
        setLlm(h.llm_enabled)
      })
      .catch(() => setApiOk(false))
  }, [])

  const run = useCallback(async () => {
    if (!a || !b) {
      setError('Please choose both documents.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const res = await compareFiles(a, b)
      setResult(res)
      setTab('diff')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Compare failed')
    } finally {
      setBusy(false)
    }
  }, [a, b])

  const stats = result?.diff.stats

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>
            LawRisk <span className="sub">· contract risk + clause diff</span>
          </h1>
          <p className="header-hint">
            Explainable 0–100 risk score, per-dimension findings with source excerpts,
            and a paragraph-level diff tree — all computed locally.
          </p>
        </div>
        <div className="status">
          <span className={`dot ${apiOk ? 'dot--ok' : 'dot--bad'}`} />
          {apiOk ? 'API online' : 'API offline'}
          {llm && <span className="llm-flag">LLM summary on</span>}
        </div>
      </header>

      <div className="controls">
        <FileDrop label="Template A" file={a} onFile={setA} accent="a" />
        <span className="arrow">→</span>
        <FileDrop label="Template B" file={b} onFile={setB} accent="b" />
        <button className="run" onClick={run} disabled={busy || !a || !b}>
          {busy ? 'Comparing…' : 'Compare & score'}
        </button>
      </div>

      {error && <div className="error">{error}</div>}

      {result && (
        <div className="layout">
          <aside className="risk">
            <RiskPanel title="Template A" report={result.risk_a} />
            <RiskPanel title="Template B" report={result.risk_b} />
            <TemplatesPanel />
          </aside>

          <main className="content">
            <div className="tabs">
              <button className={tab === 'diff' ? 'active' : ''} onClick={() => setTab('diff')}>
                Side-by-side
              </button>
              <button className={tab === 'tree' ? 'active' : ''} onClick={() => setTab('tree')}>
                Diff tree
              </button>
              <button className={tab === 'report' ? 'active' : ''} onClick={() => setTab('report')}>
                Markdown report
              </button>
            </div>
            <div className="statline">
              <span className="stat stat--add">+{stats?.additions} added</span>
              <span className="stat stat--del">−{stats?.deletions} removed</span>
              <span className="stat stat--mod">~{stats?.modifications} modified</span>
            </div>
            {tab === 'diff' && <DiffView rows={result.rows} />}
            {tab === 'tree' && <DiffTree root={result.diff.root} />}
            {tab === 'report' && (
              <div>
                <a
                  className="download"
                  href={`data:text/markdown;charset=utf-8,${encodeURIComponent(result.markdown)}`}
                  download="lawrisk-diff-report.md"
                >
                  Download .md
                </a>
                <pre className="markdown">{result.markdown}</pre>
              </div>
            )}
          </main>
        </div>
      )}

      {!result && (
        <div className="hero">
          <h2>Two templates, one verdict.</h2>
          <p>
            Upload the same agreement from two vendors (or two versions) and get an
            explainable risk score plus a paragraph-level clause diff tree with
            semantic summaries — no cloud API, deterministic and reproducible.
          </p>
        </div>
      )}
    </div>
  )
}
