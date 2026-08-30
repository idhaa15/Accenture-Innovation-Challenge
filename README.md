# MediLens — Safety-First Emergency Triage

[![Live Demo](https://img.shields.io/badge/Open-Live%20Demo-315f53?style=for-the-badge)]((https://drive.google.com/drive/folders/1Fz94vi-Rk7NqGDjhDlwOIb54pm1JdVDh?dmr=1&ec=wgc-drive-hero-goto))
[![API](https://img.shields.io/badge/API-FastAPI-111827?style=for-the-badge)](http://localhost:8003/health)

> **Decision support only.** MediLens is a fictional hackathon prototype, not a diagnostic device, validated clinical protocol, or real-patient deployment.

## Table of Contents

- [Problem solved](#problem-solved)
- [What we built and why](#what-we-built-and-why)
- [Workflow](#workflow)
- [How the prototype addresses the challenge](#how-the-prototype-addresses-the-challenge)
- [Safety, uncertainty, and accountability](#safety-uncertainty-and-accountability)
- [Prototype evidence and demo flow](#prototype-evidence-and-demo-flow)
- [Business impact and feasibility](#business-impact-and-feasibility)
- [Target users](#target-users)
- [Three-phase roadmap](#three-phase-roadmap)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Run locally](#run-locally)
- [Data, privacy, and jurisdiction](#data-privacy-and-jurisdiction)
- [Limitations and future scope](#limitations-and-future-scope)

## Problem solved

Emergency departments must make explainable prioritisation decisions in seconds despite incomplete history, ambiguous symptoms, different age-related risk profiles, and fluctuating demand. The cost of under-triage is much higher than over-triage, yet the clinician must retain final authority.

MediLens is a clinician-facing queue and reassessment prototype. It turns fictional intake data into a transparent five-level **prototype urgency** recommendation, highlights uncertainty and missing critical measurements, keeps waiting patients visible for reassessment, and records clinician decisions.

## What we built and why

### Approaches considered

| Approach | Strength | Why it was not sufficient alone |
|---|---|---|
| Pure rules | Predictable, auditable, works offline | Brittle for atypical or ambiguous free-text presentations. |
| Pure LLM triage | Handles narrative context and symptom combinations | Cannot be trusted as an unconstrained clinical authority; can fail, vary, or return invalid output. |
| Black-box risk score | Simple rank output | Hides evidence and uncertainty; difficult for clinicians to challenge. |
| **Chosen: LLM-led, safety-bounded hybrid** | Rich narrative reasoning with deterministic safety and continuity | Best fit for a hackathon prototype: transparent, fail-safe, clinician-controlled. |

### Final design

- **Gemini is the primary reasoner** when enabled. It receives a redacted structured case and returns JSON containing approved symptoms, urgency level, confidence, escalation state, and human-readable reasoning.
- **LangGraph orchestrates** extraction/context, demographic/data-quality checks, graph evidence, and synthesis.
- **Deterministic safety shell** validates input and prevents observed immediate danger (SpO₂ <90 or systolic BP <90) from being downgraded.
- **Deterministic fallback** returns a complete recommendation if AI is disabled, unavailable, invalid, timed out, rate-limited, or forced into fail-safe mode.
- **Clinician control** is explicit: override, immediate escalation, patient update/reassessment, missing-vital capture, review flag, and accept-to-treatment are recorded.

This separation was deliberate: the LLM interprets the case; deterministic code protects hard boundaries and keeps the workflow available; a clinician owns the final decision.

## Workflow

```text
Landing page → new intake / patient update
             ↓
FastAPI + Pydantic validates fields and units
             ↓
LangGraph StateGraph
  ├─ data quality + age-aware context
  ├─ NetworkX symptom-risk evidence
  └─ Gemini structured reasoning (if available)
             ↓
Observed-emergency safety floor / deterministic fallback
             ↓
SQLite triage history + audit actions
             ↓
Ranked live queue and clinician review
```

### Queue policy

The queue never lets wait time cross a prototype urgency level. Within a level it orders:

1. Level 1–5 prototype urgency.
2. Confirmed deterioration after new observations.
3. Critical measurement review (missing SpO₂ or systolic BP).
4. Reassessment due.
5. Capped wait-time fairness.

### Patient update and reassessment

The **Update patient** control accepts revised complaint/symptoms and vitals, persists them, re-runs triage, logs changed fields, and refreshes the queue. Nurse Copilot captures one missing observation at a time. This supports continuous triage rather than a one-time score.

## How the prototype addresses the challenge

| Challenge requirement | MediLens response | Prototype evidence |
|---|---|---|
| Ambiguous / overlapping symptoms | LLM-led structured reasoning plus a closed symptom vocabulary and graph evidence. | P001 has vague epigastric pain with nausea and jaw radiation. |
| Pediatric, adult, geriatric variation | Age-band context flags and age-aware observed-vital checks. | P002/P011/P020 are pediatric; P004/P010/P016 are geriatric. |
| Incomplete data | Missing values are explicitly unknown; no normal-value imputation. Missing SpO₂/BP creates measurement review. | P002 has missing BP; Nurse Copilot requests an observation. |
| Explainable decisions in seconds | UI shows evidence bullets, confidence, observed vitals, graph path, and queue status. | Every assessment returns explanation and reasoning history. |
| Asymmetric under-triage cost | Observed emergency floor cannot be downgraded; critical graph evidence, low confidence, and measurement review make risk visible to staff. | SpO₂ <90 or systolic BP <90 produces a Level 1 floor. |
| Surge behaviour | Reversible 3× surge inserts 10 additional fictional encounters and re-ranks safely. | **Simulate 3× surge** button. |
| Human review and override | Required-rationale clinician override and manual escalation become the active queue decision. | Override table and triage history in SQLite. |
| Ongoing waiting-room monitoring | Reassessment intervals, due flags, vital updates, and patient update workflow. | Queue refreshes every 3 seconds; reassessment schedule persists. |
| Different hospital scales | Catalogue is separate from active encounters; provider concurrency/rate limits and local fallback reduce dependency on external calls. | Baseline five-patient queue plus 20-record catalogue. |

## Safety, uncertainty, and accountability

### Explicit uncertainty policy

```text
Missing observation ≠ normal
Missing observation ≠ abnormal
Missing critical observation = measure and review urgently
```

Missing data alone does not claim disease or silently change the clinical level. It lowers confidence and creates an actionable measurement-review state. Observed instability still receives a hard safety floor.

### Escalation bias

MediLens is not optimised for average classification accuracy. The system prioritises avoiding false reassurance by:

- preventing an LLM from downgrading observed SpO₂ <90 or systolic BP <90;
- retaining critical graph evidence and low-confidence escalation flags for clinician review;
- prioritising critical missing measurements within the same urgency bucket;
- returning deterministic fail-safe output rather than failing closed when an external provider is unavailable;
- allowing immediate Level 1 clinician escalation.

This is a prototype safety posture, not evidence of clinical calibration. Prospective validation is required before any real use.

### Accountability and audit trail

SQLite WAL stores patient inputs, triage recommendations, confidence, data quality, graph/reasoning trace, trigger reason, clinician overrides, manual escalation, update actions, and graph-weight history. Overrides require clinician ID and rationale; the clinician-set level becomes the active queue decision.

The assumed jurisdiction is **HIPAA / United States** for the prototype’s override field. This label does **not** make the project HIPAA compliant.

## Prototype evidence and demo flow

### Scenario coverage

The fictional demonstration catalogue includes at least 20 varied encounters: ambiguous complaints, pediatric and geriatric presentations, no-history patients, missing measurements, observed instability, trauma, respiratory, neurological, and lower-acuity comparison cases.

### Suggested live demo

1. Open the landing page and start a new assessment.
2. Select an ambiguous, low-pain presentation to show risk evidence.
3. Select **Simulate 3× surge** and show that hard urgency boundaries remain intact.
4. Open a patient with missing vital data; use **Ask nurse copilot** to collect an observation.
5. Use **Update patient** to add symptoms/vitals and show reassessment + queue change.
6. Submit a clinician override with a rationale; show the updated active level.
7. Toggle **Fail-safe** to demonstrate a complete deterministic response when AI is unavailable.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, React 18, TypeScript, Cytoscape.js, Lucide |
| API | FastAPI, Uvicorn, Pydantic v2 |
| Orchestration | LangGraph `StateGraph`; LangChain Core dependency |
| LLM | Google Gemini (`google-genai`); Groq adapter retained for vocabulary extraction |
| Safety / evidence | Python rules, NetworkX, NumPy |
| Storage | SQLite with WAL mode |

## Project structure

```text
backend/
  app/main.py                 API, queue, reassessment, WebSocket
  app/graph/agents.py         LangGraph and deterministic fallback
  app/graph/llm_provider.py   Redacted Gemini/Groq provider adapters
  app/graph/symptom_graph.py  NetworkX evidence graph
  app/core/                   Redaction and queue policy
  app/db/                     SQLite schema and audit persistence
  app/mock_data/              Fictional demo catalogue
frontend/
  src/app/page.tsx            MediLens workflow and queue
  src/components/             Graph, override, Nurse Copilot, patient update
README.md
```

## Run locally

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8003
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).


Set `LOCAL_ONLY_MODE=true` to guarantee no external calls. If the provider fails, inspect backend logs for `gemini_synthesis_failed`; the fallback remains available.

## Data, privacy, and jurisdiction

- Repository data is fictional. Do not enter real patient information.
- The provider adapter redacts direct identifiers before external calls, but regex redaction is not a substitute for a hospital privacy programme.
- Production requires approved/private inference, encryption, role-based access, secrets management, retention/deletion policies, immutable audit export, security testing, and legal/privacy approval.
- HIPAA is assumed for the hackathon; no compliance claim is made.

## Business impact and feasibility

### How MediLens makes an impact

MediLens targets the operational gap between arrival and clinician review: it consolidates observed facts, uncertainty, reasoning, reassessment status, and queue order into one clinician-controlled workflow. The intended benefit is not autonomous triage; it is faster recognition of patients who need review, fewer missed reassessment prompts, and less manual queue scanning during surge conditions.

### Illustrative pilot impact model

These are conservative planning assumptions for a 200-bed hospital with roughly 200 ED visits/day. They are **not clinical-outcome claims or guarantees**.

| Metric | Illustrative baseline | Pilot target | Why it matters |
|---|---:|---:|---|
| Time to an explainable triage recommendation | 8–12 min | 3–5 min | Saves 5–7 minutes of staff coordination per arrival. |
| Reassessment visibility | Manual, variable | 100% of active waiting encounters flagged when due | Reduces silent waiting-room lapses. |
| Queue review time during a 3× surge | 10–15 min manual scan | <2 min ranked review | Helps charge staff react to changing load. |
| Staff time released | — | 3–5 nursing/triage hours per day | Equivalent to ~90–150 hours/month for redeployment. |
| Avoided delayed-review events | — | 5–10/month flagged earlier | A safety/process measure, not a diagnosis claim. |

### Feasibility

- **Technical:** works with local rules when AI is unavailable; does not require an LLM call to render or rank the queue.
- **Workflow:** fits existing triage roles—nurse captures observations, clinician reviews/overrides, charge nurse sees queue state.
- **Deployment:** begins as a standalone overlay; later integrates with EHR/vitals feeds via FHIR/HL7.
- **Adoption:** explanations, confidence, and required override rationale make recommendations challengeable rather than opaque.

### Illustrative production investment and ROI

Low-end India pilot planning estimate; final costs depend on hospital integration, security, and validation scope.

| Item | One-time | Monthly |
|---|---:|---:|
| 8–12 week controlled pilot: integration, UI hardening, audit/security baseline | ₹8–12 lakh | ₹0.8–1.5 lakh |
| Initial production rollout: managed hosting, SSO/RBAC, monitoring, support | ₹18–30 lakh | ₹2–4 lakh |

Illustrative annual value model: reclaiming 3–5 triage/nursing coordination hours/day at ₹350/hour yields roughly **₹3.8–6.4 lakh/year** in redeployable capacity. If the system also prevents one avoidable high-cost delayed-review escalation per quarter, the pilot can plausibly justify its operating cost; this must be measured prospectively rather than assumed. A low-cost pilot therefore focuses first on operational metrics: triage time, reassessment completion, override rate, and delayed-review flags.

## Target users

| User | Primary job | MediLens value |
|---|---|---|
| Triage nurse | Capture intake, missing vitals, and reassessment data | Fast structured intake; Nurse Copilot prompts for missing observations. |
| ED physician | Confirm, override, or escalate urgency | Reviewable evidence, confidence, and documented override path. |
| Charge nurse / ED coordinator | Manage queue during normal and surge volume | Hard urgency boundaries, due reviews, and surge simulation/visibility. |
| Hospital quality and operations teams | Audit process reliability and bottlenecks | Triage/action history, override patterns, and measurable pilot metrics. |
| IT / clinical informatics | Govern safe rollout | Clear integration boundary, fallback mode, and future FHIR/HL7 path. |

## Three-phase roadmap

| Phase | Timeline | Goal | Deliverables / success measures |
|---|---|---|---|
| 1. Controlled pilot | 0–3 months | Prove workflow value with fictional or approved de-identified data | Role-based access, protocol configuration, 50–100 reviewed cases, safety regression suite, triage-time and reassessment baseline. |
| 2. Hospital integration | 3–9 months | Connect to one ED without changing clinician authority | FHIR/HL7 intake/vitals, managed database, immutable audits, SSO/RBAC, downtime workflow, prospective clinician evaluation. |
| 3. Scale and validate | 9–18 months | Validate generalisability across sites | Multi-site calibration, subgroup/fairness analysis, model monitoring, specialty configurations, formal governance and regulatory pathway. |

## Limitations and future scope

### Known hackathon limitations

- Symptom graph and thresholds are small, hand-authored, and clinically unvalidated.
- LLM confidence is not calibrated probability and must not be treated as one.
- Provider latency, quota, availability, and model behaviour can change.
- SQLite and local process state are prototype-only.
- No real EHR/HL7/FHIR integration, identity matching, authentication, or production monitoring exists.
- The UI is clinician-supportive but has not undergone usability testing with clinical staff.

### Production-ready roadmap

1. Clinical governance: versioned hospital protocol, clinician review board, prospective validation, subgroup fairness and false-reassurance evaluation.
2. Evidence/data: licensed ontology, multilingual aliases, data card, controlled labels, unit/timestamp provenance, calibration and counterfactual testing.
3. Security/privacy: SSO/RBAC, encryption, key management, immutable audit export, retention policy, threat modelling, approved data-processing agreements.
4. Integration: FHIR/HL7 adapters, EHR history, device feeds, bed/staff context, downtime workflows, encounter identity management.
5. Reliability: managed database, migrations, observability, load testing, alerting, provider failover, replayable safety test suite.
6. Human factors: role-specific workflows, review queue, explanation usability studies, override analytics, and local policy configuration.

## License

For hackathon demonstration and evaluation. Confirm licensing and governance before reuse.
