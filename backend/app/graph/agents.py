from __future__ import annotations

import asyncio
import copy
import json
import os
import time
from datetime import datetime, timezone
from operator import add
from typing import Annotated, Any, TypedDict

import networkx as nx
import structlog
from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

from app.db.database import age_band
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
LLM_PATIENT_BUDGET = max(0, int(os.getenv('TRIAGE_LLM_PATIENT_BUDGET', '5')))
PROVIDER_SEMAPHORE = asyncio.Semaphore(PROVIDER_CONCURRENCY)
TRIAGE_CACHE: dict[str, dict[str, Any]] = {}
PROVIDER_BLOCKED_UNTIL = {'groq': 0.0, 'google': 0.0}
PROVIDER_CALL_COUNTS = {'groq': 0, 'google': 0}


def _provider_available(name: str) -> bool:
    return time.monotonic() >= PROVIDER_BLOCKED_UNTIL[name] and PROVIDER_CALL_COUNTS[name] < LLM_PATIENT_BUDGET


def _block_provider(name: str, seconds: float = 30.0) -> None:
    PROVIDER_BLOCKED_UNTIL[name] = time.monotonic() + seconds


def _error_summary(exc: Exception) -> str:
    return f'{type(exc).__name__}:{getattr(exc, "status_code", None) or getattr(exc, "code", None) or "unknown"}'


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


def extract_symptoms(patient: dict[str, Any]) -> list[str]:
    text = patient['chief_complaint'].lower()
    result = [label for label, words in KEYWORDS.items() if any(word in text for word in words)]
    vitals = patient['vitals']
    if vitals.get('spo2') is not None and vitals['spo2'] < 94: result.append('low_spo2')
    if vitals.get('heart_rate') is not None and vitals['heart_rate'] > 100: result.append('tachycardia')
    if vitals.get('systolic_bp') is not None and vitals['systolic_bp'] < 90: result.append('low_bp')
    return list(dict.fromkeys(result))


def _llm_enabled() -> bool:
    return os.getenv('TRIAGE_USE_LLM', 'false').lower() in {'1', 'true', 'yes', 'on'}


def _parse_json(content: str) -> dict[str, Any]:
    value = json.loads(content.strip())
    if not isinstance(value, dict):
        raise ValueError('Model response was not a JSON object')
    return value


async def _groq_extract(patient: dict[str, Any]) -> list[str]:
    from groq import AsyncGroq

    client = AsyncGroq(api_key=os.environ['GROQ_API_KEY'])
    PROVIDER_CALL_COUNTS['groq'] += 1
    async with PROVIDER_SEMAPHORE:
        response = await client.chat.completions.create(
            model=os.getenv('GROQ_MODEL', 'openai/gpt-oss-20b'),
            messages=[
                {'role': 'system', 'content': f'Return JSON only: {{"symptoms": [labels]}}. Use only these labels: {sorted(GRAPH_LABELS)}.'},
                {'role': 'user', 'content': json.dumps({'chief_complaint': patient['chief_complaint'], 'vitals': patient['vitals']})},
            ],
            temperature=0,
            response_format={'type': 'json_object'},
            timeout=float(os.getenv('TRIAGE_LLM_TIMEOUT_SECONDS', '10')),
        )
    parsed = _parse_json(response.choices[0].message.content or '{}')
    symptoms = parsed.get('symptoms')
    if not isinstance(symptoms, list):
        raise ValueError('Model response did not contain a symptom list')
    return [item for item in symptoms if isinstance(item, str) and item in GRAPH_LABELS]


async def _gemini_synthesize(state: TriageState) -> tuple[int, float, bool]:
    from google import genai

    client = genai.Client(api_key=os.environ['GOOGLE_API_KEY'])
    PROVIDER_CALL_COUNTS['google'] += 1
    prompt = {
        'instruction': 'Return JSON only with triage_level (1-5), confidence (0-1), escalated (boolean). Level 1 is most urgent. Never reduce urgency below the worst-case safety level.',
        'demographic_flags': state.get('demographic_flags', []),
        'demographic_level': state.get('demographic_level', 5),
        'worst_case_path': state.get('worst_case_path', []),
        'adversary_level': state.get('adversary_level', 5),
        'base_confidence': state.get('base_confidence', .35),
    }
    async with PROVIDER_SEMAPHORE:
        response = await asyncio.wait_for(client.aio.models.generate_content(model=os.getenv('GEMINI_MODEL', 'gemini-3-flash-preview'), contents=json.dumps(prompt)), timeout=float(os.getenv('TRIAGE_LLM_TIMEOUT_SECONDS', '10')))
    parsed = _parse_json(response.text or '{}')
    level = int(parsed['triage_level'])
    confidence = float(parsed['confidence'])
    if level not in range(1, 6) or not 0 <= confidence <= 1:
        raise ValueError('Model synthesis was outside the supported range')
    return level, confidence, bool(parsed.get('escalated', confidence < .70))


async def _extract_node(state: TriageState) -> dict[str, Any]:
    patient = state['patient_input']
    symptoms = extract_symptoms(patient)
    degraded = state.get('degraded_mode', False)
    complaint = patient['chief_complaint'].lower()
    use_model = _llm_enabled() and (not symptoms or len(symptoms) >= 3 or any(term in complaint for term in AMBIGUOUS_TERMS))
    if use_model and not os.getenv('GROQ_API_KEY'):
        degraded = True
    elif use_model and os.getenv('GROQ_API_KEY') and _provider_available('groq'):
        try:
            symptoms = list(dict.fromkeys(await _groq_extract(patient))) or symptoms
        except Exception as exc:
            degraded = True
            _block_provider('groq')
            logger.warning('groq_extraction_failed', error=_error_summary(exc))
    elif use_model:
        degraded = True
    return {
        'extracted_symptoms': symptoms,
        'degraded_mode': degraded,
        'reasoning_log': [{'agent_name': 'Node Extraction', 'graph_nodes_visited': symptoms, 'conclusion': f'Activated {len(symptoms)} symptom node(s).', 'confidence_delta': 0.0}],
    }


async def _demographic_node(state: TriageState) -> dict[str, Any]:
    patient = state['patient_input']
    age, vitals = patient['age_years'], patient['vitals']
    band, flags, urgency, confidence = age_band(age), [], 5, .86
    if not patient['has_prior_history']:
        flags.append('No prior history available: uncertainty elevated'); confidence -= .13
    missing = [key for key, value in vitals.items() if value is None]
    if missing:
        flags.append(f'Missing intake vital(s): {", ".join(missing)}'); confidence -= .18; urgency = min(urgency, 3)
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
    return {'demographic_flags': flags, 'demographic_level': urgency, 'base_confidence': max(.35, confidence), 'reasoning_log': [{'agent_name': 'Demographic Specialist', 'graph_nodes_visited': [], 'conclusion': '; '.join(flags) or 'No demographic risk flags.', 'confidence_delta': round(confidence - .86, 2)}]}


async def _adversary_node(state: TriageState) -> dict[str, Any]:
    paths: list[str] = []
    graph = state['graph']
    for symptom in state.get('extracted_symptoms', []):
        if symptom not in graph: continue
        for critical in CRITICAL_NODES:
            try:
                path = nx.shortest_path(graph, symptom, critical)
                if len(path) <= 3: paths.append(' -> '.join(path))
            except nx.NetworkXNoPath:
                pass
    paths = paths[:4]
    level = 1 if any('respiratory_failure' in path or 'internal_bleeding' in path for path in paths) else 2 if paths else 5
    visited = [node for path in paths for node in path.split(' -> ')]
    return {'worst_case_path': visited, 'adversary_level': level, 'reasoning_log': [{'agent_name': 'Safety Adversary', 'graph_nodes_visited': visited, 'conclusion': '; '.join(paths) if paths else 'No short path to critical endpoints.', 'confidence_delta': -.08 if paths else 0.0}]}


def _fallback_synthesis(state: TriageState) -> tuple[int, float, bool]:
    patient = state['patient_input']
    pain = patient.get('self_reported_pain') or 0
    level = min(state.get('demographic_level', 5), state.get('adversary_level', 5), 2 if pain >= 8 else 5)
    confidence = state.get('base_confidence', .35)
    if state.get('worst_case_path'): confidence = max(.3, confidence - .08)
    if not state.get('extracted_symptoms'): confidence -= .12
    if state.get('degraded_mode'): confidence = min(confidence, .62)
    escalated = confidence < .70 or bool(state.get('worst_case_path'))
    if confidence < .70: level = max(1, level - 1)
    return level, max(.3, min(.99, confidence)), escalated


async def _synthesizer_node(state: TriageState) -> dict[str, Any]:
    level, confidence, escalated = _fallback_synthesis(state)
    degraded = state.get('degraded_mode', False)
    complaint = state['patient_input']['chief_complaint'].lower()
    use_model = _llm_enabled() and (state.get('confidence', 1) < .70 or len(state.get('worst_case_path', [])) > 4 or any(term in complaint for term in AMBIGUOUS_TERMS) or len(state.get('extracted_symptoms', [])) >= 3)
    if use_model and not os.getenv('GOOGLE_API_KEY'):
        degraded = True
        level, confidence, escalated = _fallback_synthesis({**state, 'degraded_mode': True})
    elif use_model and os.getenv('GOOGLE_API_KEY') and not degraded and _provider_available('google'):
        try:
            level, confidence, escalated = await _gemini_synthesize(state)
            level = min(level, state.get('demographic_level', 5), state.get('adversary_level', 5))
            if confidence < .70: level, escalated = max(1, level - 1), True
        except Exception as exc:
            degraded = True
            _block_provider('google')
            logger.warning('gemini_synthesis_failed', error=_error_summary(exc))
            level, confidence, escalated = _fallback_synthesis({**state, 'degraded_mode': True})
    elif use_model and not degraded:
        degraded = True
        level, confidence, escalated = _fallback_synthesis({**state, 'degraded_mode': True})
    flags = list(state.get('demographic_flags', []))
    if state.get('worst_case_path'): flags.append('Safety adversary found a short path to a critical condition')
    if degraded: flags.append('External AI unavailable: deterministic fail-safe active')
    return {'triage_level': level, 'confidence': round(confidence, 2), 'degraded_mode': degraded, 'demographic_flags': flags, 'reasoning_log': [{'agent_name': 'Synthesizer', 'graph_nodes_visited': [], 'conclusion': f'Safety-first ESI-style recommendation: Level {level}.', 'confidence_delta': 0.0}]}


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
    result = {'patient_id': patient['patient_id'], 'triage_level': state['triage_level'], 'confidence': state['confidence'], 'escalated_for_uncertainty': state['triage_level'] <= 2 or bool(state.get('worst_case_path')) or state.get('confidence', 1) < .70, 'degraded_mode': state.get('degraded_mode', False), 'reasoning_path': state['reasoning_log'], 'trigger_reason': trigger_reason, 'symptoms': state.get('extracted_symptoms', []), 'demographic_flags': state.get('demographic_flags', []), 'updated_at': datetime.now(timezone.utc).isoformat()}
    if trigger_reason == 'intake' and not result['degraded_mode']:
        TRIAGE_CACHE[cache_key] = copy.deepcopy(result)
    return result
