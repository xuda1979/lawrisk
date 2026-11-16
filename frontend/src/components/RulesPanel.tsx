import { useEffect, useMemo, useState } from 'react'
import { fetchRules } from '../api'
import type { RuleInfo } from '../types'

const DIM_LABELS: Record<string, string> = {
  commercial: 'Commercial',
  liability: 'Liability',
  data: 'Data protection',
  export: 'Export compliance',
}

const DIM_ORDER = ['commercial', 'liability', 'data', 'export']

function RuleCard({ rule }: { rule: RuleInfo }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="rule">
      <div className="rule__head">
        <code className="rule__id">{rule.rule_id}</code>
        <span
          className={`badge ${rule.kind === 'absence' ? 'badge--medium' : rule.severity >= 20 ? 'badge--high' : 'badge--low'}`}
        >
          {rule.kind === 'absence' ? 'absence' : `sev ${rule.severity}`}
        </span>
      </div>
      <p className="rule__desc">{rule.description}</p>
      <div className="rule__meta">
        <span className="rule__dim">{DIM_LABELS[rule.dimension] ?? rule.dimension}</span>
        {rule.has_condition && <span className="rule__tag">conditional</span>}
        {rule.has_exclusion && <span className="rule__tag">carveout</span>}
      </div>
      <button className="rule__toggle" onClick={() => setOpen((v) => !v)}>
        {open ? '− hide details' : '+ why & fix'}
      </button>
      {open && (
        <div className="rule__details">
          <p className="rule__reason">
            <strong>Why it fires:</strong> {rule.reason}
          </p>
          <p className="rule__mitigation">
            <strong>Mitigation:</strong> {rule.mitigation}
          </p>
          <details className="rule__pattern">
            <summary>Pattern source</summary>
            <pre>{rule.pattern ?? '(absence rule — no literal pattern)'}</pre>
            {rule.condition && (
              <>
                <div className="rule__pattern-label">Condition</div>
                <pre>{rule.condition}</pre>
              </>
            )}
          </details>
        </div>
      )}
    </li>
  )
}

export function RulesPanel() {
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading')
  const [rules, setRules] = useState<RuleInfo[]>([])
  const [engine, setEngine] = useState('')
  const [filter, setFilter] = useState<'all' | 'paragraph' | 'absence'>('all')
  const [query, setQuery] = useState('')

  useEffect(() => {
    let active = true
    fetchRules()
      .then((cat) => {
        if (!active) return
        setRules(cat.rules)
        setEngine(cat.engine)
        setPhase('ready')
      })
      .catch((e) => {
        if (!active) return
        setPhase('error')
        console.error(e)
      })
    return () => {
      active = false
    }
  }, [])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return rules
      .filter((r) => filter === 'all' || r.kind === filter)
      .filter((r) => {
        if (!q) return true
        return [r.rule_id, r.dimension, r.reason, r.mitigation, r.description ?? '']
          .join(' ')
          .toLowerCase()
          .includes(q)
      })
      .sort(
        (a, b) =>
          DIM_ORDER.indexOf(a.dimension) - DIM_ORDER.indexOf(b.dimension) ||
          a.rule_id.localeCompare(b.rule_id),
      )
  }, [rules, filter, query])

  if (phase === 'loading') return <div className="rule-hint">Loading rule handbook…</div>
  if (phase === 'error') return <div className="rule-hint error">Rule handbook unavailable.</div>

  return (
    <section className="risk-panel">
      <h3>Rule handbook</h3>
      <p className="risk-summary">
        Every deterministic rule behind the score{engine ? ` — ${engine}` : ''}. Click a
        rule for why it fires and how to fix it. Opaque finding ids like R-COMM-8
        resolve here.
      </p>
      <label className="rule-search">
        <input
          type="search"
          placeholder="Search rules (id, dimension, reason)…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      <div className="rule-filters">
        {(['all', 'paragraph', 'absence'] as const).map((k) => (
          <button
            key={k}
            className={filter === k ? 'active' : ''}
            onClick={() => setFilter(k)}
          >
            {k === 'all' ? `All (${rules.length})` : `${k} (${rules.filter((r) => r.kind === k).length})`}
          </button>
        ))}
      </div>
      <ul className="rule-list">
        {visible.map((r) => (
          <RuleCard key={r.rule_id} rule={r} />
        ))}
      </ul>
      {visible.length === 0 && <p className="rule-hint">No rules match “{query}”.</p>}
    </section>
  )
}
