
import { lazy, StrictMode, Suspense, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { createRoot } from 'react-dom/client'
import {
  ArrowRight, ArrowUpRight, ChartBar, Code, GitBranch, GithubLogo,
  Briefcase, Graph, ListChecks, Plus, Trash, X,
} from '@phosphor-icons/react'
import { api, errorText, pending } from './api'
import type { Repository, Scan, Session, Snapshot } from './api'
import { OpenSource } from './OpenSource'
import { Practice } from './Practice'
import { Career } from './Career'
import { DecisionHistory } from './DecisionHistory'
import { RubricPreview } from './RubricPreview'
import { Scorecard } from './Scorecard'
import './styles.css'

const CodeGraph = lazy(() => import('./Graph').then(module => ({ default: module.CodeGraph })))

type View = 'workspace' | 'rankings' | 'practice' | 'career' | 'opensource'
type Tab = 'graph' | 'quality' | 'history'

function App() {
  const [view, setView] = useState<View>('workspace')
  const [focusRoadmap, setFocusRoadmap] = useState(false)
  const [tab, setTab] = useState<Tab>('graph')
  const [session, setSession] = useState<Session | null>(null)
  const [scans, setScans] = useState<Scan[]>([])
  const [active, setActive] = useState<string | null>(null)
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [repo, setRepo] = useState('')
  const [consent, setConsent] = useState(false)
  const [notice, setNotice] = useState('')
  const [loadError, setLoadError] = useState('')
  const [busy, setBusy] = useState(false)
  const [picker, setPicker] = useState(false)
  const [repositories, setRepositories] = useState<Repository[]>([])
  const [pickerPage, setPickerPage] = useState(1)
  const [pickerStatus, setPickerStatus] = useState('')
  const [settings, setSettings] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(false)
  const [previous, setPrevious] = useState<Scan | undefined>()
  const [practiceFocus, setPracticeFocus] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const account = await api<Session>('/session')
        const results = await api<Scan[]>('/scans')
        if (alive) { setSession(account); setScans(results) }
      } catch (error) { if (alive) setNotice(errorText(error)) }
    })()
    const auth = new URLSearchParams(location.search).get('auth')
    if (auth) {
      history.replaceState(null, '', '/')
      if (auth !== 'connected') setNotice(auth === 'unavailable' ? 'GitHub sign-in is unavailable.' : 'GitHub could not connect. Please try again.')
    }
    return () => { alive = false }
  }, [])

  const shouldPoll = scans.some(pending)
  useEffect(() => {
    if (!shouldPoll) return
    let alive = true
    let timer: number
    async function attempt() {
      try {
        const next = await api<Scan[]>('/scans')
        if (alive) setScans(next)
        if (!next.some(pending)) return
      } catch (error) {
        if (alive) setNotice(errorText(error))
      }
      if (alive) timer = window.setTimeout(() => void attempt(), 1900)
    }
    timer = window.setTimeout(() => void attempt(), 1000)
    return () => { alive = false; window.clearTimeout(timer) }
  }, [shouldPoll])

  const selectedRow = scans.find(item => item.id === active)
  const selectedState = selectedRow?.state
  useEffect(() => {
    let alive = true
    setSnapshot(null)
    setLoadError('')
    if (active && selectedState !== 'complete' && selectedState !== 'review') return
    if (selectedState === 'review') setTab('quality')
    const run = active
      ? api<Scan>('/scans/' + active).then(scan => scan.result as Snapshot)
      : api<Snapshot>('/sample')
    void run.then(result => { if (alive) setSnapshot(result) })
      .catch(error => { if (alive) setLoadError(errorText(error)) })
    return () => { alive = false }
  }, [active, selectedState])

  useEffect(() => {
    if (!picker) return
    let alive = true
    setPickerStatus('Loading repositories…')
    void api<Repository[]>('/github/repos?page=' + pickerPage).then(next => {
      if (alive) { setRepositories(next); setPickerStatus('') }
    }).catch(error => { if (alive) setPickerStatus(errorText(error)) })
    return () => { alive = false }
  }, [picker, pickerPage])

  async function start(event: FormEvent) {
    event.preventDefault()
    setNotice('')
    setBusy(true)
    try {
      const scan = await api<Scan>('/scans', 'POST', { repository: repo, ai: consent, history: consent })
      setScans(current => [scan, ...current.filter(row => row.id !== scan.id)])
      openScan(scan.id)
      setRepo('')
      setConsent(false)
    } catch (error) { setNotice(errorText(error)) }
    finally { setBusy(false) }
  }

  function openScan(id: string | null, nextTab: Tab = 'graph') {
    setActive(id); setView('workspace'); setTab(nextTab); setPrevious(undefined)
  }

  async function removeScan(id: string) {
    try {
      await api('/scans/' + id, 'DELETE')
      setScans(current => current.filter(row => row.id !== id))
      if (active === id) openScan(null)
    } catch (error) { setNotice(errorText(error)) }
  }

  async function approveRubric(expected: string[], note: string) {
    if (!active) return
    const published = await api<Scan>('/scans/' + active + '/rubric', 'POST', { expected, note })
    setScans(current => current.map(row => row.id === published.id ? published : row))
  }

  async function accountAction(remove: boolean) {
    setNotice('')
    try {
      await api(remove ? '/account' : '/auth/logout', remove ? 'DELETE' : 'POST')
      setSession(await api<Session>('/session'))
      setScans([])
      openScan(null)
      setSettings(false)
      setDeleteConfirm(false)
    } catch (error) { setNotice(errorText(error)) }
  }

  const summary = selectedRow?.result && 'error' in selectedRow.result ? selectedRow.result : null
  const comparable = scans.filter(row => row.id !== active && row.repo === snapshot?.repo && row.summary?.rankable
    && snapshot?.quality.rankable && scoreGroup(row.summary) === scoreGroup(snapshot.quality))

  return <>
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header className="topbar">
      <div className="top-inner">
        <button className="brand" onClick={() => openScan(null)}><span className="brand-mark"><GitBranch size={21} weight="bold" /></span><span>SkillForge</span></button>
        <nav aria-label="Main navigation">
          <button aria-current={view === 'workspace' ? 'page' : undefined} onClick={() => setView('workspace')}><Graph size={18} /> Workspace</button>
          <button aria-current={view === 'rankings' ? 'page' : undefined} onClick={() => setView('rankings')}><ChartBar size={18} /> Rankings</button>
          <button aria-current={view === 'practice' ? 'page' : undefined} onClick={() => { setPracticeFocus(null); setView('practice') }}><Code size={18} /> Practice</button>
          <button aria-current={view === 'opensource' ? 'page' : undefined} onClick={() => setView('opensource')}><GithubLogo size={18} /> Open Source</button>
          <button aria-current={view === 'career' ? 'page' : undefined} onClick={() => { setFocusRoadmap(false); setView('career') }}><Briefcase size={18} /> Career</button>
        </nav>
        <button className="top-account" onClick={() => setSettings(!settings)} aria-expanded={settings}>
          <GithubLogo size={18} /><span>{session?.login ?? 'Account'}</span>
        </button>
      </div>
    </header>
    <main className="shell" id="main-content" tabIndex={-1}>
      {settings && <section className="settings-panel" aria-label="Account settings">
        <div className="split"><h2>Account</h2><button className="icon-button" onClick={() => setSettings(false)} aria-label="Close account settings"><X size={17} /></button></div>
        <p>{session?.login ? 'Connected as ' + session.login : 'You’re using a temporary workspace.'}</p>
        {session?.login ? <button className="button" onClick={() => void accountAction(false)}>Disconnect GitHub</button>
          : session?.oauth && <a className="button" href="/api/auth/github">Connect GitHub</a>}
        <div className="danger-zone">
          {deleteConfirm ? <><p>Delete your scans, practice results, and workspace data?</p><button className="button danger" onClick={() => void accountAction(true)}>Confirm deletion</button>
            <button className="button" onClick={() => setDeleteConfirm(false)}>Cancel</button></>
            : <button className="button danger" onClick={() => setDeleteConfirm(true)}>Delete workspace data</button>}
        </div>
      </section>}
      {notice && <div className="notice" role="alert">{notice}<button className="icon-button" onClick={() => setNotice('')} aria-label="Dismiss notice"><X size={16} /></button></div>}
      {view === 'workspace' ? <>
        <section className="hero">
          <div className="hero-copy">
            <h1>Understand the <em>code</em><br className="desktop-break" /> <em>you ship.</em></h1>
            <p>Explore how a repository fits together and see what its quality score is based on.</p>
          </div>
          <form className="import-panel" onSubmit={start}>
            <div className="import-title"><h2>Analyze a repository</h2></div>
            <label htmlFor="repository">Public GitHub URL</label>
            <div className="input-line"><GithubLogo size={19} /><input id="repository" autoComplete="off" value={repo} maxLength={280}
              onChange={event => setRepo(event.target.value)} placeholder="github.com/owner/repository" required /></div>
            {session?.ai && <label className="checkbox"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />
              <span>Send up to six public code excerpts and recent commit messages to Gemini for optional review. Public commit history may be cached in Neo4j.</span></label>}
            <div className="import-actions">
              <button className="button primary" disabled={busy || !session}>{busy ? 'Queuing…' : 'Analyze repo'} <ArrowRight size={17} /></button>
              {session?.oauth && !session.login && <a href="/api/auth/github" className="text-button">Connect GitHub</a>}
              {session?.login && <button type="button" className="text-button" onClick={() => { setPickerPage(1); setPicker(true) }}>Choose from GitHub</button>}
            </div>
          </form>
        </section>
        <div className="workspace-grid">
          <aside className="library">
            <div className="split"><h2>Repositories</h2><button className="icon-button" aria-label="Focus repository import" onClick={() => document.getElementById('repository')?.focus()}><Plus size={17} /></button></div>
            <button className={'library-item' + (!active ? ' active' : '')} aria-pressed={!active} onClick={() => openScan(null)}>
              <GitBranch size={17} /><span><strong>delivery-routing</strong><small>Example repository</small></span>
            </button>
            {scans.map(scan => <div className={'library-row' + (scan.id === active ? ' active' : '')} key={scan.id}>
              <button className="library-item" aria-pressed={scan.id === active} onClick={() => openScan(scan.id)}>
                <GitBranch size={17} /><span><strong>{scan.repo}</strong><small>{pending(scan) ? scan.state : scan.state === 'failed' ? 'Needs attention'
                  : scan.state === 'review' ? 'Rubric ready for review' : (scan.revision?.slice(0, 7) ?? 'Complete') +
                  (scan.summary?.score != null ? ' · ' + scan.summary.score + '/' + (scan.summary.scale ?? 100) : '')}</small></span>
              </button>
              {!pending(scan) && <button className="icon-button tiny remove-scan" onClick={() => {
                if (window.confirm('Remove this scan from your workspace?')) void removeScan(scan.id)
              }} aria-label={'Remove scan for ' + scan.repo}><Trash size={14} /></button>}
            </div>)}
          </aside>
          <section className="detail" aria-label="Selected repository">
            <div className="detail-heading">
              <div><p className="eyebrow">{snapshot?.sample ? 'Example repository' : 'Repository analysis'}</p>
                <h2>{snapshot?.repo ?? selectedRow?.repo ?? 'Repository analysis'}</h2>
                {snapshot?.description && <p>{snapshot.description}</p>}</div>
              {snapshot && <div className="revision"><GitBranch size={16} /> {snapshot.branch}<span>{snapshot.revision.slice(0, 7)}</span></div>}
            </div>
            {!snapshot && !loadError && !summary && <div className="status-panel" role="status">{selectedState === 'queued' ? 'Waiting for an analysis worker…'
              : selectedState === 'running' ? 'Reading source and building the graph…' : 'Loading repository…'}</div>}
            {loadError && <div className="status-panel" role="alert">{loadError}</div>}
            {summary && <div className="status-panel" role="alert"><p>{summary.error}</p>
              {summary.retryAt && <p>Try after {new Date(summary.retryAt * 1000).toLocaleTimeString()}.</p>}
              <button className="button" onClick={() => { setRepo(selectedRow!.repo); document.getElementById('repository')?.focus() }}>Prepare another scan</button></div>}
            {snapshot && <>
              <div className="tabbar" role="group" aria-label="Repository views">
                <button aria-pressed={tab === 'graph'} onClick={() => setTab('graph')}><Graph size={17} /> Code graph</button>
                <button aria-pressed={tab === 'quality'} onClick={() => setTab('quality')}><ListChecks size={17} /> Quality score</button>
                <button aria-pressed={tab === 'history'} onClick={() => setTab('history')}><GitBranch size={17} /> Decision history</button>
              </div>
              {tab === 'graph' && <Suspense fallback={<p className="status-panel" role="status">Loading code graph…</p>}>
                <CodeGraph key={snapshot.repo + snapshot.revision} snapshot={snapshot} scanId={active} />
              </Suspense>}
              {tab === 'quality' && selectedState === 'review' && <RubricPreview key={active} snapshot={snapshot} onApprove={approveRubric} />}
              {tab === 'quality' && selectedState !== 'review' && <Scorecard key={active ?? 'sample'} scanId={active} snapshot={snapshot} comparable={comparable} previous={previous} onCompare={setPrevious}
                onPractice={id => { setPracticeFocus(id); setView('practice'); window.scrollTo(0, 0) }} />}
              {tab === 'history' && <DecisionHistory key={active ?? 'sample'} snapshot={snapshot} scanId={active} />}
            </>}
          </section>
        </div>
      </> : view === 'rankings' ? <Rankings scans={scans} onOpen={id => openScan(id, 'quality')} onWorkspace={() => setView('workspace')} />
        : view === 'opensource' ? <OpenSource onRoadmap={() => {
          setFocusRoadmap(true); setView('career')
        }} onExplore={repository => {
          setRepo(repository); setConsent(false); openScan(null); window.scrollTo(0, 0)
        }} /> : view === 'practice' ? <Practice enabled={!!session?.judge} initialProblem={practiceFocus} /> : <Career scans={scans} session={session} focusRoadmap={focusRoadmap}
          onDiscover={() => { setView('opensource'); window.scrollTo(0, 0) }}
          onPractice={() => { setPracticeFocus(null); setView('practice'); window.scrollTo(0, 0) }} />}
    </main>
    <footer><span>SkillForge</span><span>Repository analysis and applied practice</span></footer>
    {picker && <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-label="Choose a GitHub repository">
      <div className="split"><h2>Choose a public repository</h2><button className="icon-button" autoFocus onClick={() => setPicker(false)} aria-label="Close picker"><X size={18} /></button></div>
      {pickerStatus ? <p role="status">{pickerStatus}</p> : <div className="picker-list">
        {repositories.length ? repositories.map(item => <button key={item.name} onClick={() => { setRepo(item.name); setPicker(false); document.getElementById('repository')?.focus() }}>
          <GithubLogo size={17} /><span><strong>{item.name}</strong><small>{item.description ?? item.language ?? 'Public repository'}</small></span><ArrowRight size={16} />
        </button>) : <p>No public repositories on this page.</p>}
      </div>}
      <div className="split"><button className="button compact" disabled={pickerPage === 1 || !!pickerStatus} onClick={() => setPickerPage(pickerPage - 1)}>Previous</button>
        <span>Page {pickerPage}</span><button className="button compact" disabled={repositories.length < 30 || pickerPage >= 10 || !!pickerStatus}
          onClick={() => setPickerPage(pickerPage + 1)}>Next</button></div>
    </section></div>}
  </>
}

function scoreGroup(summary: NonNullable<Scan['summary']>) {
  return [summary.cohort, summary.version, summary.scale ?? 100, summary.comparisonKey ?? 'legacy'].join('|')
}

function Rankings({ scans, onOpen, onWorkspace }: { scans: Scan[]; onOpen: (id: string) => void; onWorkspace: () => void }) {
  const latest = [...new Map([...scans].reverse().filter(row => row.state === 'complete').map(row => [row.repo, row])).values()]
  const ranked = latest.filter(row => row.summary?.rankable && row.summary.score !== null)
  const groups = Map.groupBy(ranked, row => scoreGroup(row.summary!))
  const unranked = latest.filter(row => !row.summary?.rankable)
  return <section className="ranking-page">
    <p className="eyebrow"><span className="accent-square" /> Repository quality</p>
    <h1>Repository rankings<span>.</span></h1>
    <p>Compare the latest completed scan per repository within the same project type, language cohort, and measured rubric.</p>
    {!latest.length && <div className="status-panel"><p>Analyze a public repository to start your rankings.</p><button className="button primary" onClick={onWorkspace}>Open workspace <ArrowRight size={16} /></button></div>}
    {[...groups].map(([key, rows]) => <section className="panel rankings" key={key}>
      <h2>{[rows[0].summary?.archetype, rows[0].summary?.cohort, rows[0].summary?.version].filter(Boolean).join(' · ')}</h2>
      {rows.sort((a, b) => (b.summary?.score ?? 0) - (a.summary?.score ?? 0)).map((row, index, ordered) =>
        <button key={row.id} onClick={() => onOpen(row.id)}><span>{ordered.findIndex(item => item.summary?.score === row.summary?.score) + 1 || index + 1}</span>
          <strong>{row.repo}</strong><span>{row.summary?.coverage.percent}% coverage</span><strong>{row.summary?.score}/{row.summary?.scale ?? 100}</strong><ArrowUpRight size={17} /></button>)}
    </section>)}
    {!!unranked.length && <section className="panel rankings"><h2>Unranked</h2>{unranked.map(row => <button key={row.id} onClick={() => onOpen(row.id)}>
      <span>—</span><strong>{row.repo}</strong><span>{row.summary?.coverage.percent}% coverage</span><span>Partial</span><ArrowUpRight size={17} /></button>)}</section>}
  </section>
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
