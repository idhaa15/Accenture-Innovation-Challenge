from __future__ import annotations

import re


def redact_text(value: str) -> str:
    value = re.sub(r'\b(?:MRN|medical record number)\s*[:#-]?\s*[A-Z0-9-]+\b', '[MRN]', value, flags=re.I)
    value = re.sub(r'\b\d{3}[-.) ]\d{3}[-. ]\d{4}\b', '[PHONE]', value)
    value = re.sub(r'\b\d{1,5}\s+[A-Za-z0-9 .-]+\s+(?:Street|St|Road|Rd|Avenue|Ave|Boulevard|Blvd)\b', '[ADDRESS]', value, flags=re.I)
    return value


def redact_patient(patient: dict) -> dict:
    safe = {key: value for key, value in patient.items() if key not in {'name', 'patient_name', 'date_of_birth', 'dob', 'mrn'}}
    safe['patient_id'] = '[PATIENT]'
    safe['chief_complaint'] = redact_text(str(safe.get('chief_complaint', '')))
    safe.pop('age_years', None)
    return safe