'use client';
import { useState } from 'react';
import { X } from 'lucide-react';
import { post, type Patient } from '../lib/api';

export default function NurseCopilotModal({ patient, onClose, onDone }: { patient: Patient; onClose: () => void; onDone: () => void }) {
  const field = patient.data_quality.missing_fields[0];
  const question = patient.data_quality.next_best_questions[0] || `Record ${field}`;
  const [value, setValue] = useState(''); const [error, setError] = useState('');
  async function submit(event: React.FormEvent) { event.preventDefault(); const numeric = Number(value); if (!Number.isFinite(numeric)) return setError('Enter a numeric observed value.'); try { await post(`/encounters/${patient.patient_id}/answer`, { field, value: numeric, actor: 'nurse' }); onDone(); onClose(); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save observation.'); } }
  return <div className="modal-backdrop"><form className="modal" onSubmit={submit}><button type="button" className="close" onClick={onClose}><X /></button><p className="eyebrow">NURSE COPILOT</p><h2>Capture observation</h2><p>{question}. This updates the assessment; it does not make a diagnosis.</p><label>{field.replace('_', ' ')}<input autoFocus required inputMode="decimal" value={value} onChange={event => setValue(event.target.value)} placeholder="Enter observed value" /></label>{error && <p className="error">{error}</p>}<button className="primary">Save and reassess</button></form></div>;
}
