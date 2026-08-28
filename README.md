# PatientTriage.ai

[![Temporary YouTube](https://img.shields.io/badge/YouTube-Karan%20Aujla%20placeholder-FF0000?style=for-the-badge&logo=youtube)](https://www.youtube.com/watch?v=vsWxs1tuwDk&list=RDvsWxs1tuwDk&start_radio=1)


[![Open Local Demo](https://img.shields.io/badge/Open-Local%20Demo-10b981?style=for-the-badge)](http://localhost:3000)
[![API Health](https://img.shields.io/badge/API-FastAPI-0a7ea4?style=for-the-badge)](http://localhost:8000/health)

Safety-first emergency-department triage prototype for the Accenture Innovation Challenge. PatientTriage.ai combines deterministic safety policy, a NetworkX symptom graph, LangGraph orchestration, optional Groq extraction plus Gemini reasoning, clinician actions, and an audit trail.

> Decision support only. Not a validated diagnostic device. Graph-based reasoning is a heuristic, not a licensed clinical protocol.

## Table of Contents

- [What We Built](#what-we-built)
- [How It Works](#how-it-works)
- [Technology](#technology)
- [Project Structure](#project-structure)
- [How to Run Locally](#how-to-run-locally)
- [Demo Flow](#demo-flow)
- [Data and Information Safety](#data-and-information-safety)
- [Optimization](#optimization)
- [Future Scope](#future-scope)
- [Limitations](#limitations)

## What We Built

- Live ED queue with hard acuity buckets: a Level 1 can never be passed by a Level 2-5 patient because of wait time.
- LangGraph workflow with four stages: Node Extraction, Demographic Specialist, Safety Adversary, and Synthesizer.
- Optional two-stage model path: Groq extracts a closed symptom vocabulary; Gemini reasons over a redacted, structured ambiguous case.
- PHI redaction before external calls and `LOCAL_ONLY_MODE` for zero external calls.
- Deterministic fallback when providers time out, rate-limit, return invalid data, or are unavailable.
- NetworkX symptom-to-risk graph that surfaces short paths to critical endpoints.
- Pediatric, adult, and geriatric calibration rules.
- Vitals-triggered re-triage and persisted reassessment schedules; overdue reassessments are visibly flagged without inventing new clinical observations.
- Reversible surge simulation capped at 20 active patients.
- Clinician override and manual escalation audit trail; the clinician-set level becomes the active queue decision immediately.
- SQLite WAL persistence.
- Full fictional patient catalogue separated from the active hospital queue.

## How It Works

```text
Frontend: Next.js + React + Cytoscape.js
        | REST/JSON and queue WebSocket
        v
Backend: FastAPI
        v
LangGraph workflow
  |-- Node Extraction: local rules, optional Groq extraction
  |-- Demographic Specialist: age-aware vital checks
  |-- Safety Adversary: NetworkX shortest paths
  |-- Synthesizer: optional Gemini reasoning, bounded by local safety rules
        |
        +--> SQLite audit store
        +--> NumPy queue decay
        +--> Cytoscape reasoning graph
```

The complete fictional catalogue lives in `backend/app/mock_data/simulated_patients.json`. SQLite tracks which records are currently active encounters. The catalogue can contain 100 or more records while the live queue contains only the selected patients seeking treatment.

## Technology

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, React 18, TypeScript, Cytoscape.js, Lucide React |
| API | FastAPI, Uvicorn, Pydantic v2 |
| Orchestration | LangGraph, LangChain Core |
| Optional models | Groq extraction + Gemini reasoning via `google-genai` |
| Reasoning graph | NetworkX |
| Queue policy | Hard acuity bucket → deterioration → reassessment due → capped linear wait fairness |
| Storage | SQLite with WAL mode |
| Logging | Structlog |

## Project Structure

```text
backend/
  app/
    main.py                    FastAPI routes, lifecycle, queue, WebSocket
    graph/agents.py             LangGraph workflow and model fallbacks
    graph/symptom_graph.py      NetworkX graph and synaptic updates
    core/queue_decay.py         Queue decay and vital-delta checks
    db/database.py              SQLite schema and persistence
    db/models.py                Pydantic request/result models
    mock_data/simulated_patients.json  Fictional master catalogue
  requirements.txt
frontend/
  src/app/page.tsx              Clinical HUD shell
  src/components/               Queue, graph, surge, override, banner UI
  src/lib/api.ts                Typed API client
  package.json
PATIENT_TRIAGE_FEATURES_AND_ROADMAP.md  Feature and improvement plan
```

## How to Run Locally

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8003
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. The API is available at http://localhost:8003 and health checks are available at http://localhost:8003/health.

## Optional LLM Mode

LLM mode is disabled by default. For fictional or approved de-identified demo data, configure `backend/.env`:

```env
TRIAGE_USE_LLM=true
LOCAL_ONLY_MODE=false
GROQ_API_KEY=your-key
GOOGLE_API_KEY=your-key
GROQ_MODEL=openai/gpt-oss-20b
GEMINI_MODEL=gemini-3-flash-preview
TRIAGE_MAX_CONCURRENT_CALLS=4
TRIAGE_LLM_CALLS_PER_MINUTE=12
```

The system uses local rules first. Groq is reserved for closed-vocabulary symptom extraction and Gemini for ambiguous-case reasoning. Gemini receives the complete redacted structured case (complaint, vitals, pain, data quality, extracted symptoms, demographic flags, and graph evidence), but its recommendation cannot reduce urgency below the deterministic safety level. Providers are rate-limited in a rolling one-minute window, de-identified before transmission, and protected by a circuit breaker. Provider failures return a valid deterministic result with `degraded_mode=true`. Set `LOCAL_ONLY_MODE=true` to guarantee no external calls.

Never commit `.env` or paste API keys into source control, screenshots, or chat.

## Demo Flow

1. Open P001 to show an ambiguous low-pain presentation with a cardiac safety path.
2. Enable the 3x surge to activate additional catalogue patients.
3. Select a patient, set a reassessment interval, and observe the due flag when its review is overdue.
4. Use **Worsen vitals & re-triage** to show deterioration moving a patient within their acuity bucket.
5. Open **Clinician override**, provide a rationale, and submit it; the active queue level changes immediately.
6. Toggle **Fail-safe demo** to demonstrate deterministic operation when AI is unavailable.

## API Endpoints

| Endpoint | Method | Purpose |
|---|---:|---|
| `/health` | GET | Service health and fail-safe state |
| `/status` | GET | Queue depth, fallback rate, and provider telemetry |
| `/queue` | GET | Active ranked queue |
| `/graph` | GET | Cytoscape graph data |
| `/triage/intake` | POST | Assess a patient |
| `/patients/{patient_id}/vitals` | POST | Update vitals and reassess |
| `/surge` | POST | Activate or reset a simulated surge |
| `/demo/failsafe` | POST | Toggle deterministic demo mode |
| `/override` | POST | Record clinician override, make it active, and record graph calibration |
| `/encounters/{id}/accept` | POST | Move the patient from the waiting queue to treatment |
| `/encounters/{id}/override` | POST | Audited rationale-required override |
| `/encounters/{id}/escalate-now` | POST | Immediate active Level 1 escalation |
| `/encounters/{id}/answer` | POST | Supply a missing vital and reassess |
| `/encounters/{id}/second-opinion` | POST | Flag physician review |
| `/encounters/{id}/reassessment-interval` | PATCH | Persist and schedule a patient-specific interval |
| `/ws/queue` | WebSocket | Stream queue snapshots |

## Data and Information Safety

The repository contains fictional data only. With LLM mode enabled, selected de-identified complaint text and vitals are sent to the configured external provider. This configuration is not suitable for real patient information. Use `LOCAL_ONLY_MODE=true` for privacy-sensitive demos.

Before real hospital use, the project would require private or approved provider endpoints, encryption, authentication, role-based access, secrets management, audit controls, data retention policies, security testing, clinical validation, and hospital privacy approval.

## Optimization

The project is optimized around a 20-patient active hospital simulation:

- The catalogue is independent from active encounters.
- Clear cases use deterministic local processing.
- Ambiguous cases use LLMs selectively.
- Queue refreshes make no external provider calls; they only mark overdue reassessment and apply the deterministic queue policy.

## Queue Safety Policy

The queue is sorted in this exact order:

1. Triage level, where Level 1 is always ahead of Levels 2-5.
2. Confirmed deterioration from a new vital-sign assessment.
3. A reassessment that is due, which prompts staff to obtain new observations.
4. Capped linear wait fairness within the same level only.

Waiting time alone never promotes a patient into a more urgent clinical level. A clinician override or manual escalation writes a new active triage record and immediately reorders the queue. This prototype policy is for the fictional demo only and requires local clinical governance and validation before any deployment.
- Provider concurrency defaults to four.
- Provider budgets default to five calls per backend process.
- Successful results are cached.
- Quota failures activate a cooldown and immediately use fallback.

## Future Scope

See [PATIENT_TRIAGE_FEATURES_AND_ROADMAP.md](PATIENT_TRIAGE_FEATURES_AND_ROADMAP.md) for the full feature plan. The highest-value next steps are:

- Add structured data-quality and missing-field explanations.
- Expand and version the symptom library with aliases.
- Add a tested, transparent ranking formula with score components.
- Add richer explanations, evidence IDs, and counterfactuals.
- Add encounter lifecycle states such as waiting, in treatment, discharged, and cancelled.
- Add automated integration, safety, load, and fallback tests.

## Limitations

- The dataset is fictional and not clinically validated.
- Thresholds are illustrative and are not a substitute for hospital protocols.
- SQLite is suitable for this prototype, not a production hospital deployment.
- AI output must remain clinician-reviewable and must not be treated as a diagnosis.
- ROI and clinical benefit require prospective validation.
