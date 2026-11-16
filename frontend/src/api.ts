import type { CompareResult, ReviewResult, RuleCatalog, TemplateLibrary } from './types'

const API = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export async function compareFiles(a: File, b: File): Promise<CompareResult> {
  const form = new FormData()
  form.append('template_a', a)
  form.append('template_b', b)
  form.append('name_a', a.name || 'Template A')
  form.append('name_b', b.name || 'Template B')
  const res = await fetch(`${API}/api/compare`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Compare failed (${res.status})`)
  return res.json()
}

export async function reviewFile(file: File, name: string): Promise<ReviewResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('name', name || file.name || 'Document')
  const res = await fetch(`${API}/api/review`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Review failed (${res.status})`)
  return res.json()
}

export async function health(): Promise<{ status: string; llm_enabled: boolean }> {
  const res = await fetch(`${API}/api/health`)
  if (!res.ok) throw new Error('API unreachable')
  return res.json()
}

export async function listTemplates(): Promise<TemplateLibrary> {
  const res = await fetch(`${API}/api/templates`)
  if (!res.ok) throw new Error('Template library unavailable')
  return res.json()
}

export async function fetchRules(): Promise<RuleCatalog> {
  const res = await fetch(`${API}/api/rules`)
  if (!res.ok) throw new Error('Rule handbook unavailable')
  return res.json()
}

export async function compareWithTemplate(
  templateId: string,
  document: File,
  name: string,
): Promise<CompareResult> {
  const form = new FormData()
  form.append('document', document)
  form.append('name', name || 'Document')
  const res = await fetch(`${API}/api/templates/${templateId}/compare`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) throw new Error(`Template compare failed (${res.status})`)
  return res.json()
}
