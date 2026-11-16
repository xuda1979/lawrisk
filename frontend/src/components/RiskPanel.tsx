import type { RiskReport } from '../types'

const LEVEL_COLOR: Record<string, string> = {
  low: 'var(--level-low)',
  medium: 'var(--level-med)',
  high: 'var(--level-high)',
}

function Gauge({ score, level }: { score: number; level: string }) {
  const hue = 120 - score * 1.2
  return (
    <div className="gauge" title={`Risk score ${score}/100 (${level})`}>
      <span className="gauge__value" style={{ color: LEVEL_COLOR[level] }}>{score}</span>
      <div className="gauge__track">
        <div
          className="gauge__fill"
          style={{ width: `${score}%`, background: `hsl(${hue} 70% 45%)` }}
        />
      </div>
      <span className={`badge badge--${level}`}>{level}</span>
    </div>
  )
}

export function RiskPanel({ title, report }: { title: string; report: RiskReport }) {
  return (
    <section className="risk-panel">
      <h3>{title}</h3>
      <Gauge score={report.overall_score} level={report.overall_level} />
      <p className="risk-summary">{report.summary}</p>

      <div className="dimensions">
        {report.dimensions.map((d) => (
          <div key={d.dimension} className="dimension">
            <div className="dimension__row">
              <span className="dimension__name">{d.dimension}</span>
              <span className={`badge badge--${d.risk_level}`}>{d.risk_level}</span>
            </div>
            <div className="dimension__bar">
              <div
                className="dimension__fill"
                style={{ width: `${d.normalized}%` }}
              />
            </div>
            <div className="dimension__meta">
              score {d.normalized.toFixed(0)}/100 · confidence {d.confidence.toFixed(2)}
            </div>
          </div>
        ))}
      </div>

      {report.penalties.length > 0 && (
        <details open className="findings">
          <summary>Findings ({report.penalties.length})</summary>
          <ul>
            {report.penalties.map((p, i) => (
              <li key={i} className="finding">
                <div className="finding__head">
                  <span className="finding__rule">{p.rule_id}</span>
                  <span className="finding__sev">+{p.severity}</span>
                  <span className="finding__dim">{p.dimension}</span>
                </div>
                <p className="finding__reason">{p.reason}</p>
                {p.excerpt && (
                  <blockquote className="finding__excerpt">“{p.excerpt}”</blockquote>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      <small className="hash" title="Deterministic SHA-256 of inputs + engine version">
        hash {report.deterministic_hash?.slice(0, 12)}…
      </small>
    </section>
  )
}
