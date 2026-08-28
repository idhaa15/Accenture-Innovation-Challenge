'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import { Activity, BrainCircuit, Check, ChevronRight, ClipboardCheck, FilePlus2, HeartPulse, MessageCircleQuestion, RefreshCw, ShieldAlert, Stethoscope, UserRound, UserRoundCheck, X, Zap } from 'lucide-react';
import CytoscapeGraph from '../components/CytoscapeGraph';
import DegradedModeBanner from '../components/DegradedModeBanner';
import OverrideModal from '../components/OverrideModal';
import SurgeToggle from '../components/SurgeToggle';
import { getQueue, post, type Patient } from '../lib/api';

const levels = ['Resuscitation', 'Emergent', 'Urgent', 'Less urgent', 'Non-urgent'];
const blankVitals = { heart_rate: '', resp_rate: '', temp_c: '', spo2: '', systolic_bp: '' };
function toNumber(value: string) { return value === '' ? null : Number(value); }
function normalizePatient(patient: Patient): Patient {
  return {
    ...patient,
    explanation: { summary: patient.explanation?.summary || 'Explanation unavailable for this legacy assessment.', evidence: patient.explanation?.evidence || [], why_this_level: patient.explanation?.why_this_level || 'Review the processing trace and current observations.' },
    data_quality: { status: patient.data_quality?.status || 'complete', missing_fields: patient.data_quality?.missing_fields || [], invalid_fields: patient.data_quality?.invalid_fields || [], stale_fields: patient.data_quality?.stale_fields || [], next_best_questions: patient.data_quality?.next_best_questions || [] },
    reasoning_path: patient.reasoning_path || [],
  };
}

export default function Home() {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [selected, setSelected] = useState<Patient>();
  const [started, setStarted] = useState(false);
  const [showIntake, setShowIntake] = useState(false);
  const [override, setOverride] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [failsafe, setFailsafe] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const queue = await getQueue();
      const normalized = queue.patients.map(normalizePatient);
      setPatients(normalized);
      setFailsafe(queue.failsafe_mode);
      setSelected(current => normalized.find(patient => patient.patient_id === current?.patient_id) || current || normalized[0]);
      setError('');
    } catch { setError('Backend unavailable. Start FastAPI on port 8000.'); }
  }, []);
  useEffect(() => { refresh(); const timer = setInterval(refresh, 3000); return () => clearInterval(timer); }, [refresh]);

  async function action(path: string, body?: unknown) {
    setBusy(true);
    try { await post(path, body); await refresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Request failed'); } finally { setBusy(false); }
  }
  async function submitIntake(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get('patient_name') || '').trim();
    const patientId = String(form.get('patient_id') || '').trim() || `PT-${Date.now().toString().slice(-6)}`;
    await action('/triage/intake', {
      patient_id: patientId, patient_name: name, age_years: Number(form.get('age_years')), has_prior_history: form.get('has_prior_history') === 'yes',
      chief_complaint: String(form.get('chief_complaint') || ''), self_reported_pain: toNumber(String(form.get('pain') || '')),
      vitals: Object.fromEntries(Object.entries(blankVitals).map(([key]) => [key, toNumber(String(form.get(key) || ''))])),
    });
    setShowIntake(false); setStarted(true); (event.target as HTMLFormElement).reset();
  }
  const worsen = () => selected && action(`/patients/${selected.patient_id}/vitals`, { vitals: { ...selected.vitals, heart_rate: (selected.vitals.heart_rate || 90) + 30, spo2: Math.max(70, (selected.vitals.spo2 || 96) - 5) } });
  const ask = () => { if (!selected?.data_quality.next_best_questions[0]) return; const value = prompt(selected.data_quality.next_best_questions[0]); if (value) action(`/encounters/${selected.patient_id}/answer`, { field: selected.data_quality.missing_fields[0], value: Number(value) || value }); };

  return <main>
    <header><div className="brand"><div className="brand-icon"><HeartPulse /></div><div><h1>PatientTriage<span>.ai</span></h1><p>SAFETY-FIRST ED DECISION SUPPORT</p></div></div><div className="status"><i /> LIVE QUEUE <span>DEMO MODE</span></div></header>
    <DegradedModeBanner active={failsafe || patients.some(patient => patient.degraded_mode)} />
    {error && <div className="notice"><ShieldAlert size={16} /> {error}<button onClick={() => setError('')}><X size={15} /></button></div>}
    {!started ? <section className="welcome"><div className="welcome-mark"><HeartPulse size={42} /></div><p className="eyebrow">CLINICAL OPERATIONS CONSOLE</p><h2>PatientTriage.ai</h2><p>Safety-first emergency department decision support for continuous, explainable triage.</p><button className="start-button" onClick={() => { setStarted(true); setShowIntake(true); }}><FilePlus2 size={18} /> Start a new assessment</button><small>Fictional demo data only · clinician remains the final decision-maker</small></section> : <>
      <section className="toolbar"><div><strong>Emergency Department</strong><small>{patients.length} active encounters · queue recalculates every 3 seconds</small></div><div className="actions"><button onClick={() => action('/demo/failsafe')}><Zap size={15} /> Fail-safe: {failsafe ? 'ON' : 'OFF'}</button><SurgeToggle disabled={busy} onClick={() => action('/surge', { count: 10 })} /><button onClick={refresh}><RefreshCw size={15} /> Refresh</button><button className="primary" onClick={() => setShowIntake(true)}><FilePlus2 size={15} /> New patient</button></div></section>
      <div className="layout"><aside><div className="queue-title"><div><h2>Current queue</h2><p>Sorted by acuity, deterioration and wait</p></div><span className="queue-count">{patients.length}</span></div><div className="patients">{patients.map(patient => <button className={`queue-row ${selected?.patient_id === patient.patient_id ? 'selected' : ''}`} key={patient.patient_id} onClick={() => setSelected(patient)}><span className={`level l${patient.triage_level}`}>L{patient.triage_level}</span><span className="queue-copy"><b>{patient.patient_id}</b><span>{patient.chief_complaint}</span><small>{levels[patient.triage_level - 1]} · {patient.recommended_department}</small></span><ChevronRight size={16} /></button>)}</div></aside>
        <section className="workspace">{selected ? <><div className="hero"><div><div className="eyebrow"><BrainCircuit size={15} /> EXPLAINABLE TRIAGE RESULT</div><h2>{selected.patient_id}</h2><p>{selected.chief_complaint}</p></div><div className={`big-level l${selected.triage_level}`}>LEVEL <b>{selected.triage_level}</b><small>{levels[selected.triage_level - 1]}</small></div></div><div className="summary-strip"><div><span>Recommended department</span><strong>{selected.recommended_department}</strong><small>{selected.routing_confidence} routing confidence</small></div><div><span>Priority score</span><strong>{selected.dynamic_score}</strong><small>{Math.floor(selected.wait_seconds / 60)}m wait decay</small></div><div><span>Confidence</span><strong>{Math.round(selected.confidence * 100)}%</strong><small>{selected.degraded_mode ? 'Deterministic fallback' : 'Model assisted'}</small></div></div><div className="detail-grid"><div className="detail-panel"><h3><ClipboardCheck size={17} /> Why this level?</h3><p className="full-summary">{selected.explanation?.summary}</p><p>{selected.explanation?.why_this_level}</p><div className="evidence">{selected.explanation?.evidence.map(item => <span key={item}>• {item}</span>)}</div></div><div className="detail-panel"><h3><Activity size={17} /> Patient details</h3><div className="patient-facts"><span><UserRound size={14} /> {selected.age_years} years · {selected.age_band}</span><span><UserRoundCheck size={14} /> {selected.demographic_flags?.join('; ') || 'No demographic flags'}</span></div><div className="vitals">{Object.entries(selected.vitals).map(([key, value]) => <span key={key}>{key.replace('_', ' ').toUpperCase()}<b>{value ?? 'Missing'}</b></span>)}</div></div></div><div className="detail-panel reasoning"><h3><Stethoscope size={17} /> Processing trace</h3>{selected.reasoning_path.map(reason => <div className="reason" key={reason.agent_name}><b>{reason.agent_name}</b><ChevronRight size={14} /><span>{reason.conclusion}</span></div>)}</div><div className="action-bar"><button className="accept" onClick={() => action(`/encounters/${selected.patient_id}/accept`)}><Check size={16} /> Accept</button><button onClick={() => setOverride(true)}><Stethoscope size={16} /> Override</button><button className="escalate" onClick={() => action(`/encounters/${selected.patient_id}/escalate-now`)}><ShieldAlert size={16} /> Escalate Now</button>{selected.data_quality?.next_best_questions?.length > 0 && <button onClick={ask}><MessageCircleQuestion size={16} /> Ask</button>}<button title="Request second opinion" onClick={() => action(`/encounters/${selected.patient_id}/second-opinion`)}><UserRoundCheck size={16} /> Second opinion</button><label className="interval">Reassess<select onChange={event => action(`/encounters/${selected.patient_id}/reassessment-interval`, { seconds: Number(event.target.value) })} defaultValue="300"><option value="60">1 min</option><option value="300">5 min</option><option value="900">15 min</option><option value="1800">30 min</option></select></label><button className="danger" onClick={worsen}><Activity size={16} /> Worsen vitals</button></div><p className="data-note">{selected.data_quality?.status === 'incomplete' ? `Missing: ${selected.data_quality.missing_fields.join(', ')}` : 'All expected intake vitals recorded.'}</p><CytoscapeGraph patient={selected} /></> : <div className="empty"><HeartPulse size={30} /><h2>No active patient selected</h2><button className="primary" onClick={() => setShowIntake(true)}>Start assessment</button></div>}</section></div>
    </>}
    {showIntake && <div className="modal-backdrop"><form className="modal intake-modal" onSubmit={submitIntake}><button type="button" className="close" onClick={() => setShowIntake(false)}><X /></button><p className="eyebrow">NEW ENCOUNTER</p><h2>Patient intake</h2><p className="modal-help">Enter observed information. Missing high-risk vitals remain visible and lower confidence.</p><div className="form-grid"><label>Patient name<input name="patient_name" required placeholder="Fictional patient name" /></label><label>Patient ID<input name="patient_id" placeholder="Optional · auto-generated" /></label><label>Age<input name="age_years" type="number" min="0" max="130" required /></label><label>Prior history<select name="has_prior_history" defaultValue="yes"><option value="yes">Known history</option><option value="no">No history available</option></select></label></div><label>Chief complaint<textarea name="chief_complaint" required minLength={3} placeholder="What brought the patient to the ED?" /></label><div className="form-grid vitals-form">{Object.entries(blankVitals).map(([key]) => <label key={key}>{key.replace('_', ' ')}<input name={key} type="number" step={key === 'temp_c' ? '0.1' : '1'} placeholder="Optional" /></label>)}</div><label>Self-reported pain (0-10)<input name="pain" type="number" min="0" max="10" /></label><p className="privacy-note">Patient details are redacted before any configured third-party AI call. Local-only mode is supported.</p><button className="primary submit-button" disabled={busy}><HeartPulse size={17} /> {busy ? 'Processing...' : 'Process and add to queue'}</button></form></div>}
    {override && selected && <OverrideModal patient={selected} onClose={() => setOverride(false)} onDone={refresh} />}
  </main>;
}
