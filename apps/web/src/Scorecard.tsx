import { DecisionHistory } from './DecisionHistory'

import { ArrowDown, ArrowUpRight, CheckCircle, CircleDashed, MagnifyingGlass, Sparkle, WarningCircle } from '@phosphor-icons/react'
import { useState } from 'react'
import type { Finding, Scan, Snapshot } from './api'
import { RubricCriteria } from './RubricPreview'
import './scorecard.css'

type Filter = 'review' | 'unmeasured' | 'all'
const format = new Intl.NumberFormat()

function lost(finding: Finding) {
  return finding.points == null ? 0 : finding.max - finding.points
}

function Status({ finding }: { finding: Finding }) {
  return <span className={'finding-status ' + (finding.severity === 'critical' ? 'critical' : finding.state)}>
    {finding.severity === 'critical' ? 'Critical' : finding.state === 'review' ? 'Review'
      : finding.state === 'met' ? 'Met' : 'Unmeasured'}
  </span>
}

function Metric({ name, value, detail, percent, tone }: {
  name: string; value: string; detail: string; percent?: number; tone: string
}) {
  return <article className="score-metric"><h3>{name}</h3><strong>{value}</strong>
    {percent != null && <progress className={tone} value={percent} max={100} aria-label={name} />}
    <p>{detail}</p>
  </article>
}

export function Scorecard({ snapshot, scanId, previous, comparable, onCompare, onPractice }: {
  snapshot: Snapshot; scanId: string | null; previous?: Scan; comparable: Scan[]; onCompare: (scan?: Scan) => void; onPractice: (id: string) => void
}) {
  const quality = snapshot.quality
  const [filter, setFilter] = useState<Filter>('review')
  const [contextFinding, setContextFinding] = useState<Finding>()
  const delta = previous?.summary?.score != null && quality.score != null ? quality.score - previous.summary.score : null
  const ordered = [...quality.findings].sort((a, b) => Number(b.severity === 'critical') - Number(a.severity === 'critical') ||
    Number(a.state === 'met') - Number(b.state === 'met') || lost(b) - lost(a))
  const needsReview = ordered.filter(item => item.state === 'review')
  const notMeasured = ordered.filter(item => item.state === 'unmeasured')
  const rows = filter === 'review' ? needsReview : filter === 'unmeasured' ? notMeasured : ordered
  const max = quality.scale ?? 100
  const percent = quality.score == null ? 0 : quality.score / max
  const scoreTone = quality.score == null ? '#65748a' : percent >= .8 ? '#74e4bb' : percent >= .6 ? '#f6ba72' : '#f6998d'

  return <div className="report">
    <section className="score-sheet" aria-label="Engineering score summary">
      <header className="score-sheet-head">
        <div><h3>{quality.archetype ? 'Engineering score' : 'Legacy quality score'}</h3>
          <p>{[quality.archetype, quality.cohort].filter(Boolean).join(' · ')}</p></div>
        <span className={'score-eligibility' + (quality.rankable ? ' ranked' : '')}>
          {quality.rankable ? <CheckCircle size={15} /> : <CircleDashed size={15} />}
          {quality.rankable ? 'Eligible for rankings' : 'Unranked'}
        </span>
      </header>
      <div className="score-sheet-body">
        <div className="score-dial">
          <div className="score-ring" aria-hidden="true" style={{
            background: 'conic-gradient(from 225deg, ' + scoreTone + ' ' + (percent * 270) + 'deg, #364963 ' +
              (percent * 270) + 'deg 270deg, transparent 270deg)',
          }} />
          <div className="score-dial-text">
            <strong>{quality.score == null ? '—' : format.format(quality.score)}</strong>
            <span>out of {format.format(max)}</span>
            {quality.grade && <small style={{ color: scoreTone }}>Grade {quality.grade}</small>}
          </div>
        </div>
        <div className="score-priorities">
          <h4>What needs attention</h4>
          {needsReview.length ? needsReview.slice(0, 3).map(item => <div className="score-priority" key={item.title}>
            <Status finding={item} />
            <div><strong>{item.title}</strong><small>{item.path ? item.path + (item.line ? ':' + item.line : '') : item.dimension}</small>
              <progress value={lost(item)} max={item.max || 1} aria-label={item.title + ' points lost'} /></div>
            <span>−{lost(item)} pts</span>
          </div>) : <p>{notMeasured.length ? 'No deductions recorded. Some checks are still unmeasured.' : 'No deductions in the measured checks.'}</p>}
          {quality.severityCap != null && <p className="score-cap">A severe finding capped the score at {quality.severityCap}.</p>}
        </div>
      </div>
      <footer className="score-sheet-foot">
        <span className="mono">{quality.version} · {snapshot.revision.slice(0, 12)}</span>
        <a href="#score-evidence" onClick={() => { setFilter('review'); setContextFinding(undefined) }}>Review evidence <ArrowDown size={14} /></a>
      </footer>
    </section>

    <div className="score-metrics">
      <Metric name="Source coverage" value={quality.coverage.percent + '%'} percent={quality.coverage.percent} tone="blue"
        detail={quality.coverage.analyzed + ' of ' + quality.coverage.eligible + ' eligible files analyzed'} />
      <Metric name="Rubric measured" value={quality.evaluationCoverage == null ? '—' : quality.evaluationCoverage + '%'}
        percent={quality.evaluationCoverage} tone="mint" detail="Share of relevant scoring weight verified by checks" />
      <Metric name="Static confidence" value={quality.confidence ?? '—'} tone="amber"
        detail={quality.rankable ? 'Clears the current evidence requirements' : 'Coverage or rubric review limits this result'} />
    </div>
    {(comparable.length > 0 || quality.review?.note) && <section className="panel score-context">
      {quality.review?.note && <p>Open context question · {quality.review.note}</p>}
      {!!comparable.length && <label className="comparison">Compare revision <select value={previous?.id ?? ''} onChange={event =>
        onCompare(comparable.find(scan => scan.id === event.target.value))}>
        <option value="">Select revision</option>{comparable.map(scan => <option key={scan.id} value={scan.id}>
          {scan.revision?.slice(0, 7)} · {new Date(scan.created * 1000).toLocaleDateString()}
        </option>)}
      </select>{delta !== null && <strong>{delta > 0 ? '+' : ''}{delta} points</strong>}</label>}
    </section>}

    <section className="panel findings" id="score-evidence">
      <div className="score-evidence-head">
        <div><h3>Evidence and next steps</h3><p>Findings from the sampled revision.</p></div>
        <div className="score-filters" role="group" aria-label="Filter findings">
          <button className="button compact" aria-pressed={filter === 'review'} onClick={() => { setFilter('review'); setContextFinding(undefined) }}>Needs review <span>{needsReview.length}</span></button>
          <button className="button compact" aria-pressed={filter === 'unmeasured'} onClick={() => { setFilter('unmeasured'); setContextFinding(undefined) }}>Unmeasured <span>{notMeasured.length}</span></button>
          <button className="button compact" aria-pressed={filter === 'all'} onClick={() => { setFilter('all'); setContextFinding(undefined) }}>All <span>{ordered.length}</span></button>
        </div>
      </div>
      {!rows.length && <p className="score-evidence-empty">No findings match this filter.</p>}
      {rows.map(finding => <article key={JSON.stringify([finding.title, finding.dimension, finding.path, finding.line])}>
        <div className="finding-icon">{finding.state === 'met' ? <CheckCircle size={21} />
          : finding.state === 'review' ? <WarningCircle size={21} /> : <MagnifyingGlass size={21} />}</div>
        <div><h4>{finding.title}</h4><p>{finding.detail}</p>
          {finding.path && <small className="mono word-wrap">{finding.url && !snapshot.sample
            ? <a href={finding.url} target="_blank" rel="noreferrer">{finding.path}:{finding.line} <ArrowUpRight size={13} /></a>
            : finding.path + ':' + finding.line}</small>}
          {finding.path && snapshot.preview_paths.includes(finding.path) &&
            <button className="text-button" aria-expanded={contextFinding === finding}
              onClick={() => setContextFinding(contextFinding === finding ? undefined : finding)}>
              Inspect file history
            </button>}
          {finding.state === 'review' && ['Performance hygiene', 'Performance'].includes(finding.dimension) &&
            <button className="text-button" onClick={() => onPractice('load-monitor')}>Practice efficient processing</button>}
          {finding.state === 'review' && ['Test files are present', 'Assertions in sampled tests'].includes(finding.title) &&
            <button className="text-button" onClick={() => onPractice('support-coverage')}>Practice boundary cases</button>}
        </div>
        <div className="evidence-points"><Status finding={finding} />
          {finding.points != null && <small>{finding.points}/{finding.max} points</small>}</div>
        {contextFinding === finding && finding.path && <div className="finding-history">
          <DecisionHistory snapshot={snapshot} scanId={scanId} path={finding.path} timeline={false} />
        </div>}
      </article>)}
    </section>

    <details className="panel score-details">
      <summary>Score by dimension</summary>
      <div className="dimensions">{quality.dimensions.map(dimension => <div key={dimension.name}>
        <div className="split"><span>{dimension.name}</span><strong>
          {dimension.max ? dimension.points + '/' + dimension.max : 'Unmeasured'}
        </strong></div>
        <progress value={dimension.points} max={dimension.max || 1} aria-label={dimension.name} />
      </div>)}</div>
    </details>
    {quality.criteria && <details className="panel score-details">
      <summary>Project rubric</summary><RubricCriteria criteria={quality.criteria} />
    </details>}
    {snapshot.review && <section className="panel findings">
      <h3><Sparkle size={19} /> Optional Gemini review</h3>
      {snapshot.review.mode === 'unavailable' && <p>Gemini was unavailable. The static report is ready.</p>}
      {snapshot.review.mode === 'reviewed' && !snapshot.review.findings.length && <p>No cited additional findings returned.</p>}
      {Object.keys(snapshot.review.historySources ?? {}).length > 0 && <details>
        <summary>Commit history coverage</summary>
        <ul>{Object.entries(snapshot.review.historySources ?? {}).map(([path, source]) => <li key={path}>
          {path} · {source === 'neo4j' ? 'Neo4j' : source === 'github' ? 'GitHub' : 'Unavailable'}
        </li>)}</ul>
      </details>}
      {snapshot.review.decisions?.map((item, index) => <article key={'decision-' + index}>
        <div className="finding-icon"><Sparkle size={19} /></div><div><h4>{item.title}</h4><p>{item.detail}</p>
        <blockquote>{item.commit.quote}</blockquote>
        <a href={item.commit.url} target="_blank" rel="noreferrer">Commit {item.commit.sha.slice(0, 7)}</a>
        {item.url && <p><a href={item.url} target="_blank" rel="noreferrer">Current code · {item.path}:{item.line}</a></p>}
        </div>
      </article>)}
      {snapshot.review.findings.map((item, index) => <article key={index}>
        <div className="finding-icon"><Sparkle size={19} /></div><div><h4>{item.title}</h4><p>{item.detail}</p>
        {item.url && <a href={item.url} target="_blank" rel="noreferrer">{item.path}:{item.line} <ArrowUpRight size={14} /></a>}</div>
      </article>)}
    </section>}
  </div>
}
