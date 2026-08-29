from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.core.queue_decay import check_vitals_re_triage, within_bucket_priority
from app.db import database
from app.db.models import OverridePayload, PatientInput, SurgePayload, VitalAnswer, Vitals, VitalsUpdate
from app.graph.agents import PROVIDER_CALL_COUNTS, triage
from app.graph.symptom_graph import build_symptom_graph, synaptic_update

GRAPH = build_symptom_graph()
FAILSAFE_MODE = False
SURGE_ACTIVE = False


def serialise_queue() -> list[dict]:
    database.refresh_reassessment_due()
    rows = database.queue_rows()
    if not rows: return []
    now = datetime.now(timezone.utc)
    waits = np.array([max(0, (now - datetime.fromisoformat(row['arrival_ts'])).total_seconds()) for row in rows])
    intervals = np.array([row.get('reassessment_interval_seconds') or 300 for row in rows], dtype=float)
    fairness = within_bucket_priority(waits, intervals)
    items = []
    for row, score, wait in zip(rows, fairness, waits):
        row['vitals'] = json.loads(row.pop('vitals_json'))
        row['reasoning_path'] = json.loads(row['reasoning_path'])
        row['explanation'] = json.loads(row.pop('explanation_json', '{}'))
        row['data_quality'] = json.loads(row.pop('data_quality_json', '{}'))
        row['llm_response'] = json.loads(row.pop('llm_response_json', '{}'))
        row['measurement_review_required'] = bool(row['data_quality'].get('measurement_review_required'))
        row['wait_seconds'] = int(wait); row['dynamic_score'] = round(float(score), 2)
        items.append(row)
    # Acuity is a hard boundary. The following safety signals order only within
    # the same prototype urgency level: detected deterioration, required
    # measurement review, overdue reassessment, then wait-time fairness.
    return sorted(items, key=lambda item: (
        item['triage_level'],
        not bool(item.get('deteriorating')),
        not bool(item.get('measurement_review_required')),
        not bool(item.get('reassessment_due')),
        -item['dynamic_score'],
        -item['wait_seconds'],
        item['arrival_ts'],
    ))


async def assess(payload: dict, trigger: str = 'intake') -> dict:
    result = await triage(payload, GRAPH, FAILSAFE_MODE, trigger)
    database.upsert_patient(payload); database.log_triage(result)
    database.complete_reassessment(payload['patient_id'], trigger == 'vitals_change')
    return result


async def assess_many(records: list[dict], trigger: str = 'intake') -> list[dict]:
    limit = asyncio.Semaphore(8)

    async def bounded(record: dict) -> dict:
        async with limit:
            return await assess(record, trigger)

    return await asyncio.gather(*(bounded(record) for record in records))


def restore_graph_weights() -> int:
    updates = database.weight_history()
    for update in updates:
        if GRAPH.has_edge(update['source_node'], update['target_node']):
            GRAPH[update['source_node']][update['target_node']]['weight'] = update['new_weight']
    return len(updates)


def needs_legacy_reassessment(patient_id: str) -> bool:
    """Recover active records created before a triage log was written."""
    latest = database.latest_triage(patient_id)
    if not latest:
        return True
    try:
        return not bool(json.loads(latest.get('explanation_json') or '{}'))
    except (TypeError, json.JSONDecodeError):
        return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.initialise()
    restored = restore_graph_weights()
    print(f'Restored {restored} historical graph weight update(s).')
    if not database.queue_rows():
        records = json.loads((Path(__file__).parent / 'mock_data' / 'simulated_patients.json').read_text())
        await assess_many(records[:5])
    else:
        legacy = [patient for patient in database.active_patient_inputs() if needs_legacy_reassessment(patient['patient_id'])]
        if legacy:
            await assess_many(legacy)
    yield


app = FastAPI(title='PatientTriage.ai', version='1.0.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:3000'], allow_methods=['*'], allow_headers=['*'])


@app.get('/health')
def health(): return {'status': 'ok', 'failsafe_mode': FAILSAFE_MODE}


@app.get('/queue')
def queue(): return {'patients': serialise_queue(), 'failsafe_mode': FAILSAFE_MODE, 'surge_mode': SURGE_ACTIVE}


@app.get('/status')
def status():
    stats = database.recent_action_stats()
    return {'queue_depth': len(database.queue_rows()), 'fallback_rate_5m': stats['fallbacks'] / max(1, stats['actions']), 'provider_calls': PROVIDER_CALL_COUNTS}


@app.post('/triage/intake')
async def intake(patient: PatientInput): return await assess(patient.model_dump())


@app.post('/patients/{patient_id}/vitals')
async def update_vitals(patient_id: str, update: VitalsUpdate):
    patient = database.get_patient(patient_id)
    if not patient: raise HTTPException(404, 'Patient not found')
    prior = json.loads(patient['vitals_json']); current = update.vitals.model_dump()
    payload = {**patient, 'vitals': current}
    payload.pop('vitals_json', None); payload.pop('age_band', None); payload.pop('arrival_ts', None); payload.pop('consent_flag', None)
    fired = check_vitals_re_triage(current, prior, database.age_band(patient['age_years']))
    result = await assess(payload, 'vitals_change' if fired else 'reassessment')
    return {'reassessment_fired': fired, 'result': result}


@app.post('/encounters/{patient_id}/update')
async def update_encounter(patient_id: str, update: dict):
    patient = database.get_patient(patient_id)
    if not patient: raise HTTPException(404, 'Patient not found')
    try:
        vitals = Vitals.model_validate(update.get('vitals', json.loads(patient['vitals_json']))).model_dump()
        complaint = str(update.get('chief_complaint', patient['chief_complaint'])).strip()
        if len(complaint) < 3: raise ValueError('Chief complaint must be at least 3 characters')
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    payload = {key: patient.get(key, '') for key in ('patient_id', 'patient_name', 'gender', 'pronouns', 'preferred_language', 'age_years', 'has_prior_history', 'self_reported_pain')}
    payload.update({'chief_complaint': complaint, 'vitals': vitals})
    result = await assess(payload, 'reassessment')
    changed_vitals = [field for field, value in vitals.items() if value != json.loads(patient['vitals_json']).get(field)]
    database.record_action(patient_id, 'clinician', 'patient-update', {'updated_fields': (['chief_complaint'] if complaint != patient['chief_complaint'] else []) + changed_vitals, 'trigger': 'reassessment'})
    return {'result': result, 'queue_updated': True}


@app.post('/surge')
async def surge(payload: SurgePayload):
    global SURGE_ACTIVE
    records = json.loads((Path(__file__).parent / 'mock_data' / 'simulated_patients.json').read_text())
    if SURGE_ACTIVE:
        baseline_ids = {record['patient_id'] for record in records[:5]}
        surge_ids = [record['patient_id'] for record in records if record['patient_id'] not in baseline_ids]
        database.delete_patients(surge_ids)
        SURGE_ACTIVE = False
        return {'added': 0, 'removed': len(surge_ids), 'patients': serialise_queue(), 'surge_mode': SURGE_ACTIVE}
    existing = {p['patient_id'] for p in database.queue_rows()}
    candidates = [p for p in records if p['patient_id'] not in existing]
    await assess_many(candidates[:payload.count])
    SURGE_ACTIVE = True
    return {'added': min(payload.count, len(candidates)), 'patients': serialise_queue(), 'surge_mode': SURGE_ACTIVE}


@app.post('/surge/reset')
def reset_surge():
    global SURGE_ACTIVE
    records = json.loads((Path(__file__).parent / 'mock_data' / 'simulated_patients.json').read_text())
    baseline_ids = {record['patient_id'] for record in records[:5]}
    surge_ids = [record['patient_id'] for record in records if record['patient_id'] not in baseline_ids]
    database.delete_patients(surge_ids)
    SURGE_ACTIVE = False
    return {'removed': len(surge_ids), 'patients': serialise_queue(), 'surge_mode': SURGE_ACTIVE}


@app.post('/demo/failsafe')
def toggle_failsafe():
    global FAILSAFE_MODE
    FAILSAFE_MODE = not FAILSAFE_MODE
    return {'failsafe_mode': FAILSAFE_MODE}


@app.get('/graph')
def graph():
    return {'nodes': [{'data': {'id': n, 'label': n.replace('_', ' '), 'kind': d['kind']}} for n, d in GRAPH.nodes(data=True)], 'edges': [{'data': {'id': f'{a}-{b}', 'source': a, 'target': b, 'weight': d['weight']}} for a,b,d in GRAPH.edges(data=True)]}


def _apply_clinician_level(payload: OverridePayload, action_type: str) -> dict:
    latest = database.latest_triage(payload.patient_id)
    if not latest: raise HTTPException(404, 'No assessment found for this patient')
    delta = 1 if payload.overridden_level < latest['triage_level'] else -1 if payload.overridden_level > latest['triage_level'] else 0
    paths = json.loads(latest['reasoning_path'])
    nodes = next((r['graph_nodes_visited'] for r in paths if r['agent_name'] == 'Safety Adversary'), [])
    updates = []
    for source, target in zip(nodes, nodes[1:]):
        old, new = synaptic_update(GRAPH, source, target, delta)
        if old != new: updates.append({'source': source, 'target': target, 'old_weight': old, 'new_weight': new})
    override_id = database.record_override_with_weights(payload.patient_id, payload.clinician_id, latest['triage_level'], latest['confidence'], payload.overridden_level, payload.justification, payload.jurisdiction, [(item['source'], item['target'], item['old_weight'], item['new_weight']) for item in updates])
    reasoning = json.loads(latest['reasoning_path'])
    reasoning.append({'agent_name': 'Clinician decision', 'graph_nodes_visited': [], 'conclusion': f'{action_type.replace("_", " ").title()}: Level {payload.overridden_level}. {payload.justification}', 'confidence_delta': 0.0})
    explanation = json.loads(latest['explanation_json'])
    explanation['summary'] = f'Clinician-set Level {payload.overridden_level}: {payload.justification}'
    explanation.setdefault('evidence', []).append('Clinician decision is the active queue priority.')
    explanation['why_this_level'] = 'A licensed clinician supplied a documented queue decision.'
    database.log_triage({
        'patient_id': payload.patient_id, 'updated_at': datetime.now(timezone.utc).isoformat(),
        'triage_level': payload.overridden_level, 'confidence': 1.0,
        'escalated_for_uncertainty': payload.overridden_level <= 2, 'degraded_mode': False,
        'reasoning_path': reasoning, 'trigger_reason': action_type,
        'explanation': explanation, 'recommended_department': latest['recommended_department'],
        'routing_confidence': 'high', 'data_quality': json.loads(latest['data_quality_json']),
        'disclaimer': latest['disclaimer'],
    })
    database.complete_reassessment(payload.patient_id, payload.overridden_level < latest['triage_level'])
    return {'override_id': override_id, 'triage_level': payload.overridden_level, 'audit_logged': True, 'weight_updates': updates}


@app.post('/override')
def override(payload: OverridePayload):
    return _apply_clinician_level(payload, 'clinician_override')


@app.post('/encounters/{patient_id}/accept')
def accept(patient_id: str, actor: str = 'clinician'):
    if not database.latest_triage(patient_id): raise HTTPException(404, 'No assessment found for this patient')
    database.set_encounter_status(patient_id, 'in_treatment')
    return {'action_id': database.record_action(patient_id, actor, 'accept', {'status': 'accepted'}), 'audit_logged': True}


@app.post('/encounters/{patient_id}/override')
def encounter_override(patient_id: str, payload: OverridePayload):
    if payload.patient_id != patient_id: raise HTTPException(400, 'Patient identifier mismatch')
    result = _apply_clinician_level(payload, 'clinician_override')
    database.record_action(patient_id, payload.clinician_id, 'override', {'override_id': result['override_id'], 'justification': payload.justification})
    return result


@app.post('/encounters/{patient_id}/escalate-now')
def escalate_now(patient_id: str, actor: str = 'clinician'):
    latest = database.latest_triage(patient_id)
    if not latest: raise HTTPException(404, 'No assessment found for this patient')
    result = _apply_clinician_level(OverridePayload(patient_id=patient_id, clinician_id=actor, overridden_level=1, justification='Manual immediate escalation by clinician.', jurisdiction='HIPAA'), 'manual_escalation')
    result['action_id'] = database.record_action(patient_id, actor, 'escalate-now', {'level': 1, 'reason': 'manual escalation'})
    return result


@app.post('/encounters/{patient_id}/answer')
async def answer(patient_id: str, answer: VitalAnswer):
    patient = database.get_patient(patient_id)
    if not patient: raise HTTPException(404, 'Patient not found')
    vitals = json.loads(patient['vitals_json'])
    vitals[answer.field] = answer.value
    vitals = Vitals.model_validate(vitals).model_dump()
    payload = {key: patient[key] for key in ('patient_id', 'patient_name', 'gender', 'pronouns', 'preferred_language', 'age_years', 'has_prior_history', 'chief_complaint', 'self_reported_pain')}; payload['vitals'] = vitals
    result = await assess(payload, 'reassessment')
    database.record_action(patient_id, answer.actor, 'answer', {'field': answer.field})
    return result


@app.post('/encounters/{patient_id}/second-opinion')
def second_opinion(patient_id: str, actor: str = 'clinician'):
    if not database.get_patient(patient_id): raise HTTPException(404, 'Patient not found')
    return {'action_id': database.record_action(patient_id, actor, 'second-opinion', {'review_requested': True}), 'audit_logged': True}


@app.patch('/encounters/{patient_id}/reassessment-interval')
def reassessment_interval(patient_id: str, payload: dict):
    if not database.get_patient(patient_id): raise HTTPException(404, 'Patient not found')
    seconds = payload.get('seconds')
    if not isinstance(seconds, int) or seconds < 10 or seconds > 3600: raise HTTPException(400, 'seconds must be between 10 and 3600')
    database.set_reassessment_interval(patient_id, seconds)
    return {'action_id': database.record_action(patient_id, payload.get('actor', 'clinician'), 'reassessment-interval', {'seconds': seconds}), 'next_reassessment_scheduled': True, 'audit_logged': True}


@app.websocket('/ws/queue')
async def queue_socket(socket: WebSocket):
    await socket.accept()
    try:
        while True:
            await socket.send_json({'patients': serialise_queue(), 'failsafe_mode': FAILSAFE_MODE})
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        return
