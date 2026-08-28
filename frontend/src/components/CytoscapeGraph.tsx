'use client';

import { useEffect, useRef, useState } from 'react';
import cytoscape from 'cytoscape';
import type { Patient } from '../lib/api';
import { API } from '../lib/api';
import PatientUpdateModal from './PatientUpdateModal';

export default function CytoscapeGraph({ patient }: { patient: Patient | undefined }) {
  const ref = useRef<HTMLDivElement>(null);
  const [updating, setUpdating] = useState(false);

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
            { selector: 'node', style: { 'background-color': '#315f53', label: 'data(label)', color: '#17201e', 'font-size': 11, 'font-weight': 600, 'text-background-color': '#ffffff', 'text-background-opacity': 1, 'text-background-padding': 3, 'text-border-color': '#d7ddda', 'text-border-width': 1, 'text-valign': 'bottom', 'text-margin-y': 7, width: 20, height: 20 } },
            { selector: 'node[kind = "hub"]', style: { 'background-color': '#315f53', width: 32, height: 32 } },
            { selector: 'node[kind = "critical"]', style: { 'background-color': '#a43835', width: 34, height: 34 } },
            { selector: 'edge', style: { width: 1.5, 'line-color': '#9ba6a2', 'curve-style': 'bezier' } },
            { selector: '.active', style: { 'background-color': '#866a1e', 'line-color': '#866a1e', width: 3 } },
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

  const quality = patient?.data_quality;
  return <div className="graph-wrap">{quality && <div className={`measurement-status ${quality.measurement_review_required ? 'required' : ''}`}><strong>{quality.measurement_review_required ? 'Measurement review required' : quality.status === 'incomplete' ? 'Observations missing' : 'Data complete'}</strong><span>{quality.measurement_review_required ? quality.review_reason : quality.status === 'incomplete' ? `Unknown: ${quality.missing_fields.join(', ')}. Missing values do not change the clinical level.` : 'All expected intake vitals are recorded.'}</span></div>}<div className="graph-heading"><div><strong>Symptom graph</strong><span>Amber nodes and edges are the evidence path for {patient?.patient_id || 'the selected patient'}.</span></div><button className="update-patient" onClick={()=>setUpdating(true)}>Update patient</button></div><div className="graph" ref={ref} />{updating&&patient&&<PatientUpdateModal patient={patient} onClose={()=>setUpdating(false)} onDone={()=>window.dispatchEvent(new Event('medilens-queue-updated'))}/>}</div>;
}
