from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import networkx as nx

from app.db.database import age_band
from app.graph.symptom_graph import CRITICAL_NODES

KEYWORDS = {
    'chest_pain': ['chest', 'epigastric'], 'jaw_pain': ['jaw'], 'nausea': ['nausea'], 'fever': ['fever'],
    'lethargy': ['letharg'], 'poor_feeding': ['poor feeding'], 'confusion': ['confusion', 'not himself'],
    'trauma': ['mvc', 'trauma', 'accident'], 'deformity': ['deform'], 'ankle_pain': ['ankle'],
    'shortness_of_breath': ['shortness', 'breathless'], 'cough': ['cough'], 'wheeze': ['wheeze'],
    'abdominal_pain': ['abdominal', 'stomach'], 'headache': ['headache'], 'weakness': ['weakness'],
    'speech_change': ['speech', 'slurred'], 'vomiting': ['vomit'], 'dizziness': ['dizz'], 'fainting': ['faint'],
    'bleeding': ['bleed'], 'burn': ['burn'], 'rash': ['rash'], 'back_pain': ['back pain'],
}


def extract_symptoms(patient: dict) -> list[str]:
    text = patient['chief_complaint'].lower()
    result = [label for label, words in KEYWORDS.items() if any(word in text for word in words)]
    vitals = patient['vitals']
    if vitals.get('spo2') is not None and vitals['spo2'] < 94: result.append('low_spo2')
    if vitals.get('heart_rate') is not None and vitals['heart_rate'] > 100: result.append('tachycardia')
    if vitals.get('systolic_bp') is not None and vitals['systolic_bp'] < 90: result.append('low_bp')
    return list(dict.fromkeys(result))


async def demographic_specialist(patient: dict) -> tuple[list[str], int, float]:
    age, vitals = patient['age_years'], patient['vitals']
    band, flags, urgency, confidence = age_band(age), [], 5, .86
    if not patient['has_prior_history']:
        flags.append('No prior history available: uncertainty elevated'); confidence -= .13
    missing = [k for k, v in vitals.items() if v is None]
    if missing:
        flags.append(f'Missing intake vital(s): {", ".join(missing)}'); confidence -= .18; urgency = min(urgency, 3)
    hr, rr, temp, spo2, bp = vitals.get('heart_rate'), vitals.get('resp_rate'), vitals.get('temp_c'), vitals.get('spo2'), vitals.get('systolic_bp')
    if band == 'pediatric':
        if hr and hr > 160: flags.append('Pediatric tachycardia'); urgency = min(urgency, 2)
        if rr and rr > 40: flags.append('Pediatric elevated respiratory rate'); urgency = min(urgency, 2)
        if temp and temp >= 38: flags.append('Pediatric fever'); urgency = min(urgency, 2)
        if spo2 and spo2 < 95: flags.append('Pediatric oxygen concern'); urgency = min(urgency, 2)
    elif band == 'geriatric':
        if temp and (temp >= 37.8 or temp < 36): flags.append('Geriatric temperature risk'); urgency = min(urgency, 2)
        if spo2 and spo2 < 92: flags.append('Oxygen concern'); urgency = min(urgency, 2)
        if 'confusion' in patient['chief_complaint'].lower() or 'not himself' in patient['chief_complaint'].lower(): flags.append('New geriatric confusion'); urgency = min(urgency, 2)
    else:
        if temp and temp >= 38: flags.append('Fever'); urgency = min(urgency, 3)
        if spo2 and spo2 < 94: flags.append('Low oxygen saturation'); urgency = min(urgency, 1)
    if hr and hr > 130: flags.append('Severe tachycardia'); urgency = min(urgency, 2)
    if bp and bp < 90: flags.append('Hypotension'); urgency = min(urgency, 1)
    return flags, urgency, max(.35, confidence)


async def safety_adversary(symptoms: list[str], graph: nx.Graph) -> tuple[list[str], int]:
    paths: list[str] = []
    for symptom in symptoms:
        if symptom not in graph: continue
        for critical in CRITICAL_NODES:
            try:
                path = nx.shortest_path(graph, symptom, critical)
                if len(path) <= 3:
                    paths.append(' -> '.join(path))
            except nx.NetworkXNoPath:
                pass
    return paths[:4], (1 if any('respiratory_failure' in p or 'internal_bleeding' in p for p in paths) else 2 if paths else 5)


async def triage(patient: dict, graph: nx.Graph, degraded_mode: bool = False, trigger_reason: str = 'intake') -> dict:
    symptoms = extract_symptoms(patient)
    flags, demographic_level, confidence = await demographic_specialist(patient)
    paths, adversary_level = await safety_adversary(symptoms, graph)
    pain = patient.get('self_reported_pain') or 0
    base = min(demographic_level, adversary_level, 2 if pain >= 8 else 5)
    if paths: flags.append('Safety adversary found a short path to a critical condition')
    if not symptoms: confidence -= .12
    if degraded_mode: confidence = min(confidence, .62); flags.append('External AI unavailable: deterministic fail-safe active')
    escalated = confidence < .70 or bool(paths)
    if confidence < .70: base = max(1, base - 1)
    reasoning = [
        {'agent_name': 'Node Extraction', 'graph_nodes_visited': symptoms, 'conclusion': f'Activated {len(symptoms)} symptom node(s).', 'confidence_delta': 0.0},
        {'agent_name': 'Demographic Specialist', 'graph_nodes_visited': [], 'conclusion': '; '.join(flags) or 'No demographic risk flags.', 'confidence_delta': round(confidence - .86, 2)},
        {'agent_name': 'Safety Adversary', 'graph_nodes_visited': [n for p in paths for n in p.split(' -> ')], 'conclusion': '; '.join(paths) if paths else 'No short path to critical endpoints.', 'confidence_delta': -.08 if paths else 0.0},
        {'agent_name': 'Synthesizer', 'graph_nodes_visited': [], 'conclusion': f'Safety-first ESI-style recommendation: Level {base}.', 'confidence_delta': 0.0},
    ]
    return {'patient_id': patient['patient_id'], 'triage_level': base, 'confidence': round(max(.3, min(.99, confidence)), 2), 'escalated_for_uncertainty': escalated, 'degraded_mode': degraded_mode, 'reasoning_path': reasoning, 'trigger_reason': trigger_reason, 'symptoms': symptoms, 'demographic_flags': flags, 'updated_at': datetime.now(timezone.utc).isoformat()}
