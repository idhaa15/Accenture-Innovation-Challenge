# PatientTriage.ai

Fictional, safety-first ED triage prototype. **Decision support only; not diagnostic or deployable clinical software.**

## Current workflow

```text
Intake / new vitals → FastAPI validation → LangGraph → Gemini reasoning
→ observed-vital safety floor → SQLite audit → live queue
```

- **Primary path:** Gemini receives a redacted structured case and returns JSON: `symptoms`, `triage_level`, `confidence`, `escalated`, `reasoning_summary`.
- **Fallback:** deterministic keyword/graph/rule path runs only when AI is off, unavailable, invalid, or rate-limited.
- **Safety shell:** validates input and prevents observed SpO₂ <90 or systolic BP <90 from being downgraded.
- **Missing data:** unknown—not normal or abnormal. Missing SpO₂/BP requires measurement review and moves earlier only within its existing urgency level.
- **Human control:** override, escalation, reassessment, missing-vital entry, and accept-to-treatment are audited.

## Queue order

1. Prototype urgency level (Level 1 always leads)
2. Confirmed deterioration
3. Critical measurement review
4. Reassessment due
5. Capped wait fairness

Wait time and missing data never cross urgency levels.

## Audit visibility

SQLite: `backend/patient_triage.db`. Every assessment stores result, reasoning, data quality, clinician actions, and parsed model JSON in `triage_logs.llm_response_json`. The UI shows this under **Stored model JSON**. Fallbacks store explicit fallback metadata.

## Demo

- New patient creates a fictional encounter.
- Simulate 3× surge adds 10 catalogue patients; it then becomes Reset.
- Fail-safe forces deterministic mode.
- Intake modal scrolls within the viewport.

Catalogue: `backend/app/mock_data/simulated_patients.json`; SQLite holds active encounters/history.

## Run

```bash
# terminal 1
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8003

# terminal 2
cd frontend && npm install && npm run dev
```

Open `http://localhost:3000`.


## Stack and limits

Next.js/React, FastAPI/Pydantic, SQLite WAL, LangGraph `StateGraph`, Gemini, NetworkX. LangChain Core is installed but not directly used by app code.

Real deployment requires clinical validation/governance, privacy approval, RBAC/encryption, immutable audit controls, production observability/database, and EHR integration.
