
import {
  ArrowLeft, ArrowRight, ArrowsOutSimple, ArrowUpRight, Code, FolderSimple, Graph, ListBullets,
  MagnifyingGlass, Minus, Plus, X,
} from '@phosphor-icons/react'
import cytoscape, { type Core } from 'cytoscape'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { Edge, Node, Snapshot, Source } from './api'
import { api, errorText } from './api'
import { folderOverview, neighborhood, PAGE_SIZE, parentScope, ROOT_FILES, searchNodes } from './graphView'
import type { AggregateEdge, OverviewNode } from './graphView'
import './graph.css'

const colors: Record<string, string> = {
  file: '#79dad8', folder: '#82aaff', function: '#c0a6ff', package: '#f5ba80', unresolved: '#bcc4d1',
}
const types = ['folder', 'file', 'function', 'package', 'unresolved']
const typeName = (kind: string) => kind === 'unresolved' ? 'Unresolved' : kind.charAt(0).toUpperCase() + kind.slice(1)
const scopeName = (scope: string) => scope === ROOT_FILES ? 'Root files' : scope.replace(/\/$/, '')
const sourceAvailable = (node: Node, snapshot: Snapshot) => node.path && snapshot.preview_paths.includes(node.path)
type DrawnEdge = Edge | AggregateEdge

function relationLabel(edge: DrawnEdge) {
  return 'count' in edge ? edge.count + ' ' + (edge.kind === 'calls' ? 'calls' : 'imports')
    : edge.kind === 'defines' ? 'Defines' : edge.kind
}

export function CodeGraph({ snapshot, scanId, onAsk }: {
  snapshot: Snapshot; scanId: string | null; onAsk?: (path: string, line: number | null) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const graph = useRef<Core | null>(null)
  const canvasTitle = useRef<HTMLHeadingElement>(null)
  const inspectorTitle = useRef<HTMLHeadingElement>(null)
  const searchInput = useRef<HTMLInputElement>(null)
  const sourceBlock = useRef<HTMLPreElement>(null)
  const previewTitle = useRef<HTMLHeadingElement>(null)
  const [width, setWidth] = useState(640)
  const [scope, setScope] = useState('')
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<Node | null>(null)
  const [edgeDetail, setEdgeDetail] = useState('')
  const [preview, setPreview] = useState<Source | null>(null)
  const [highlight, setHighlight] = useState<number | null>(null)
  const [draft, setDraft] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState('')
  const [loading, setLoading] = useState(false)
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('all')
  const [filter, setFilter] = useState('all')
  const [browse, setBrowse] = useState(false)
  const previewSeq = useRef(0)

  const allNodes = useMemo(() => new Map(snapshot.graph.nodes.map(node => [node.id, node])), [snapshot])
  const overview = useMemo(() => folderOverview(snapshot.graph.nodes, snapshot.graph.edges, scope, page, filter),
    [snapshot, scope, page, filter])
  const focused = useMemo(() => selected ? neighborhood(selected, snapshot.graph.edges, allNodes, filter) : null,
    [selected, snapshot, allNodes, filter])
  const matches = useMemo(() => browse ? searchNodes(snapshot.graph.nodes, query, kind) : [],
    [snapshot, query, kind, browse])
  const nodes: OverviewNode[] = focused ? focused.nodes : overview.nodes
  const columns = width >= 620 ? 3 : width >= 300 ? 2 : 1
  const horizontal = width >= 560
  const rows = focused ? horizontal ? Math.max(focused.incoming.length, focused.outgoing.length)
    : Math.ceil((focused.nodes.length - 1) / columns) + 1 : Math.ceil(nodes.length / columns)
  const height = Math.max(306, 65 + Math.max(1, rows) * 81)
  const nodeWidth = Math.min(176, Math.max(94, width / (focused && horizontal ? 3 : columns) - 27))

  useEffect(() => {
    if (!container.current) return
    const cy = cytoscape({
      container: container.current, elements: [], minZoom: .55, maxZoom: 1.6,
      autoungrabify: true, boxSelectionEnabled: false, userZoomingEnabled: false,
      style: [
        { selector: 'node', style: {
          shape: 'round-rectangle', width: 'data(width)', height: 48,
          'background-color': '#1b2636', 'border-color': 'data(color)', 'border-width': 1.25,
          label: 'data(label)', color: '#ecf2fb', 'font-size': 13, 'font-weight': 600,
          'font-family': 'system-ui', 'text-valign': 'center', 'text-halign': 'center',
          'text-max-width': 'data(textWidth)', 'text-wrap': 'ellipsis',
          'overlay-opacity': 0,
        } },
        { selector: 'node[center = "yes"]', style: { 'background-color': '#283c58', 'border-width': 2.5 } },
        { selector: 'node:selected', style: { 'background-color': '#26394e' } },
        { selector: 'edge', style: {
          width: 1.4, 'curve-style': 'bezier', 'line-color': '#627b99',
          'target-arrow-color': '#7797b9', 'target-arrow-shape': 'triangle', 'arrow-scale': .8,
          'overlay-opacity': 0,
        } },
        { selector: 'edge[kind ^= "calls"]', style: {
          'line-color': '#b59ee8', 'target-arrow-color': '#b59ee8', 'line-style': 'dashed',
        } },
        { selector: 'edge:selected', style: { width: 3, 'line-color': '#83dedd', 'target-arrow-color': '#83dedd' } },
      ],
    })
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(container.current)
    graph.current = cy
    return () => { observer.disconnect(); graph.current = null; cy.destroy() }
  }, [])

  useEffect(() => {
    const cy = graph.current
    if (!cy) return
    const renderedNodes = focused ? focused.nodes : overview.nodes
    const renderedEdges = focused ? focused.edges : overview.edges
    const coordinates = (node: Node, index: number) => {
      if (!focused) return { x: width * ((index % columns) + .5) / columns,
        y: height / 2 + (Math.floor(index / columns) - (rows - 1) / 2) * 81 }
      if (node.id === selected?.id) return { x: width / 2, y: horizontal ? height / 2 : 49 }
      if (horizontal) {
        const side = focused.incoming.includes(node.id) ? focused.incoming : focused.outgoing
        return { x: width * (side === focused.incoming ? .175 : .825),
          y: height / 2 + (side.indexOf(node.id) - (side.length - 1) / 2) * 81 }
      }
      return { x: width * (((index - 1) % columns) + .5) / columns, y: 129 + Math.floor((index - 1) / columns) * 81 }
    }
    cy.resize()
    cy.batch(() => {
      cy.elements().remove()
      cy.add(renderedNodes.map((node, index) => {
        const count = 'count' in node && node.count ? '  ·  ' + node.count : ''
        return { data: { id: node.id, label: node.label + count, color: colors[node.kind] ?? colors.file,
          center: node.id === selected?.id ? 'yes' : 'no', width: nodeWidth, textWidth: nodeWidth - 18, payload: node },
        position: coordinates(node, index) }
      }))
      cy.add(renderedEdges.map((edge, index) => ({
        data: { id: 'edge-' + index, source: edge.source, target: edge.target, kind: edge.kind, payload: edge },
      })))
    })
    cy.viewport({ zoom: 1, pan: { x: 0, y: 0 } })
  }, [overview, focused, selected, nodeWidth, columns, width, height, horizontal, rows])

  function resetScope(next: string) {
    setScope(next); setPage(0); setSelected(null); setEdgeDetail('')
    setBrowse(false); setQuery(''); setKind('all'); setFilter('all')
  }

  function selectNode(node: Node) {
    if (node.kind === 'folder') {
      resetScope(node.id)
      requestAnimationFrame(() => canvasTitle.current?.focus())
      return
    }
    const actual = allNodes.get(node.id)
    if (actual) {
      setSelected(actual); setFilter('all'); setBrowse(false); setEdgeDetail('')
      requestAnimationFrame(() => inspectorTitle.current?.focus())
      return
    }
    setQuery(''); setKind(node.kind); setBrowse(true)
    requestAnimationFrame(() => searchInput.current?.focus())
  }

  async function showSource(path: string, line: number | null) {
    const sequence = ++previewSeq.current
    setPreviewError(''); setPreview(null); setDraft(null); setHighlight(line); setLoading(true)
    try {
      const next = await api<Source>((scanId ? '/scans/' + scanId : '/sample') + '/source?path=' + encodeURIComponent(path))
      if (previewSeq.current === sequence) setPreview(next)
    } catch (error) {
      if (previewSeq.current === sequence) setPreviewError(errorText(error))
    } finally {
      if (previewSeq.current === sequence) setLoading(false)
    }
  }

  useEffect(() => {
    const cy = graph.current
    if (!cy) return
    const onNode = (event: cytoscape.EventObject) => selectNode(event.target.data('payload') as Node)
    const onEdge = (event: cytoscape.EventObject) => {
      const edge = event.target.data('payload') as DrawnEdge
      const [from, to] = [edge.source, edge.target].map(id => cy.getElementById(id).data('payload') as Node)
      setEdgeDetail(from.label + ' → ' + to.label + ' · ' + relationLabel(edge))
      if ('path' in edge && edge.line && snapshot.preview_paths.includes(edge.path)) void showSource(edge.path, edge.line)
    }
    cy.on('tap', 'node', onNode).on('tap', 'edge', onEdge)
    return () => { cy.off('tap', 'node', onNode).off('tap', 'edge', onEdge) }
  }, [allNodes, snapshot.preview_paths, scanId])

  useEffect(() => {
    const block = sourceBlock.current
    const line = block?.querySelector<HTMLElement>('.highlight-line')
    if (block && line) block.scrollTop = line.offsetTop - block.offsetTop - 30
    if (preview) {
      previewTitle.current?.focus({ preventScroll: true })
      previewTitle.current?.scrollIntoView({ block: 'nearest' })
    }
  }, [preview, highlight])

  function zoom(factor: number) {
    const cy = graph.current
    if (cy) cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } })
  }

  function connectionList(title: string, edges: Edge[], incoming: boolean) {
    return <section className="connection-list"><h4>{title} <span>{edges.length}</span></h4>
      {edges.length ? edges.map(edge => {
        const target = allNodes.get(incoming ? edge.source : edge.target)
        if (!target) return null
        return <div className="connection-row" key={JSON.stringify([edge.source, edge.target, edge.kind, edge.path, edge.line])}>
          <button className="connection-target" onClick={() => selectNode(target)}><strong>{target.label}</strong>
            <small>{relationLabel(edge)}</small></button>
          {edge.line && snapshot.preview_paths.includes(edge.path) && <button className="icon-button"
            onClick={() => void showSource(edge.path, edge.line)} aria-label={'Open ' + edge.path + ':' + edge.line}><ArrowUpRight size={15} /></button>}
        </div>
      }) : <p>No indexed connections.</p>}
    </section>
  }

  return <section className="graph-card" aria-label="Interactive code structure">
    <div className="graph-toolbar">
      <label className="search-field graph-search"><MagnifyingGlass size={17} /><input ref={searchInput}
        value={query} onChange={event => { setQuery(event.target.value); setBrowse(true) }}
        onKeyDown={event => {
          if (event.key === 'Enter' && matches[0]) { event.preventDefault(); selectNode(matches[0]) }
          if (event.key === 'Escape') setBrowse(false)
        }} placeholder="Find a file, function, or package" aria-label="Find a file, function, or package" /></label>
      <label className="select-field"><select aria-label="Filter graph connections" value={filter}
        onChange={event => { setFilter(event.target.value); setEdgeDetail('') }}>
        <option value="all">All connections</option><option value="imports">Imports</option>
        <option value="calls">Function calls</option>
        {selected && <><option value="contains">Folder structure</option><option value="defines">Definitions</option></>}
      </select></label>
      <button className="button compact" onClick={() => setBrowse(!browse)} aria-expanded={browse}>
        <ListBullets size={17} /> {browse ? 'Hide list' : 'Browse nodes'}
      </button>
    </div>
    {browse && <section className="graph-browse" aria-label="Graph node browser">
      <div className="split"><h4>{matches.length} {query ? 'matches' : 'indexed nodes'}</h4>
        <label className="select-field"><select aria-label="Filter graph node type" value={kind} onChange={event => setKind(event.target.value)}>
          <option value="all">All node types</option>{types.map(type => <option key={type} value={type}>{typeName(type)}</option>)}
        </select></label></div>
      <div className="graph-results">
        {matches.length ? matches.slice(0, 50).map(node => <button key={node.id} onClick={() => selectNode(node)}>
          <span className="color-dot" style={{ background: colors[node.kind] }} /><strong>{node.label}</strong>
          <small>{node.path ?? node.kind}</small><ArrowRight size={14} />
        </button>) : <p>No matching nodes. Try a different name or node type.</p>}
      </div>
      {matches.length > 50 && <p>Showing 50 of {matches.length}. Search to narrow the list.</p>}
    </section>}
    <div className="graph-heading">
      <div>
        <nav className="graph-crumb" aria-label="Graph location">
          {selected || scope ? <button className="text-button" onClick={() => resetScope(selected ? scope : parentScope(scope))}>
            <ArrowLeft size={15} /> {selected ? 'Back to overview' : 'Up one level'}</button> : <span><Graph size={16} /> Repository overview</span>}
          {scope && <span>{scopeName(scope)}</span>}
        </nav>
        <h3 tabIndex={-1} ref={canvasTitle}>{selected?.label ?? (scope ? scopeName(scope) : 'Repository structure')}</h3>
        <p>{selected ? 'Direct connections around this node' : 'Select a folder to drill down, or search for a specific node.'}</p>
      </div>
      {!selected && overview.total > PAGE_SIZE && <div className="graph-pages">
        <button className="icon-button" disabled={page === 0} onClick={() => setPage(page - 1)} aria-label="Previous graph page"><ArrowLeft size={16} /></button>
        <span>{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, overview.total)} of {overview.total}</span>
        <button className="icon-button" disabled={(page + 1) * PAGE_SIZE >= overview.total}
          onClick={() => setPage(page + 1)} aria-label="Next graph page"><ArrowRight size={16} /></button>
      </div>}
    </div>
    <div className={'graph-grid' + (selected ? ' selected' : '')}>
      <div className="map">
        <div className="canvas" style={{ height }} aria-hidden="true" ref={container} />
        {!nodes.length && <p className="canvas-empty">No indexed nodes in this view.</p>}
        {selected && <div className="map-directions">{horizontal ? <><span>Incoming</span><span>Outgoing</span></>
          : <span>Selected node above its neighbors</span>}</div>}
        <div className="zoom-controls">
          <button className="icon-button" aria-label="Zoom in" onClick={() => zoom(1.2)}><Plus size={17} /></button>
          <button className="icon-button" aria-label="Zoom out" onClick={() => zoom(.83)}><Minus size={17} /></button>
          <button className="icon-button" aria-label="Reset graph view" onClick={() => graph.current?.viewport({ zoom: 1, pan: { x: 0, y: 0 } })}><ArrowsOutSimple size={17} /></button>
        </div>
      </div>
      {selected && focused && <aside className="node-inspector" aria-label="Graph node details">
        <div className="split"><span className="eyebrow">{typeName(selected.kind)}</span>
          <button className="icon-button" aria-label="Close node details" onClick={() => { resetScope(scope); searchInput.current?.focus() }}><X size={16} /></button>
        </div>
        <h3 tabIndex={-1} ref={inspectorTitle}>{selected.label}</h3>
        {selected.path && <p className="mono word-wrap">{selected.path}</p>}
        {sourceAvailable(selected, snapshot) && <button className="button compact" onClick={() => void showSource(selected.path!, selected.line)}>
          <Code size={16} /> Open source</button>}
        {onAsk && selected.path && selected.kind !== 'folder' && <button className="button compact"
          onClick={() => onAsk(selected.path!, selected.line)}>Ask why</button>}
        {connectionList('Incoming', focused.relevant.filter(edge => edge.target === selected.id), true)}
        {connectionList('Outgoing', focused.relevant.filter(edge => edge.source === selected.id && edge.target !== selected.id), false)}
      </aside>}
    </div>
    <div className="legend">
      <div>{types.map(type => <span key={type}><i style={{ background: colors[type] }} />{typeName(type)}</span>)}</div>
      <span>{nodes.length} shown{focused?.hidden ? ' · ' + focused.hidden + ' more in details' : ''}
        {!focused && overview.hidden ? ' · ' + overview.hidden + ' additional folder links' : ''}</span>
    </div>
    {(edgeDetail || snapshot.graph.unresolved > 0 || snapshot.graph.limited) && <div className="graph-note" role="status">
      {edgeDetail || [snapshot.graph.unresolved ? snapshot.graph.unresolved + ' connections could not be resolved from the source sample' : '',
        snapshot.graph.limited ? 'Graph index limit reached' : ''].filter(Boolean).join(' · ')}
    </div>}
    {!selected && <div className="graph-shortcuts" role="group" aria-label="Nodes in this view">
      {overview.nodes.map(node => <button key={node.id} onClick={() => selectNode(node)}>
        {node.kind === 'folder' ? <FolderSimple size={15} /> : <ArrowRight size={14} />} {node.label}
      </button>)}
    </div>}
    {(preview || loading || previewError) && <section className="preview" aria-label="Source preview">
      <div className="split"><div><h3 tabIndex={-1} ref={previewTitle}>{preview?.path ?? 'Source preview'}</h3>
        {preview?.url && <a href={preview.url} target="_blank" rel="noreferrer">Open pinned file on GitHub <ArrowUpRight size={14} /></a>}</div>
        <div className="inline-buttons">{preview && <button className="button compact" onClick={() => setDraft(draft === null ? preview.source : null)}>
          {draft === null ? 'Open scratch draft' : 'Discard draft'}</button>}
          <button className="icon-button" aria-label="Close preview" onClick={() => {
            previewSeq.current++; setPreview(null); setLoading(false); setDraft(null); setPreviewError('')
          }}><X size={16} /></button></div>
      </div>
      {loading && <p role="status">Fetching pinned source…</p>}{previewError && <p role="alert">{previewError}</p>}
      {draft !== null ? <label className="draft-field">Local scratch draft<textarea value={draft}
        aria-label="Local scratch draft" onChange={event => setDraft(event.target.value)} spellCheck={false} /></label>
        : preview && <pre ref={sourceBlock}>{preview.source.split('\n').map((line, index) => <span key={index} className={highlight === index + 1 ? 'highlight-line' : ''}>
          <i>{index + 1}</i>{line || ' '}
        </span>)}</pre>}
    </section>}
  </section>
}
