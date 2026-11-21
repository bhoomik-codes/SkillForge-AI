import { useEffect, useRef, useState } from 'react'
import cytoscape from 'cytoscape'
import { ArrowUpRight, GitBranch } from '@phosphor-icons/react'
import { recordLabel } from './DecisionChat'
import type { RecordLink, RecordNode, Trail } from './DecisionChat'

const edgeLabels: Record<string, string> = {
  HAS_COMMENT: 'Has comment', REFERENCES: 'References', DECLARES_FIX: 'Declares a fix',
  REPORTS_REGRESSION_FROM: 'Reports regression from', MERGED_AS: 'Merged as', CLOSED: 'Closed',
  CHANGES_FILE: 'Changed file', ASSOCIATED_WITH: 'Associated PR', CROSS_REFERENCED: 'Cross-referenced',
}

const kindColors: Record<string, string> = { pr: '#b4e078', issue: '#f1b578', commit: '#8eb6ec', discussion: '#cfb0ed' }

export default function EvidenceGraph({ graph }: { graph: Trail['graph'] }) {
  const canvas = useRef<HTMLDivElement>(null)
  const [selected, setSelected] = useState<RecordNode | RecordLink>()
  useEffect(() => {
    if (!canvas.current || !graph.nodes.length) return
    const cy = cytoscape({
      container: canvas.current, maxZoom: 2.2, minZoom: 0.25,
      elements: [
        ...graph.nodes.map(node => ({ data: { id: node.id, label: recordLabel(node), shade: kindColors[node.kind] ?? '#a2ac9c' } })),
        ...graph.edges.map((edge, index) => ({
          data: { id: 'edge-' + index, source: edge.source, target: edge.target, label: edgeLabels[edge.kind] ?? edge.kind },
        })),
      ],
      style: [
        { selector: 'node', style: { 'background-color': 'data(shade)', color: '#edf1e9', label: 'data(label)',
          'font-size': 12, 'text-valign': 'bottom', 'text-margin-y': 7, width: 21, height: 21 } },
        { selector: 'edge', style: { width: 1.5, 'curve-style': 'bezier', 'line-color': '#6d7f71',
          'target-arrow-color': '#9aab9e', 'target-arrow-shape': 'triangle' } },
        { selector: ':selected', style: { 'overlay-color': '#e0f6aa', 'overlay-opacity': 0.18 } },
      ],
      layout: { name: graph.edges.length ? 'breadthfirst' : 'grid', directed: true, padding: 34, spacingFactor: 1.5 },
    })
    cy.on('tap', 'node', event => setSelected(graph.nodes.find(node => node.id === event.target.id())))
    cy.on('tap', 'edge', event => setSelected(graph.edges[Number(event.target.id().slice(5))]))
    const observer = new ResizeObserver(() => cy.resize())
    observer.observe(canvas.current)
    return () => { observer.disconnect(); cy.destroy() }
  }, [graph])

  if (!graph.nodes.length) return null
  return <details className="decision-trail" open>
    <summary><GitBranch size={16} /> Decision trail <span>{graph.nodes.length} records · {graph.edges.length} links</span></summary>
    <div ref={canvas} className="decision-canvas" aria-hidden="true" />
    {selected && <div className="decision-inspector">
      <strong>{'id' in selected ? recordLabel(selected) + ' · ' + selected.title : edgeLabels[selected.kind] ?? selected.kind}</strong>
      <p>{('id' in selected ? selected.body : selected.evidence).slice(0, 550)}</p>
      <a href={selected.url} target="_blank" rel="noreferrer">Open GitHub evidence <ArrowUpRight size={13} /></a>
    </div>}
    <details className="decision-trail-list">
      <summary>Browse evidence and relationships</summary>
      <ul>{graph.nodes.map(node => <li key={node.id}><a href={node.url} target="_blank" rel="noreferrer">
        {recordLabel(node)} · {node.title}
      </a></li>)}</ul>
      <ul>{graph.edges.map(edge => <li key={[edge.source, edge.target, edge.kind].join('-')}>
        <a href={edge.url} target="_blank" rel="noreferrer">{edge.source} → {edgeLabels[edge.kind] ?? edge.kind} → {edge.target}</a>
        {edge.evidence && <small>{edge.evidence}</small>}
      </li>)}</ul>
    </details>
  </details>
}
