from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

from app.core.redact import redact_patient


def enabled() -> bool:
    return os.getenv('TRIAGE_USE_LLM', 'false').lower() in {'1', 'true', 'yes', 'on'} and os.getenv('LOCAL_ONLY_MODE', 'false').lower() not in {'1', 'true', 'yes', 'on'}


def groq_configured() -> bool:
    return enabled() and bool(os.getenv('GROQ_API_KEY'))


def gemini_configured() -> bool:
    return enabled() and bool(os.getenv('GOOGLE_API_KEY'))


def _parse_gemini_json(text: str | None) -> dict[str, Any]:
    """Accept JSON mode output and safely tolerate a legacy Markdown fence."""
    content = (text or '').strip()
    content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content, flags=re.IGNORECASE).strip()
    start = content.find('{')
    if start < 0:
        raise ValueError('Gemini returned no JSON object')
    value, _ = json.JSONDecoder().raw_decode(content[start:])
    if not isinstance(value, dict):
        raise ValueError('Gemini response was not a JSON object')
    return value


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


async def synthesize(state: dict[str, Any], local_safety_level: int, allowed_symptoms: list[str]) -> dict[str, Any]:
    """Primary LLM path: extract closed-vocabulary symptoms and reason in one response."""
    if not gemini_configured():
        raise RuntimeError('Gemini reasoning is not configured')
    safe_patient = redact_patient(state['patient_input'])
    prompt = {
        'instruction': f'Return JSON only with triage_level (1-5), confidence (0-1), escalated (boolean), symptoms (array using only {allowed_symptoms}), and reasoning_summary (a concise, human-readable explanation citing observed facts, uncertainty, and next action). Level 1 is most urgent. This is decision support, not a diagnosis. Make the urgency recommendation from observed evidence. Missing fields are unknown: never treat them as normal or abnormal, never change triage_level because a field is missing alone, and state that critical missing observations require measurement review. Do not reduce urgency below local_safety_level.',
        'local_safety_level': local_safety_level,
        'patient': safe_patient,
        'extracted_symptoms': state.get('extracted_symptoms', []),
        'demographic_flags': state.get('demographic_flags', []),
        'graph_evidence': state.get('worst_case_path', []),
        'data_quality': state.get('data_quality', {}),
        'base_confidence': state.get('base_confidence', .35),
    }
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ['GOOGLE_API_KEY'])
    # Gemini can take longer than ten seconds for structured clinical reasoning.
    # A short deadline caused healthy calls to be marked unavailable and opened
    # the fail-safe circuit breaker unnecessarily.
    request = {
        'model': os.getenv('GEMINI_MODEL', 'gemini-3-flash-preview'),
        'contents': json.dumps(prompt),
        'config': types.GenerateContentConfig(response_mime_type='application/json', temperature=0),
    }
    # JSON mode removes the usual prose/fenced response. A single retry covers
    # rare empty or truncated responses without abandoning the LLM path.
    for attempt in range(2):
        response = await asyncio.wait_for(
            client.aio.models.generate_content(**request),
            timeout=float(os.getenv('TRIAGE_LLM_TIMEOUT_SECONDS', '30')),
        )
        try:
            value = _parse_gemini_json(response.text)
            break
        except (json.JSONDecodeError, ValueError):
            if attempt:
                raise
    level, confidence = int(value['triage_level']), float(value['confidence'])
    if level not in range(1, 6) or not 0 <= confidence <= 1:
        raise ValueError('Provider response outside supported range')
    symptoms = [item for item in value.get('symptoms', []) if isinstance(item, str) and item in allowed_symptoms]
    return {**value, 'triage_level': level, 'confidence': confidence, 'escalated': bool(value.get('escalated', confidence < .7)), 'symptoms': list(dict.fromkeys(symptoms)), 'reasoning_summary': str(value.get('reasoning_summary', '')).strip()}
