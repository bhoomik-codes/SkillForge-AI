import { ArrowDown, ArrowUpRight, MagnifyingGlass } from '@phosphor-icons/react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { api, errorText } from './api'
import type { Snapshot } from './api'

type HistoryRecord = Snapshot['history'][number]
type Evidence = { record: HistoryRecord; entities: string[]; actors: string[]; supersededBy: (HistoryRecord & { basis: string })[]; related: HistoryRecord[] }
type Context = { answer: string | null; confidence: string; mode: 'local' | 'neo4j' | 'fallback'; evidence: Evidence[] }
const label = (item: HistoryRecord) => item.label ?? 'PR #' + item.id

function RecordLink({ item }: { item: HistoryRecord }) {
  return item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.title} <ArrowUpRight size={14} /></a> : item.title
}

function RecordDetails({ item, actors }: { item: HistoryRecord; actors?: string[] }) {
  const names = actors ?? (item.actor ? [item.actor] : [])
  return <>
    <span className="eyebrow">{label(item)} {item.date?.slice(0, 10)} {names.map(name => ' · @' + name)}</span>
    <h4><RecordLink item={item} /></h4>
    {item.body && <p className="word-wrap">{item.body}</p>}
  </>
}

function markdownText(value: string) {
  return value.replace(/[\u0000-\u001f]/g, ' ').replace(/[\\[\]<>#*_]/g, character => '\\' + character).trim()
}

export function DecisionHistory({ snapshot, scanId, path, timeline = true }: {
  snapshot: Snapshot; scanId: string | null; path?: string; timeline?: boolean
}) {
  const [query, setQuery] = useState('')
  const [through, setThrough] = useState('')
  const [context, setContext] = useState<Context>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const displayed = snapshot.history.filter(item => !through || (item.date && item.date.slice(0, 10) <= through))
  const highestDate = snapshot.history.find(item => item.date)?.date?.slice(0, 10)

  async function ask(event: FormEvent) {
    event.preventDefault()
    setContext(undefined)
    setError('')
    setBusy(true)
    try {
      const endpoint = scanId ? '/scans/' + scanId + '/context' : '/sample/context'
      setContext(await api<Context>(endpoint, 'POST', {
        question: query.trim(), path, through: through || null, neo4j: true,
      }))
    } catch (error) { setError(errorText(error)) }
    finally { setBusy(false) }
  }

  function exportDraft() {
    if (!context) return
    const citations = new Map(context.evidence.flatMap(item => [item.record, ...item.supersededBy, ...item.related])
      .map(item => [item.id, item]))
    const content = [
      '# Architecture decision draft', '', '## Current question', markdownText(query || path || ''), '',
      '## Repository', markdownText(snapshot.repo + ' · ' + snapshot.revision), '', '## Cited context',
      ...[...citations.values()].flatMap(item => [
        '### ' + markdownText(label(item) + ' · ' + item.title),
        markdownText(item.body || 'This record has no written rationale.'),
        ...(item.url ? [item.url] : []), '',
      ]),
      '## Decision', 'Review the cited evidence and record the decision.', '',
      '## Consequences', 'Record trade-offs after review.',
    ].join('\n')
    const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'architecture-decision-draft.md'
    anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1500)
  }

  return <section className="panel history-panel" aria-label={timeline ? 'Decision history' : 'Scorecard history'}>
    <div className="split"><h3>{timeline ? 'Decision history' : 'History behind this finding'}</h3>
      {timeline && !!snapshot.history.length && <label className="history-date">Show through <input type="date"
        max={highestDate} value={through} disabled={busy} onChange={event => {
          setThrough(event.target.value); setContext(undefined); setError('')
        }} /></label>}
    </div>
    {path && <p className="mono word-wrap">{path}</p>}
    <p>{snapshot.sample ? 'Illustrative history for the sample project.' : 'Evidence from a bounded sample of public GitHub history.'}</p>
    {!snapshot.history_available && <p role="status">GitHub history is unavailable for this scan.</p>}
    {snapshot.history_available && !displayed.length && <p>No history records in this date range.</p>}
    {!!snapshot.history.length && <form onSubmit={ask}>
      <div className="history-search">
        <label className="search-field"><MagnifyingGlass size={16} /><input aria-label="Ask about repository history" value={query}
          disabled={busy} onChange={event => { setQuery(event.target.value); setContext(undefined); setError('') }}
          maxLength={200} placeholder={path ? 'Ask why this file changed (optional)'
            : snapshot.sample ? 'Why sort routes by zone before dispatch?' : 'Why was this module introduced?'}
          required={!path} /></label>
        <button disabled={busy} className="button primary">{busy ? 'Reading history…' : 'Find evidence'}</button>
      </div>

    </form>}
    {error && <p role="status">{error}</p>}
    {context && <section className="history-results" aria-label="Question evidence" aria-live="polite">
      <div className="split"><h4>Historical evidence</h4>
        {!!context.evidence.length && <button className="button compact" onClick={exportDraft}><ArrowDown size={15} /> Export decision draft</button>}</div>
      <p>{context.mode === 'neo4j' ? 'Retrieved through Neo4j'
        : context.mode === 'fallback' ? 'Neo4j is unavailable. Retrieved through the local graph.'
          : 'This snapshot has no records available for Neo4j traversal.'} · {context.confidence} confidence</p>
      <p>{context.answer ? <>Recorded rationale “{context.answer}” · <RecordLink item={context.evidence[0].record} /></>
        : 'The indexed history cannot establish why this decision was made.'}</p>
      {context.evidence.map(item => <article key={item.record.id}>
        <RecordDetails item={item.record} actors={item.actors} />
        {!!item.entities.length && <p className="word-wrap">Linked code · {item.entities.join(', ')}</p>}
        {item.related.length > 0 && <ul aria-label="Linked discussion and records">{item.related.map(related =>
          <li key={related.id}><RecordLink item={related} /> · {label(related)} {related.date?.slice(0, 10)}</li>)}</ul>}
        {item.supersededBy.map(later => <div key={later.id + later.basis}><p>Superseded · {later.basis}</p>
          <RecordDetails item={later} /></div>)}
      </article>)}
    </section>}
    {timeline && <><h4>Timeline</h4>{displayed.map(item => <article key={item.id}><RecordDetails item={item} /></article>)}</>}
  </section>
}
