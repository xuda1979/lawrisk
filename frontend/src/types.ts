/// <reference types="vite/client" />
export interface Penalty {
  dimension: string
  reason: string
  rule_id: string
  severity: number
  excerpt?: string | null
  para_index?: number | null
  keyword?: string | null
  mitigation?: string | null
}

export interface DimensionScore {
  dimension: string
  risk_level: 'low' | 'medium' | 'high'
  raw_penalty: number
  normalized: number
  confidence: number
  reasons: string[]
}

export interface RiskReport {
  document_id: string
  overall_score: number
  overall_level: 'low' | 'medium' | 'high'
  dimensions: DimensionScore[]
  penalties: Penalty[]
  summary: string
  deterministic_hash: string
}

export interface DiffItem {
  op: 'add' | 'delete' | 'modify'
  section: string
  para_index_left?: number | null
  para_index_right?: number | null
  text_left?: string | null
  text_right?: string | null
  summary: string
}

export interface DiffStats {
  additions: number
  deletions: number
  modifications: number
}

export interface DiffNode {
  label: string
  children: DiffNode[]
  items: DiffItem[]
}

export interface DiffReportPayload {
  document_left: string
  document_right: string
  root: DiffNode
  stats: DiffStats
  summary: string
}

export interface RowRisk {
  rule_id: string
  dimension: string
  severity: number
  reason: string
  mitigation?: string | null
}

export interface AlignedRow {
  op: 'add' | 'delete' | 'modify'
  section: string
  leftIdx: number | null
  rightIdx: number | null
  leftText: string | null
  rightText: string | null
  summary: string
  leftRemoved: string[]
  rightAdded: string[]
  leftRisks?: RowRisk[]
  rightRisks?: RowRisk[]
  leftRiskSum?: number
  rightRiskSum?: number
}

export interface FieldRun {
  name: string
  value: string | null
  source: string | null
  para_index: number | null
  found: boolean
}

export interface CompareResult {
  diff: DiffReportPayload
  risk_a: RiskReport
  risk_b: RiskReport
  rows: AlignedRow[]
  markdown: string
  llm_enabled: boolean
  facts_a: FieldRun[]
  facts_b: FieldRun[]
}

export interface ClauseTemplate {
  id: string
  name: string
  description: string
  sections: string[]
  paragraph_count: number
  content_hash: string
}

export interface TemplateLibrary {
  templates: ClauseTemplate[]
  llm: { enabled: boolean; provider: string; deterministic: boolean }
}
