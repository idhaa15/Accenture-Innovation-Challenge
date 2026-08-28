'use client';

import { useEffect, useRef } from 'react';
import cytoscape from 'cytoscape';
import type { Patient } from '../lib/api';
import { API } from '../lib/api';

export default function CytoscapeGraph({ patient }: { patient: Patient | undefined }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cy: cytoscape.Core | undefined;
    let cancelled = false;
    const controller = new AbortController();

    fetch(`${API}/graph`, { signal: controller.signal })
      .then((response) => response.json())
      .then((data) => {
        if (cancelled || !ref.current) return;
        const active = new Set(patient?.reasoning_path.flatMap((step) => step.graph_nodes_visited) || []);
        cy = cytoscape({
          container: ref.current,
          elements: [
            ...data.nodes.map((node: any, index: number) => ({ ...node, position: { x: 80 + (index % 6) * 150, y: 60 + Math.floor(index / 6) * 105 }, classes: active.has(node.data.id) ? 'active' : '' })),
            ...data.edges.map((edge: any) => ({
              ...edge,
              classes: active.has(edge.data.source) && active.has(edge.data.target) ? 'active' : '',
            })),
          ],
          style: [
            { selector: 'node', style: { 'background-color': '#2f7668', label: 'data(label)', color: '#b9d7d0', 'font-size': 8, 'text-valign': 'bottom', 'text-margin-y': 4, width: 18, height: 18 } },
            { selector: 'node[kind = "hub"]', style: { 'background-color': '#10b981', width: 30, height: 30 } },
            { selector: 'node[kind = "critical"]', style: { 'background-color': '#ef4444', width: 32, height: 32 } },
            { selector: 'edge', style: { width: 1, 'line-color': '#2b5750', 'curve-style': 'bezier' } },
            { selector: '.active', style: { 'background-color': '#f59e0b', 'line-color': '#f59e0b', width: 3 } },
          ],
          layout: { name: 'preset', padding: 24 },
        });
      })
      .catch((error) => {
        if (error.name !== 'AbortError') console.error('Unable to load symptom graph', error);
      });

    return () => {
      cancelled = true;
      controller.abort();
      cy?.destroy();
    };
  }, [patient]);

  return <div className="graph-wrap"><div className="graph-heading"><div><strong>Symptom graph</strong><span>Amber nodes and edges are the evidence path for {patient?.patient_id || 'the selected patient'}.</span></div><small>Green = risk hub · red = critical endpoint · muted = available graph knowledge</small></div><div className="graph" ref={ref} /></div>;
}