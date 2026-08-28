from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from app.core.redact import redact_patient


def enabled() -> bool:
    return os.getenv('TRIAGE_USE_LLM', 'false').lower() in {'1', 'true', 'yes', 'on'} and os.getenv('LOCAL_ONLY_MODE', 'false').lower() not in {'1', 'true', 'yes', 'on'}


def groq_configured() -> bool:
    return enabled() and bool(os.getenv('GROQ_API_KEY'))


def gemini_configured() -> bool:
    return enabled() and bool(os.getenv('GOOGLE_API_KEY'))


async def extract(patient: dict, labels: list[str]) -> list[str]:
    """Use Groq only for rapid, closed-vocabulary extraction."""
    if not groq_configured():
        raise RuntimeError('Groq extraction is not configured')
    safe = redact_patient(patient)
    from groq import AsyncGroq
    client = AsyncGroq(api_key=os.environ['GROQ_API_KEY'])
    response = await client.chat.completions.create(model=os.getenv('GROQ_MODEL', 'openai/gpt-oss-20b'), messages=[{'role': 'system', 'content': f'Return JSON only: {{"symptoms": [labels]}}. Use only {labels}. Preserve negations; do not diagnose.'}, {'role': 'user', 'content': json.dumps(safe)}], temperature=0, response_format={'type': 'json_object'}, timeout=float(os.getenv('TRIAGE_LLM_TIMEOUT_SECONDS', '10')))
    value = json.loads(response.choices[0].message.content or '{}')
    symptoms = value.get('symptoms', [])
    return [item for item in symptoms if isinstance(item, str) and item in labels]


async def synthesize(state: dict[str, Any], local_safety_level: int) -> tuple[int, float, bool, str]:
    """Gemini may recommend a more urgent level; deterministic policy remains the floor."""
    if not gemini_configured():
        raise RuntimeError('Gemini reasoning is not configured')
    safe_patient = redact_patient(state['patient_input'])
    prompt = {
        'instruction': 'Return JSON only with triage_level (1-5), confidence (0-1), escalated (boolean), reasoning_summary (string). Level 1 is most urgent. This is a decision-support recommendation, not a diagnosis. Do not reduce urgency below local_safety_level.',
        'local_safety_level': local_safety_level,
        'patient': safe_patient,
        'extracted_symptoms': state.get('extracted_symptoms', []),
        'demographic_flags': state.get('demographic_flags', []),
        'graph_evidence': state.get('worst_case_path', []),
        'data_quality': state.get('data_quality', {}),
        'base_confidence': state.get('base_confidence', .35),
    }
    from google import genai
    client = genai.Client(api_key=os.environ['GOOGLE_API_KEY'])
    response = await asyncio.wait_for(client.aio.models.generate_content(model=os.getenv('GEMINI_MODEL', 'gemini-3-flash-preview'), contents=json.dumps(prompt)), timeout=float(os.getenv('TRIAGE_LLM_TIMEOUT_SECONDS', '10')))
    value = json.loads(response.text or '{}')
    level, confidence = int(value['triage_level']), float(value['confidence'])
    if level not in range(1, 6) or not 0 <= confidence <= 1:
        raise ValueError('Provider response outside supported range')
    return level, confidence, bool(value.get('escalated', confidence < .7)), str(value.get('reasoning_summary', '')).strip()
