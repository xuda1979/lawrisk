import type { RiskReport } from '../types'

const LEVEL_LABEL: Record<string, string> = { low: 'LOW', medium: 'MEDIUM', high: 'HIGH' }
const DIM_LABEL: Record<string, string> = {
  commercial: 'Commercial',
  liability: 'Liability',
  data: 'Data protection',
  export: 'Export compliance',
}

function dimLabel(name: string) {
  return DIM_LABEL[name] ?? name
}

export function VerdictBanner({
  titleA,
  reportA,
  titleB,
  reportB,
}: {
  titleA: string
  reportA: RiskReport
  titleB: string
  reportB: RiskReport
}) {
  const a = reportA.overall_score
  const b = reportB.overall_score

  // Levels are monotonic with score, so comparing them picks the riskier doc.
  let verdict: string
  let tone: string

  if (a === b) {
    tone = 'tie'
    verdict = `Both documents score ${a} (${LEVEL_LABEL[reportA.overall_level]}) — a tie on risk. Decide on the clause diff below or on non-risk terms.`
  } else if (a > b) {
    tone = 'riskier-a'
    verdict = `${titleA} (${a} ${LEVEL_LABEL[reportA.overall_level]}) scores riskier than ${titleB} (${b} ${LEVEL_LABEL[reportB.overall_level]}) — ${a - b} point gap. ${b <= 33 ? 'Template B stays low risk.' : 'Prefer the lower-scoring document on this axis.'}`
  } else {
    tone = 'riskier-b'
    verdict = `${titleB} (${b} ${LEVEL_LABEL[reportB.overall_level]}) scores riskier than ${titleA} (${a} ${LEVEL_LABEL[reportA.overall_level]}) — ${b - a} point gap. ${a <= 33 ? 'Template A stays low risk.' : 'Prefer the lower-scoring document on this axis.'}`
  }

  // Per-dimension comparison — name the axis that drives the overall gap.
  const dims = reportA.dimensions
    .map((da) => {
      const db = reportB.dimensions.find((d) => d.dimension === da.dimension)
      return db ? { name: da.dimension, a: da.normalized, b: db.normalized } : null
    })
    .filter((d): d is { name: string; a: number; b: number } => d !== null)
  const topGap = dims.length
    ? Math.max(...dims.map((d) => Math.abs(d.b - d.a)))
    : 0
  const top = topGap > 0
    ? dims.find((d) => Math.abs(d.b - d.a) === topGap) ?? null
    : null

  return (
    <>
      <div className={`verdict verdict--${tone}`}>
        <span className="verdict__tag">Verdict</span>
        <span className="verdict__text">{verdict}</span>
      </div>

      {dims.length > 0 && (
        <div className="drivers">
          <div className="drivers__head">
            Risk drivers
            <small>per-dimension score A → B (score 0–100)</small>
          </div>
          <div className="drivers__grid">
            {dims.map((d) => {
              const delta = d.b - d.a
              const isTop = top !== null && d.name === top.name && delta !== 0
              const dir = delta > 0 ? 'up' : delta < 0 ? 'down' : ''
              return (
                <div key={d.name} className={`driver${isTop ? ' driver--top' : ''}`}>
                  <span className="driver__name">{dimLabel(d.name)}</span>
                  <span className="driver__score">{d.a.toFixed(0)}</span>
                  <span className="driver__arrow">→</span>
                  <span className="driver__score">{d.b.toFixed(0)}</span>
                  <span className={`driver__delta driver__delta--${dir}`}>
                    {delta > 0 ? '+' : ''}{delta.toFixed(0)}
                  </span>
                  {isTop && <span className="driver__flag">biggest gap</span>}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </>
  )
}
