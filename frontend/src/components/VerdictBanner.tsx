import type { RiskReport } from '../types'

const LEVEL_LABEL: Record<string, string> = { low: 'LOW', medium: 'MEDIUM', high: 'HIGH' }

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

  return (
    <div className={`verdict verdict--${tone}`}>
      <span className="verdict__tag">Verdict</span>
      <span className="verdict__text">{verdict}</span>
    </div>
  )
}
