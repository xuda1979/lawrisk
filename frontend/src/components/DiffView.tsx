import { useMemo, useState } from 'react'
import type { AlignedRow, RowRisk } from '../types'

const OP_LABEL: Record<string, string> = {
  add: 'added',
  delete: 'deleted',
  modify: 'modified',
}

function RiskChip({ side, risks }: { side: 'A' | 'B'; risks: RowRisk[] }) {
  if (risks.length === 0) return null
  const sum = risks.reduce((acc, r) => acc + r.severity, 0)
  return (
    <span className={`risk-chip risk-chip--${sum >= 50 ? 'high' : 'med'}`} title={risks.map((r) => `${r.rule_id}: ${r.reason}`).join('\n')}>
      <svg
        className="risk-chip__icon"
        width="9"
        height="9"
        viewBox="0 0 10 10"
        aria-hidden="true"
      >
        <path d="M5 0 L10 9 L0 9 Z" fill="currentColor" />
      </svg>
      {side} +{sum} pts
      <span className="risk-chip__rules">{risks.map((r) => r.rule_id).join(' ')}</span>
    </span>
  )
}

function diffMeta(row: AlignedRow) {
  const l = row.leftRisks ?? []
  const r = row.rightRisks ?? []
  return (
    <>
      <RiskChip side="A" risks={l} />
      <RiskChip side="B" risks={r} />
      <span className={`pill pill--${row.op}`}>{OP_LABEL[row.op]}</span>
      <em>{row.summary}</em>
    </>
  )
}

function inline(text: string | null, mark: string[], op: string) {
  if (!text) return null
  if ((op !== 'modify' && op !== 'delete' && op !== 'add') || mark.length === 0) {
    return <>{text}</>
  }
  const words = text.split(/(\s+)/)
  return words.map((w, i) =>
    mark.includes(w.trim()) ? (
      <mark key={i} className={op === 'delete' ? 'hl-removed' : 'hl-added'}>
        {w}
      </mark>
    ) : (
      <span key={i}>{w}</span>
    ),
  )
}

function Side({ title, text, mark, op }: { title: string; text: string | null; mark: string[]; op: string }) {
  return (
    <div className={`side side--${op}`}>
      <div className="side__title">{title}</div>
      <p className="side__text">{inline(text, mark, op)}</p>
    </div>
  )
}

const OPS = ['add', 'delete', 'modify'] as const
type OpFilter = (typeof OPS)[number] | 'all'

function hasRisk(r: AlignedRow) {
  return ((r.leftRisks?.length ?? 0) + (r.rightRisks?.length ?? 0)) > 0
}

export function DiffView({
  rows,
  left,
  right,
}: {
  rows: AlignedRow[]
  left: string
  right: string
}) {
  const bySection = useMemo(() => {
    const map = new Map<string, AlignedRow[]>()
    for (const r of rows) {
      const arr = map.get(r.section) ?? []
      arr.push(r)
      map.set(r.section, arr)
    }
    return Array.from(map.entries())
  }, [rows])

  const [active, setActive] = useState<string>('all')
  const [opType, setOpType] = useState<OpFilter>('all')
  const [riskyOnly, setRiskyOnly] = useState(false)

  if (rows.length === 0) {
    return <div className="empty">No differences detected between the two documents.</div>
  }

  const shown = (active === 'all' ? bySection : bySection.filter(([s]) => s === active)).flatMap(
    ([section, items]) => {
      const filtered = items.filter(
        (r) => (opType === 'all' || r.op === opType) && (!riskyOnly || hasRisk(r)),
      )
      return filtered.length ? [[section, filtered] as const] : []
    },
  )

  return (
    <div className="diff-view">
      <div className="section-filter">
        <button
          className={active === 'all' ? 'active' : ''}
          onClick={() => setActive('all')}
        >
          All sections
        </button>
        {bySection.map(([section]) => (
          <button
            key={section}
            className={active === section ? 'active' : ''}
            onClick={() => setActive(section)}
          >
            {section}
          </button>
        ))}
      </div>
      <div className="section-filter">
        <button
          className={opType === 'all' ? 'active' : ''}
          onClick={() => setOpType('all')}
        >
          All changes
        </button>
        {OPS.map((op) => (
          <button
            key={op}
            className={opType === op ? 'active' : ''}
            onClick={() => setOpType(op)}
          >
            {OP_LABEL[op]}
          </button>
        ))}
        <span className="op-filter__spacer" />
        <button
          className={riskyOnly ? 'active risky-filter' : 'risky-filter'}
          onClick={() => setRiskyOnly((v) => !v)}
          title="Show only changed clauses that carry risk penalties"
        >
          ⚠ Risky only
        </button>
      </div>
      {shown.map(([section, items]) => (
        <section key={section} className="diff-section">
          <h4>{section}</h4>

          {items.map((row, idx) => (
            <div key={idx} className={`diff-row diff-row--${row.op}`}>
              <div className="diff-grid">
                <Side
                  title={left}
                  text={row.op === 'add' ? null : row.leftText}
                  mark={row.leftRemoved}
                  op={row.op}
                />
                <Side
                  title={right}
                  text={row.op === 'delete' ? null : row.rightText}
                  mark={row.rightAdded}
                  op={row.op}
                />
              </div>
              <div className="diff-meta">
                {diffMeta(row)}
              </div>
            </div>
          ))}
        </section>
      ))}
    </div>
  )
}
