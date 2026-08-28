from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from app.core.redact import redact_patient


def enabled() -> bool:
    return os.getenv('TRIAGE_USE_LLM', 'false').lower() in {'1', 'true', 'yes', 'on'} and os.getenv('LOCAL_ONLY_MODE', 'false').lower() not in {'1', 'true', 'yes', 'on'}


def provider() -> str:
    return os.getenv('TRIAGE_LLM_PROVIDER', 'groq').lower()


async def extract(patient: dict, labels: list[str]) -> list[str]:
    safe = redact_patient(patient)
    if provider() == 'google':
        from google import genai
        client = genai.Client(api_key=os.environ['GOOGLE_API_KEY'])
        response = await asyncio.wait_for(client.aio.models.generate_content(model=os.getenv('GEMINI_MODEL', 'gemini-3-flash-preview'), contents=json.dumps({'instruction': f'Return JSON only: {{"symptoms": [labels]}}. Use only {labels}.', 'patient': safe})), timeout=float(os.getenv('TRIAGE_LLM_TIMEOUT_SECONDS', '10')))
        value = json.loads(response.text or '{}')
    else:
        from groq import AsyncGroq
        client = AsyncGroq(api_key=os.environ['GROQ_API_KEY'])
        response = await client.chat.completions.create(model=os.getenv('GROQ_MODEL', 'openai/gpt-oss-20b'), messages=[{'role': 'system', 'content': f'Return JSON only: {{"symptoms": [labels]}}. Use only {labels}.'}, {'role': 'user', 'content': json.dumps(safe)}], temperature=0, response_format={'type': 'json_object'}, timeout=float(os.getenv('TRIAGE_LLM_TIMEOUT_SECONDS', '10')))
        value = json.loads(response.choices[0].message.content or '{}')
    symptoms = value.get('symptoms', [])
    return [item for item in symptoms if isinstance(item, str) and item in labels]


async def synthesize(state: dict[str, Any]) -> tuple[int, float, bool]:
    prompt = {'instruction': 'Return JSON only with triage_level (1-5), confidence (0-1), escalated (boolean). Never reduce urgency below the worst-case safety level.', **{key: state.get(key) for key in ('demographic_flags', 'demographic_level', 'worst_case_path', 'adversary_level', 'base_confidence')}}
    if provider() == 'google':
        from google import genai
        client = genai.Client(api_key=os.environ['GOOGLE_API_KEY'])
        response = await asyncio.wait_for(client.aio.models.generate_content(model=os.getenv('GEMINI_MODEL', 'gemini-3-flash-preview'), contents=json.dumps(prompt)), timeout=float(os.getenv('TRIAGE_LLM_TIMEOUT_SECONDS', '10')))
        value = json.loads(response.text or '{}')
    else:
        from groq import AsyncGroq
        client = AsyncGroq(api_key=os.environ['GROQ_API_KEY'])
        response = await client.chat.completions.create(model=os.getenv('GROQ_MODEL', 'openai/gpt-oss-20b'), messages=[{'role': 'system', 'content': prompt['instruction']}, {'role': 'user', 'content': json.dumps(prompt)}], temperature=0, response_format={'type': 'json_object'}, timeout=float(os.getenv('TRIAGE_LLM_TIMEOUT_SECONDS', '10')))
        value = json.loads(response.choices[0].message.content or '{}')
    level, confidence = int(value['triage_level']), float(value['confidence'])
    if level not in range(1, 6) or not 0 <= confidence <= 1:
        raise ValueError('Provider response outside supported range')
    return level, confidence, bool(value.get('escalated', confidence < .7))