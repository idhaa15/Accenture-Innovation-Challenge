from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from random import sample

import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.core.queue_decay import check_vitals_re_triage, recompute_queue
from app.db import database
from app.db.models import OverridePayload, PatientInput, SurgePayload, VitalsUpdate
from app.graph.agents import triage
from app.graph.symptom_graph import build_symptom_graph, synaptic_update

GRAPH = build_symptom_graph()
FAILSAFE_MODE = False
SURGE_ACTIVE = False


def serialise_queue() -> list[dict]:
    rows = database.queue_rows()
    if not rows: return []
    now = datetime.now(timezone.utc)
    waits = np.array([max(0, (now - datetime.fromisoformat(row['arrival_ts'])).total_seconds()) for row in rows])
    base = np.array([6 - row['triage_level'] for row in rows], dtype=float)
    dynamic = recompute_queue(base, waits)
    items = []
    for row, score, wait in zip(rows, dynamic, waits):
        row['vitals'] = json.loads(row.pop('vitals_json'))
        row['reasoning_path'] = json.loads(row['reasoning_path'])
        row['wait_seconds'] = int(wait); row['dynamic_score'] = round(float(score), 2)
        items.append(row)
    return sorted(items, key=lambda item: item['dynamic_score'], reverse=True)


async def assess(payload: dict, trigger: str = 'intake') -> dict:
    result = await triage(payload, GRAPH, FAILSAFE_MODE, trigger)
    database.upsert_patient(payload); database.log_triage(result)
    return result


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.initialise()
    if not database.queue_rows():
        records = json.loads((Path(__file__).parent / 'mock_data' / 'simulated_patients.json').read_text())
        for record in records[:5]: await assess(record)
    yield


app = FastAPI(title='PatientTriage.ai', version='1.0.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:3000'], allow_methods=['*'], allow_headers=['*'])


@app.get('/health')
def health(): return {'status': 'ok', 'failsafe_mode': FAILSAFE_MODE}


@app.get('/queue')
def queue(): return {'patients': serialise_queue(), 'failsafe_mode': FAILSAFE_MODE, 'surge_mode': SURGE_ACTIVE}


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
    result = await assess(payload, 'vitals_change' if fired else 'intake')
    return {'reassessment_fired': fired, 'result': result}


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
    for record in candidates[:payload.count]: await assess(record)
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


@app.post('/override')
def override(payload: OverridePayload):
    latest = database.latest_triage(payload.patient_id)
    if not latest: raise HTTPException(404, 'No assessment found for this patient')
    override_id = database.record_override(payload.patient_id, payload.clinician_id, latest['triage_level'], latest['confidence'], payload.overridden_level, payload.justification, payload.jurisdiction)
    delta = 1 if payload.overridden_level < latest['triage_level'] else -1 if payload.overridden_level > latest['triage_level'] else 0
    paths = json.loads(latest['reasoning_path'])
    nodes = next((r['graph_nodes_visited'] for r in paths if r['agent_name'] == 'Safety Adversary'), [])
    updates = []
    for source, target in zip(nodes, nodes[1:]):
        old, new = synaptic_update(GRAPH, source, target, delta)
        if old != new: database.record_weight(source, target, old, new, override_id); updates.append({'source': source, 'target': target, 'old_weight': old, 'new_weight': new})
    return {'override_id': override_id, 'audit_logged': True, 'weight_updates': updates}


@app.websocket('/ws/queue')
async def queue_socket(socket: WebSocket):
    await socket.accept()
    try:
        while True:
            await socket.send_json({'patients': serialise_queue(), 'failsafe_mode': FAILSAFE_MODE})
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        return
