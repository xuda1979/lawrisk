import type { FieldRun } from '../types'

const FACT_LABEL: Record<string, string> = {
  currency: 'Currency',
  term: 'Term',
  governing_law: 'Governing law',
  arbitration: 'Arbitration seat',
}

export function FactsPanel({ title, facts }: { title: string; facts: FieldRun[] }) {
  const known = facts.filter((f) => f.name in FACT_LABEL)
  const other = facts.filter((f) => !(f.name in FACT_LABEL))

  return (
    <section className="risk-panel">
      <h3>{title} · key facts</h3>
      {known.length === 0 && other.length === 0 ? (
        <p className="risk-summary">No key fields detected in this document.</p>
      ) : (
        <ul className="facts">
          {known.map((f, i) => (
            <li key={i} className="fact">
              <span className="fact__label">{FACT_LABEL[f.name]}</span>
              <span className="fact__value">{f.value}</span>
              <span className="fact__src">“{f.source}”</span>
            </li>
          ))}
          {other.map((f, i) => (
            <li key={`o-${i}`} className="fact">
              <span className="fact__label">{f.name}</span>
              <span className="fact__value">{f.value}</span>
              <span className="fact__src">“{f.source}”</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
