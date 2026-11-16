import type { ReviewResult } from '../types'

const RISK_COLOR = (level: string) =>
  level === 'high' ? 'var(--level-high)' : level === 'medium' ? 'var(--level-med)' : 'var(--level-low)'

export function ReviewView({ review }: { review: ReviewResult }) {
  const sections = review.sections

  if (sections.length === 0) {
    return (
      <p className="empty">
        No risk findings — this document scored clean.
      </p>
    )
  }

  return (
    <div className="review">
      {sections.map((s) => (
        <section key={s.heading} className="review-section">
          <h3 className="review-section__head">
            <span className="pill pill--modify">{s.heading}</span>
            <span className="review-section__meta">
              {s.findings.length} finding{s.findings.length === 1 ? '' : 's'} · {s.total_risk} risk pts
            </span>
          </h3>
          <ul className="review-list">
            {s.findings.map((f, i) => (
              <li key={i} className="review-finding">
                <div className="review-finding__head">
                  <span className="pill pill--modify">{f.rule_id}</span>
                  <span className="review-finding__sev" style={{ color: RISK_COLOR(f.severity >= 30 ? 'high' : f.severity >= 15 ? 'medium' : 'low') }}>
                    +{f.severity}
                  </span>
                  <span className="review-finding__dim">{f.dimension}</span>
                </div>
                <p className="review-finding__reason">{f.reason}</p>
                {f.excerpt && (
                  <blockquote className="finding__excerpt">“{f.excerpt}”</blockquote>
                )}
                {f.mitigation && (
                  <p className="finding__mitigation">
                    <span className="finding__mitigation-label">Fix:</span> {f.mitigation}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
