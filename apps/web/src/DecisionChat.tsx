import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowUp, ArrowUpRight, GitBranch, Microphone, Stop, User } from '@phosphor-icons/react'
import { api, errorText } from './api'
import './decision-chat.css'

const EvidenceGraph = lazy(() => import('./EvidenceGraph'))

export type RecordNode = {
  id: string; kind: string; number?: number; title: string; body: string; date: string; author: string; url: string; state?: string
}
export type RecordLink = { source: string; target: string; kind: string; evidence: string; url: string }
export type Trail = {
  mode: 'ai' | 'retrieved' | 'abstained'
  evidence: { record: string; quote: string }[]
  graph: { nodes: RecordNode[]; edges: RecordLink[] }
  source: string | null
}
type IndexStatus = {
  revision: string | null; scanState: string; records: number | null; edges: number | null; gaps: string[] | null
}
type Turn = { question: string; answer?: Trail; error?: string }
type Anchor = { path: string; line?: number }

export function recordLabel(node: RecordNode) {
  const type = node.kind === 'pr' ? 'PR' : node.kind.charAt(0).toUpperCase() + node.kind.slice(1)
  return (node.number ? type + ' #' + node.number : type) + (node.state === 'draft' ? ' (draft)' : '')
}

function Answer({ answer }: { answer: Trail }) {
  return <div className="decision-answer">
    <strong>{answer.mode === 'abstained' ? 'Rationale unconfirmed' : answer.mode === 'ai' ? 'Evidence selected by AI' : 'Retrieved evidence'}</strong>
    {answer.mode === 'abstained' && <p>I couldn’t find a documented reason in the indexed records. Open the related evidence below or try a more specific file, issue, or PR.</p>}
    {answer.evidence.map((entry, index) => {
      const node = answer.graph.nodes.find(item => item.id === entry.record)
      return node && <figure key={entry.record + index} className="decision-citation">
        <blockquote>{entry.quote}</blockquote>
        <figcaption><a href={node.url} target="_blank" rel="noreferrer">{recordLabel(node)} · {node.title} <ArrowUpRight size={13} /></a>
          {node.author && <span> · @{node.author}</span>}</figcaption>
      </figure>
    })}
    {answer.source && <a className="decision-source" href={answer.source} target="_blank" rel="noreferrer">Open pinned source <ArrowUpRight size={13} /></a>}
    <Suspense fallback={<p role="status">Loading the decision graph…</p>}>
      <EvidenceGraph graph={answer.graph} />
    </Suspense>
  </div>
}

export function DecisionChat({ scanId, voice, ai, anchor, demo }: {
  scanId: string; voice: boolean; ai: boolean; anchor?: Anchor; demo: boolean
}) {
  const [index, setIndex] = useState<IndexStatus>()
  const [messages, setMessages] = useState<Turn[]>([])
  const [preview, setPreview] = useState<Trail['graph']>()
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [question, setQuestion] = useState('')
  const [path, setPath] = useState(anchor?.path ?? '')
  const [line, setLine] = useState(anchor?.line ? String(anchor.line) : '')
  const [sending, setSending] = useState(false)
  const [consent, setConsent] = useState(false)
  const [voiceState, setVoiceState] = useState<'idle' | 'starting' | 'recording' | 'transcribing'>('idle')
  const [error, setError] = useState('')
  const recorder = useRef<MediaRecorder | undefined>(undefined)
  const voiceTimeout = useRef<number | undefined>(undefined)
  const alive = useRef(false)
  const questionBox = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      window.clearTimeout(voiceTimeout.current)
      recorder.current?.stream.getTracks().forEach(track => track.stop())
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    let timer: number
    async function refresh() {
      try {
        const next = await api<IndexStatus>('/scans/' + scanId + '/knowledge')
        if (cancelled) return
        setIndex(next)
        setError('')
        if (next.revision || !['queued', 'running'].includes(next.scanState)) return
      } catch (problem) {
        if (cancelled) return
        setError(errorText(problem))
      }
      timer = window.setTimeout(() => void refresh(), 2600)
    }
    void refresh()
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [scanId])

  useEffect(() => {
    if (anchor) {
      setPath(anchor.path)
      setLine(anchor.line ? String(anchor.line) : '')
      questionBox.current?.focus()
    }
  }, [anchor])

  async function inspect() {
    if (preview) { setPreview(undefined); return }
    setLoadingPreview(true)
    try {
      setPreview(await api<Trail['graph']>('/scans/' + scanId + '/knowledge/preview'))
    } catch (problem) {
      setError(errorText(problem))
    } finally {
      setLoadingPreview(false)
    }
  }

  async function send(event: FormEvent) {
    event.preventDefault()
    const prompt = question.trim()
    if (!prompt || !index?.revision || sending) return
    setSending(true)
    setQuestion('')
    setError('')
    setMessages(current => [...current, { question: prompt }])
    const finish = (response: Omit<Turn, 'question'>) => setMessages(current => [
      ...current.slice(0, -1), { question: prompt, ...response },
    ])
    try {
      const answer = await api<Trail>('/scans/' + scanId + '/knowledge/ask', 'POST', {
        question: prompt, path: path.trim() || null, line: path.trim() && line ? Number(line) : null, ai: consent,
      })
      finish({ answer })
    } catch (problem) {
      finish({ error: errorText(problem) })
      setQuestion(prompt)
    } finally {
      setSending(false)
      questionBox.current?.focus()
    }
  }

  async function record() {
    if (voiceState === 'recording' && recorder.current?.state === 'recording') {
      recorder.current.stop()
      return
    }
    setError('')
    setVoiceState('starting')
    let stream: MediaStream | undefined
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('Voice recording requires a supported browser and HTTPS.')
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (!alive.current) { stream.getTracks().forEach(track => track.stop()); return }
      const options = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4']
      const format = options.find(item => MediaRecorder.isTypeSupported(item))
      const recording = new MediaRecorder(stream, format ? { mimeType: format } : undefined)
      recorder.current = recording
      const chunks: Blob[] = []
      recording.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }
      recording.onstop = async () => {
        window.clearTimeout(voiceTimeout.current)
        recording.stream.getTracks().forEach(track => track.stop())
        if (!alive.current) return
        setVoiceState('transcribing')
        try {
          const audio = new Blob(chunks, { type: recording.mimeType || chunks[0]?.type })
          const response = await fetch('/api/transcribe', { method: 'POST', body: audio, credentials: 'same-origin' })
          const result = await response.json()
          if (!response.ok) throw new Error(result.detail ?? 'Transcription failed.')
          if (alive.current) { setQuestion(result.text); questionBox.current?.focus() }
        } catch (problem) {
          if (alive.current) setError(errorText(problem))
        } finally {
          if (alive.current) setVoiceState('idle')
        }
      }
      recording.start()
      setVoiceState('recording')
      voiceTimeout.current = window.setTimeout(() => { if (recording.state === 'recording') recording.stop() }, 28000)
    } catch (problem) {
      stream?.getTracks().forEach(track => track.stop())
      if (alive.current) { setError(errorText(problem)); setVoiceState('idle') }
    }
  }

  const ready = !!index?.revision
  const waiting = !index || ['queued', 'running'].includes(index.scanState)
  return <section className="decision-workspace" aria-label="Repository decision chat">
    <div className="decision-header">
      <div><h3>Ask why</h3><p>Follow the issues, pull requests, and commits behind a change.</p></div>
      <span className="decision-index"><GitBranch size={15} />{ready ? 'Stored in Neo4j' : 'Knowledge graph'}</span>
    </div>
    {ready ? <div className="decision-status" role="status">
      <span>{index.records?.toLocaleString()} records · {index.edges?.toLocaleString()} links · {index.revision?.slice(0, 7)}</span>
      {!!index.gaps?.length && <small>Partial GitHub coverage · {index.gaps.join(', ')}</small>}
      <button type="button" className="decision-status-link" disabled={loadingPreview}
        onClick={() => void inspect()}>{preview ? 'Hide graph preview' : loadingPreview ? 'Loading preview…' : 'Inspect stored graph'}</button>
    </div> : <p className="decision-status" role="status">{waiting
      ? 'Indexing GitHub history and building the Neo4j graph…'
      : 'This scan has no stored knowledge graph. Import the repository again to prepare it.'}</p>}
    {preview && <div className="decision-preview">
      <Suspense fallback={<p role="status">Loading the stored graph…</p>}>
        <EvidenceGraph graph={preview} />
      </Suspense>
    </div>}
    {ready && <div className="decision-thread" aria-label="Conversation" aria-live="polite">
      {!messages.length && <div className="decision-empty">
        <GitBranch size={31} weight="duotone" />
        <h4>What changed, and why?</h4>
        <p>Ask about a behavior, mention a PR or issue number, or attach a file and line.</p>
        {demo && <div className="decision-demo-prompts">
          <button className="button" onClick={() => {
            setQuestion('Why did Futon need to preserve reading statistics during source migration? Trace issue #127 and PR #138.')
            questionBox.current?.focus()
          }}>Trace a migration regression</button>
          <button className="button" onClick={() => {
            setQuestion('What did the draft PR #142 propose for the Continue button and navigation dock?')
            questionBox.current?.focus()
          }}>Explore the dock proposal</button>
        </div>}
      </div>}
      {messages.map((message, idx) => <article className="decision-turn" key={idx}>
        <div className="decision-question"><User size={17} /><p>{message.question}</p></div>
        {message.answer ? <Answer answer={message.answer} /> : <p className="decision-wait" role={message.error ? 'alert' : 'status'}>
          {message.error ?? 'Retrieving a decision trail from Neo4j…'}
        </p>}
      </article>)}
    </div>}
    {error && <p className="decision-error" role="alert">{error}</p>}
    <form className="decision-composer" onSubmit={send}>
      <label className="sr-only" htmlFor="decision-question">Question about this repository</label>
      <textarea id="decision-question" ref={questionBox} value={question} onChange={event => setQuestion(event.target.value)}
        maxLength={1500} rows={3} disabled={!ready} placeholder="Why was this UI changed?" />
      <details className="decision-anchor" open={anchor ? true : undefined}>
        <summary>Attach a file or line</summary>
        <label>Repository path <input value={path} maxLength={400} onChange={event => setPath(event.target.value)} placeholder="app/src/Reader.kt" /></label>
        <label>Line <input type="number" min={1} max={1000000} value={line} onChange={event => setLine(event.target.value)} /></label>
      </details>
      <div className="decision-compose-actions">
        {ai && <label className="decision-consent"><input type="checkbox" checked={consent}
          onChange={event => setConsent(event.target.checked)} /> Send this question and public evidence excerpts to Gemini</label>}
        <div>
          {voice && <button type="button" className="button" disabled={!ready || ['starting', 'transcribing'].includes(voiceState)}
            onClick={() => void record()}>{voiceState === 'recording' ? <><Stop size={17} /> Stop and transcribe</> :
              <><Microphone size={17} />{voiceState === 'transcribing' ? 'Transcribing…' : voiceState === 'starting' ? 'Waiting for microphone…' : 'Dictate with Sarvam'}</>}</button>}
          <button className="button primary" type="submit" disabled={!ready || sending || !question.trim()}>
            Ask <ArrowUp size={16} /></button>
        </div>
      </div>
      {voice && <small>Stopping the recording sends it to Sarvam. Review the transcript before asking.</small>}
    </form>
  </section>
}
