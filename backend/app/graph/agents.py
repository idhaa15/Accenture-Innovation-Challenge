from __future__ import annotations

import asyncio
import copy
import json
import os
import time
from collections import deque
from datetime import datetime, timezone
from operator import add
from typing import Annotated, Any, TypedDict

import networkx as nx
import structlog
from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

from app.db.database import age_band
from app.graph import llm_provider
from app.graph.symptom_graph import CRITICAL_NODES

load_dotenv()
logger = structlog.get_logger(__name__)

KEYWORDS = {
    'chest_pain': ['chest', 'epigastric'], 'jaw_pain': ['jaw'], 'nausea': ['nausea'], 'fever': ['fever'],
    'lethargy': ['letharg'], 'poor_feeding': ['poor feeding'], 'confusion': ['confusion', 'not himself'],
    'trauma': ['mvc', 'trauma', 'accident'], 'deformity': ['deform'], 'ankle_pain': ['ankle'],
    'shortness_of_breath': ['shortness', 'breathless'], 'cough': ['cough'], 'wheeze': ['wheeze'],
    'abdominal_pain': ['abdominal', 'stomach'], 'headache': ['headache'], 'weakness': ['weakness'],
    'speech_change': ['speech', 'slurred'], 'vomiting': ['vomit'], 'dizziness': ['dizz'], 'fainting': ['faint'],
    'bleeding': ['bleed'], 'burn': ['burn'], 'rash': ['rash'], 'back_pain': ['back pain'],
}
GRAPH_LABELS = frozenset(KEYWORDS) | {'low_spo2', 'tachycardia', 'low_bp'}
AMBIGUOUS_TERMS = ('vague', 'possible', 'maybe', 'unknown', 'not sure', 'unclear', 'atypical')
PROVIDER_CONCURRENCY = max(1, int(os.getenv('TRIAGE_MAX_CONCURRENT_CALLS', '4')))
LLM_CALLS_PER_MINUTE = max(1, int(os.getenv('TRIAGE_LLM_CALLS_PER_MINUTE', '12')))
PROVIDER_SEMAPHORE = asyncio.Semaphore(PROVIDER_CONCURRENCY)
TRIAGE_CACHE: dict[str, dict[str, Any]] = {}
PROVIDER_BLOCKED_UNTIL = {'groq': 0.0, 'google': 0.0}
PROVIDER_CALL_COUNTS = {'groq': 0, 'google': 0}
PROVIDER_CALL_TIMES = {'groq': deque(), 'google': deque()}
ROUTING = {'myocardial_infarction': 'Cardiology', 'stroke': 'Neurology', 'sepsis': 'Internal Medicine / ICU', 'respiratory_failure': 'Pulmonology', 'internal_bleeding': 'General Surgery'}
DISCLAIMER = 'Decision support only. Not a validated diagnostic device. Graph-based reasoning is a heuristic, not a licensed clinical protocol.'


def _provider_available(name: str) -> bool:
    calls = PROVIDER_CALL_TIMES[name]
    cutoff = time.monotonic() - 60
    while calls and calls[0] < cutoff:
        calls.popleft()
    return time.monotonic() >= PROVIDER_BLOCKED_UNTIL.get(name, 0.0) and len(calls) < LLM_CALLS_PER_MINUTE


def _record_provider_call(name: str) -> None:
    PROVIDER_CALL_TIMES[name].append(time.monotonic())
    PROVIDER_CALL_COUNTS[name] += 1


def _block_provider(name: str, seconds: float = 30.0) -> None:
    PROVIDER_BLOCKED_UNTIL[name] = time.monotonic() + seconds


def _error_summary(exc: Exception) -> str:
    code = getattr(exc, 'status_code', None) or getattr(exc, 'code', None) or 'unknown'
    detail = ' '.join(str(exc).split())[:180]
    return f'{type(exc).__name__}:{code}{":" + detail if detail else ""}'


class TriageState(TypedDict, total=False):
    patient_input: dict[str, Any]
    graph: nx.Graph
    extracted_symptoms: list[str]
    demographic_flags: list[str]
    demographic_level: int
    base_confidence: float
    worst_case_path: list[str]
    adversary_level: int
    triage_level: int
    confidence: float
    degraded_mode: bool
    reasoning_log: Annotated[list[dict[str, Any]], add]
    trigger_reason: str
    data_quality: dict[str, Any]
    explanation: dict[str, Any]
    recommended_department: str
    routing_confidence: str
    disclaimer: str
    llm_response: dict[str, Any]


def extract_symptoms(patient: dict[str, Any]) -> list[str]:
    text = patient['chief_complaint'].lower()
    result = [label for label, words in KEYWORDS.items() if any(word in text for word in words)]
    vitals = patient['vitals']
    if vitals.get('spo2') is not None and vitals['spo2'] < 94: result.append('low_spo2')
    if vitals.get('heart_rate') is not None and vitals['heart_rate'] > 100: result.append('tachycardia')
    if vitals.get('systolic_bp') is not None and vitals['systolic_bp'] < 90: result.append('low_bp')
    return list(dict.fromkeys(result))


def _llm_enabled() -> bool:
    return llm_provider.enabled()


def _parse_json(content: str) -> dict[str, Any]:
    value = json.loads(content.strip())
    if not isinstance(value, dict):
        raise ValueError('Model response was not a JSON object')
    return value


async def _extract_node(state: TriageState) -> dict[str, Any]:
    patient = state['patient_input']
    if _llm_enabled():
        return {'extracted_symptoms': [], 'degraded_mode': state.get('degraded_mode', False), 'reasoning_log': [{'agent_name': 'Fallback Extraction', 'graph_nodes_visited': [], 'conclusion': 'Held in reserve; primary LLM extracts symptoms and reasoning together.', 'confidence_delta': 0.0}]}
    symptoms = extract_symptoms(patient)
    return {
        'extracted_symptoms': symptoms,
        'degraded_mode': state.get('degraded_mode', False),
        'reasoning_log': [{'agent_name': 'Fallback Extraction', 'graph_nodes_visited': symptoms, 'conclusion': f'Fallback activated {len(symptoms)} symptom node(s).', 'confidence_delta': 0.0}],
    }


async def _demographic_node(state: TriageState) -> dict[str, Any]:
    patient = state['patient_input']
    age, vitals = patient['age_years'], patient['vitals']
    band, flags, urgency, confidence = age_band(age), [], 5, .86
    if not patient['has_prior_history']:
        flags.append('No prior history available: uncertainty elevated'); confidence -= .13
    expected = ('heart_rate', 'resp_rate', 'spo2', 'temp_c', 'systolic_bp')
    missing = [key for key in expected if vitals.get(key) is None]
    questions = {'spo2': 'Measure oxygen saturation', 'systolic_bp': 'Measure blood pressure', 'heart_rate': 'Measure heart rate', 'resp_rate': 'Measure respiratory rate', 'temp_c': 'Measure temperature'}
    if missing:
        flags.append(f'Missing intake vital(s): {", ".join(missing)}'); confidence -= .18
    high_risk_missing = [key for key in ('spo2', 'systolic_bp') if key in missing]
    if high_risk_missing:
        flags.append(f'Critical measurement needed: {", ".join(high_risk_missing)}'); confidence -= .12
    hr, rr, temp, spo2, bp = (vitals.get(key) for key in ('heart_rate', 'resp_rate', 'temp_c', 'spo2', 'systolic_bp'))
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
    quality = {
        'status': 'critical_fields_missing' if high_risk_missing else 'incomplete' if missing else 'complete',
        'missing_fields': missing,
        'invalid_fields': [],
        'stale_fields': [],
        'next_best_questions': [questions[key] for key in missing],
        'measurement_review_required': bool(high_risk_missing),
        'review_reason': 'Critical vital signs must be measured before final clinical disposition.' if high_risk_missing else '',
    }
    return {'demographic_flags': flags, 'demographic_level': urgency, 'base_confidence': max(.3, confidence), 'data_quality': quality, 'reasoning_log': [{'agent_name': 'Demographic Specialist', 'graph_nodes_visited': [], 'conclusion': '; '.join(flags) or 'No demographic risk flags.', 'confidence_delta': round(confidence - .86, 2)}]}


async def _adversary_node(state: TriageState) -> dict[str, Any]:
    paths: list[str] = []
    graph = state['graph']
    for symptom in state.get('extracted_symptoms', []):
        if symptom not in graph: continue
        for critical in CRITICAL_NODES:
            try:
                path = nx.shortest_path(graph, symptom, critical, weight=lambda _a, _b, edge: 1 / max(.05, edge.get('weight', .5)))
                if len(path) <= 3: paths.append(' -> '.join(path))
            except nx.NetworkXNoPath:
                pass
    paths = paths[:4]
    symptoms = set(state.get('extracted_symptoms', []))
    vitals = state.get('patient_input', {}).get('vitals', {})
    red_vital = (vitals.get('spo2') is not None and vitals['spo2'] < 92) or (vitals.get('systolic_bp') is not None and vitals['systolic_bp'] < 90)
    corroborated = red_vital or len(symptoms) >= 2
    # A graph route is an alert, not a diagnosis. It must be corroborated by
    # multiple observed signals before it can force the high-risk bucket.
    level = 2 if paths and corroborated else 3 if paths else 5
    visited = [node for path in paths for node in path.split(' -> ')]
    conclusion = '; '.join(paths) if paths else 'No short path to critical endpoints.'
    if paths and not corroborated:
        conclusion += ' Graph alert retained as supporting evidence; it does not independently set urgency.'
    return {'worst_case_path': visited, 'adversary_level': level, 'reasoning_log': [{'agent_name': 'Safety Adversary', 'graph_nodes_visited': visited, 'conclusion': conclusion, 'confidence_delta': -.08 if paths else 0.0}]}


def _fallback_synthesis(state: TriageState) -> tuple[int, float, bool]:
    patient = state['patient_input']
    pain = patient.get('self_reported_pain') or 0
    # Used only when the LLM is unavailable. Missing observations never alter
    # this clinical level; they create a separate measurement-review state.
    level = min(_hard_safety_floor(patient), state.get('adversary_level', 5), 2 if pain >= 8 else 5)
    confidence = state.get('base_confidence', .35)
    if state.get('worst_case_path'): confidence = max(.3, confidence - .08)
    if not state.get('extracted_symptoms'): confidence -= .12
    if state.get('degraded_mode'): confidence = min(confidence, .62)
    escalated = confidence < .70 or bool(state.get('worst_case_path'))
    return level, max(.3, min(.99, confidence)), escalated


def _hard_safety_floor(patient: dict[str, Any]) -> int:
    """Only observed, immediately dangerous vitals constrain LLM urgency."""
    vitals = patient['vitals']
    if (vitals.get('spo2') is not None and vitals['spo2'] < 90) or (vitals.get('systolic_bp') is not None and vitals['systolic_bp'] < 90):
        return 1
    return 5


async def _synthesizer_node(state: TriageState) -> dict[str, Any]:
    level, confidence, escalated = _fallback_synthesis(state)
    degraded = state.get('degraded_mode', False)
    use_model = _llm_enabled()
    gemini_summary = ''
    local_safety_level = _hard_safety_floor(state['patient_input'])
    if use_model and llm_provider.gemini_configured() and _provider_available('google'):
        try:
            _record_provider_call('google')
            async with PROVIDER_SEMAPHORE:
                llm_response = await llm_provider.synthesize(state, local_safety_level, sorted(GRAPH_LABELS))
            suggested_level, suggested_confidence, suggested_escalated = llm_response['triage_level'], llm_response['confidence'], llm_response['escalated']
            gemini_summary = llm_response['reasoning_summary']
            # The LLM leads the recommendation. Observed emergency vitals are
            # the only deterministic floor and can only increase urgency.
            level = min(suggested_level, local_safety_level)
            confidence = min(confidence, suggested_confidence)
            escalated = escalated or suggested_escalated
            degraded = False
        except Exception as exc:
            degraded = True
            _block_provider('google')
            logger.warning('gemini_synthesis_failed', error=_error_summary(exc))
            level, confidence, escalated = _fallback_synthesis({**state, 'degraded_mode': True})
    elif use_model:
        degraded = True
        level, confidence, escalated = _fallback_synthesis({**state, 'degraded_mode': True})
    quality = state.get('data_quality', {})
    measurement_review = bool(quality.get('measurement_review_required'))
    flags = list(state.get('demographic_flags', []))
    if state.get('worst_case_path'): flags.append('Safety adversary found a short path to a critical condition')
    if degraded: flags.append('External AI unavailable: deterministic fail-safe active')
    critical = next((node for node in CRITICAL_NODES if node in state.get('worst_case_path', [])), None)
    evidence = flags or ['No demographic risk flags and no short path to a critical endpoint']
    if critical: evidence.append(f'Graph path reached {critical}')
    if gemini_summary: evidence.append(f'Gemini reasoning: {gemini_summary}')
    if measurement_review:
        evidence.append(quality['review_reason'])
    source = 'LLM-led assessment' if gemini_summary else 'Deterministic fail-safe assessment'
    explanation = {'summary': f'Prototype urgency Level {level}: {"; ".join(evidence)}.', 'evidence': evidence, 'why_this_level': f'{source}; missing observations are treated as unknown and trigger measurement review, not a clinical-level change.'}
    department = ROUTING.get(critical, 'General ED')
    routing_confidence = 'high' if level == 1 and critical else 'heuristic'
    conclusion = f'{source}: prototype urgency Level {level}.'
    if gemini_summary: conclusion += ' Gemini recommendation was constrained by the deterministic safety floor.'
    audit_json = locals().get('llm_response', {'source': 'deterministic_fallback', 'reason': 'LLM disabled, unavailable, or failed'})
    return {'triage_level': level, 'confidence': round(confidence, 2), 'degraded_mode': degraded, 'demographic_flags': flags, 'explanation': explanation, 'recommended_department': department, 'routing_confidence': routing_confidence, 'data_quality': state.get('data_quality', {'status': 'complete', 'missing_fields': [], 'invalid_fields': [], 'stale_fields': [], 'next_best_questions': [], 'measurement_review_required': False, 'review_reason': ''}), 'disclaimer': DISCLAIMER, 'llm_response': audit_json, 'extracted_symptoms': audit_json.get('symptoms', state.get('extracted_symptoms', [])), 'reasoning_log': [{'agent_name': 'LLM Reasoning' if gemini_summary else 'Deterministic Fallback', 'graph_nodes_visited': audit_json.get('symptoms', []), 'conclusion': conclusion, 'confidence_delta': 0.0}]}


def _build_graph():
    workflow = StateGraph(TriageState)
    workflow.add_node('node_extraction', _extract_node)
    workflow.add_node('demographic_specialist', _demographic_node)
    workflow.add_node('safety_adversary', _adversary_node)
    workflow.add_node('synthesizer', _synthesizer_node)
    workflow.add_edge(START, 'node_extraction')
    workflow.add_edge('node_extraction', 'demographic_specialist')
    workflow.add_edge('node_extraction', 'safety_adversary')
    workflow.add_edge(['demographic_specialist', 'safety_adversary'], 'synthesizer')
    workflow.add_edge('synthesizer', END)
    return workflow.compile()


TRIAGE_GRAPH = _build_graph()


async def demographic_specialist(patient: dict[str, Any]) -> tuple[list[str], int, float]:
    state = await _demographic_node({'patient_input': patient})
    return state['demographic_flags'], state['demographic_level'], state['base_confidence']


async def safety_adversary(symptoms: list[str], graph: nx.Graph) -> tuple[list[str], int]:
    state = await _adversary_node({'extracted_symptoms': symptoms, 'graph': graph})
    return state['worst_case_path'], state['adversary_level']


async def triage(patient: dict[str, Any], graph: nx.Graph, degraded_mode: bool = False, trigger_reason: str = 'intake') -> dict[str, Any]:
    cache_key = json.dumps({'patient': patient, 'degraded_mode': degraded_mode, 'llm': _llm_enabled()}, sort_keys=True, default=str)
    cached = TRIAGE_CACHE.get(cache_key)
    if cached and trigger_reason == 'intake':
        return copy.deepcopy(cached)
    state = await TRIAGE_GRAPH.ainvoke({'patient_input': patient, 'graph': graph, 'degraded_mode': degraded_mode, 'trigger_reason': trigger_reason})
    result = {'patient_id': patient['patient_id'], 'triage_level': state['triage_level'], 'confidence': state['confidence'], 'escalated_for_uncertainty': state['triage_level'] <= 2 or bool(state.get('worst_case_path')) or state.get('confidence', 1) < .70 or bool(state.get('data_quality', {}).get('measurement_review_required')), 'degraded_mode': state.get('degraded_mode', False), 'reasoning_path': state['reasoning_log'], 'trigger_reason': trigger_reason, 'symptoms': state.get('extracted_symptoms', []), 'demographic_flags': state.get('demographic_flags', []), 'explanation': state.get('explanation', {}), 'recommended_department': state.get('recommended_department', 'General ED'), 'routing_confidence': state.get('routing_confidence', 'heuristic'), 'data_quality': state.get('data_quality', {'status': 'complete', 'missing_fields': [], 'invalid_fields': [], 'stale_fields': [], 'next_best_questions': [], 'measurement_review_required': False, 'review_reason': ''}), 'disclaimer': state.get('disclaimer', DISCLAIMER), 'llm_response': state.get('llm_response', {}), 'updated_at': datetime.now(timezone.utc).isoformat()}
    if trigger_reason == 'intake' and not result['degraded_mode']:
        TRIAGE_CACHE[cache_key] = copy.deepcopy(result)
    return result
