
export type Session = { login: string | null; oauth: boolean; ai: boolean; judge: boolean; voice?: boolean }
export type Node = { id: string; label: string; kind: string; path: string | null; line: number | null }
export type Edge = { source: string; target: string; kind: string; path: string; line: number | null }
export type Citation = { title: string; detail: string; path: string | null; line: number | null; url: string | null }
export type Finding = Citation & { dimension: string; points: number | null; max: number; state: 'met' | 'review' | 'unmeasured'; severity?: string }
export type Coverage = { analyzed: number; eligible: number; percent: number; total: number; truncated: boolean }
export type Criterion = { id: string; name: string; relevance: 'applicable' | 'not_applicable' | 'uncertain'; reason: string
  proposedWeight: number; evidence: Pick<Citation, 'path' | 'line' | 'url'> | null }
export type ScoreSummary = { score: number | null; rankable: boolean; cohort: string | null; version: string; coverage: Coverage
  scale?: number; archetype?: string; grade?: string | null; comparisonKey?: string }
export type Quality = ScoreSummary & { dimensions: { name: string; points: number; max: number; weight?: number }[]; findings: Finding[]
  criteria?: Criterion[]; confidence?: string; evaluationCoverage?: number; severityCap?: number | null
  review?: { expected: string[]; note: string } | null; features?: { name: string; evidence: Criterion['evidence'] }[] }
export type Snapshot = {
  repo: string; branch: string; revision: string; description: string; language: string | null; sample: boolean
  graph: { nodes: Node[]; edges: Edge[]; unresolved: number; limited: boolean }
  quality: Quality
  history: { id: number | string; label?: string; title: string; body: string; date: string | null; url?: string; actor?: string }[]
  history_available: boolean
  preview_paths: string[]
  review?: { mode: 'reviewed' | 'unavailable'; model?: string; findings: Citation[]; context?: Citation[] }
}
export type Scan = {
  id: string; repo: string; state: 'queued' | 'running' | 'review' | 'complete' | 'failed'; created: number; updated: number
  revision?: string; knowledgeReady?: boolean; summary?: ScoreSummary; result?: Snapshot | { error: string; retryAt?: number }
}
export type Repository = { name: string; description: string | null; language: string | null }
export type Source = { path: string; source: string; url: string | null }

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const result = await fetch('/api' + path, {
    method, credentials: 'same-origin',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!result.ok) {
    const error = await result.json().catch(() => ({}))
    throw new Error(typeof error.detail === 'string' ? error.detail : 'The request could not be completed.')
  }
  return result.status === 204 ? undefined as T : result.json()
}

export const pending = (scan: Scan) => scan.state === 'queued' || scan.state === 'running'
export const errorText = (error: unknown) => error instanceof Error ? error.message : 'Something went wrong.'
