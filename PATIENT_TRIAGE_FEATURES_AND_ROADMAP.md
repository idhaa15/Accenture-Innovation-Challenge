# PatientTriage.ai — Features, Technology Map, and Improvement Roadmap

## 1. Purpose

PatientTriage.ai is a safety-first emergency-department triage prototype. It combines a clinical symptom graph, deterministic safety rules, optional LLM reasoning, queue-priority decay, clinician overrides, and an audit trail.

This document is separate from the project README. It is the working product and engineering guide for deciding what exists today, what technology supports it, and what should be built next.

> This is a fictional clinical decision-support prototype. It is not a diagnostic device, medical advice system, or validated clinical protocol.

## 2. Current Architecture

```text
Next.js Clinical HUD
  | REST/JSON + WebSocket queue feed
  v
FastAPI API
  |
  v
Compiled LangGraph workflow
  |-- Node Extraction: deterministic labels, optional Groq
  |-- Demographic Specialist: age-aware vital rules
  |-- Safety Adversary: NetworkX shortest-path search
  |-- Synthesizer: optional Gemini, deterministic safety fallback
  |
  +--> NetworkX symptom graph
  +--> NumPy queue wait-time scoring
  +--> SQLite WAL audit store
```

### Runtime flow

1. A patient arrives through `POST /triage/intake`.
2. Pydantic validates the request.
3. LangGraph runs node extraction.
4. Demographic calibration and safety-adversary analysis run as parallel branches.
5. The synthesizer produces a bounded triage level and confidence.
6. If an external model fails, the deterministic scorer completes the assessment and sets `degraded_mode=true`.
7. The patient and triage result are written to SQLite.
8. The frontend reads the queue and renders the reasoning path.

## 3. Implemented Features

### 3.1 Live ED queue

**What it does:** Displays patients sorted by acuity and waiting-time priority.

**Technology:**

- Next.js 14 App Router and React 18
- FastAPI `GET /queue`
- SQLite patient and triage records
- NumPy vectorized wait-time calculation
- Five-second frontend polling
- WebSocket endpoint at `/ws/queue`

**Current limitation:** The frontend primarily relies on polling. WebSocket reconnection and active push subscription should be made explicit.

### 3.2 Neuro-symbolic symptom graph

**What it does:** Connects symptom nodes to risk hubs and critical endpoints such as myocardial infarction, sepsis, stroke, respiratory failure, and internal bleeding.

**Technology:** NetworkX.

**Current behavior:** The Safety Adversary searches for short paths from extracted symptoms to critical nodes. A short path can increase urgency even when the reported pain is low.

**Current limitation:** The graph is hand-authored and small. It is not sourced from a validated medical ontology and must not be represented as clinical truth.

### 3.3 LangGraph multi-agent orchestration

**What it does:** Runs a typed state graph with four stages:

```text
Node Extraction -> Demographic Specialist
                  -> Safety Adversary
                  -> Synthesizer
```

The demographic and safety branches execute in parallel and merge before synthesis.

**Technology:**

- LangGraph `StateGraph`
- TypedDict `TriageState`
- LangChain Core dependency
- Reducer for merging parallel reasoning entries

**Current limitation:** The LLM agents are adapters inside a safety-bounded flow, not autonomous clinical agents. The deterministic rules remain the source of continuity and guardrails.

### 3.4 Optional live LLM calls

**Groq:** Extracts symptom labels from free text using a closed graph vocabulary.

**Google Gemini:** Produces a structured synthesis candidate containing triage level, confidence, and escalation state.

**Technology:**

- Groq async SDK
- Google `google-genai` async SDK
- JSON-only response contracts
- Model timeouts
- Environment-based API keys

**Current defaults:**

- Groq: `openai/gpt-oss-20b`
- Gemini: `gemini-3-flash-preview`

**Current limitation:** Provider model names, quotas, latency, and regional availability can change. Model availability must be checked at deployment time.

### 3.5 Deterministic fail-safe mode

**What it does:** Ensures a complete answer when an API key is missing, a model times out, a provider returns an error, or the model response is invalid.

**Technology:** Python rules, Pydantic bounds, LangGraph error handling, and `degraded_mode` response metadata.

**Safety behavior:** Missing or uncertain data reduces confidence rather than silently assuming a healthy value. Confidence below `0.70` triggers escalation logic.

**Frontend behavior:** The degraded-mode banner makes fallback visible to the user.

### 3.6 Age-aware demographic analysis

**What it does:** Adjusts interpretation for pediatric, adult, and geriatric patients.

**Technology:** Python rules in the demographic LangGraph node.

**Current checks include:**

- Pediatric tachycardia, respiratory rate, fever, and oxygen concern
- Adult fever and oxygen concern
- Geriatric confusion, temperature risk, and oxygen concern
- Hypotension and severe tachycardia across age bands
- Missing vital detection

**Current limitation:** Thresholds are illustrative demo ranges, not validated clinical protocols.

### 3.7 Vitals-triggered reassessment

**What it does:** Re-runs triage when vital signs cross age-band-specific deltas.

**Technology:** FastAPI vitals route and deterministic delta checks in `queue_decay.py`.

**Current endpoint:** `POST /patients/{patient_id}/vitals`.

**Current limitation:** The frontend demo changes heart rate and SpO2 but does not yet show a detailed before/after comparison or event timeline.

### 3.8 Surge simulation and wait-time decay

**What it does:** Adds mock patients to simulate high volume and increases queue priority as wait time grows.

**Technology:** NumPy formula:

```text
S_dynamic = S_base * exp(lambda * wait_seconds)
```

The surge button is reversible. A second click removes injected surge patients and restores the baseline queue.

**Current limitation:** Surge injection is batch-based rather than a configurable timed stream.

### 3.9 Clinician override and synaptic update

**What it does:** Allows a clinician to change the recommended level, provide a required rationale, and write an audit record.

**Technology:**

- React override modal
- FastAPI `POST /override`
- SQLite `clinician_overrides`
- NetworkX edge-weight update
- SQLite `synaptic_weight_history`

**Current limitation:** Weight updates are in-memory and reset when the backend restarts. Persisted graph learning is a priority improvement.

### 3.10 Explainable reasoning display

**What it does:** Shows the four stage names, graph nodes visited, conclusions, confidence, and escalation state.

**Technology:** LangGraph reasoning log, FastAPI JSON, React components, Cytoscape.js.

**Current limitation:** The explanation is currently a compact path summary. It needs structured evidence, uncertainty causes, counterfactuals, and a clear distinction between model output and deterministic safety constraints.

### 3.11 Audit-first SQLite storage

**Stored data includes:**

- Patient identity and intake values
- Triage level and confidence
- Reasoning path
- Trigger reason
- Degraded-mode status
- Clinician override details
- Synaptic edge-weight history

**Technology:** SQLite with WAL mode.

**Current limitation:** This is suitable for a fictional prototype, not a production HIPAA/GDPR deployment. Production would need access control, encryption, retention policies, key management, immutable audit export, and a formal privacy review.

## 4. API and Data Contract Map

| Endpoint | Method | Purpose | Current state |
|---|---:|---|---|
| `/health` | GET | Service health and fail-safe state | Implemented |
| `/queue` | GET | Current ranked queue | Implemented |
| `/graph` | GET | Cytoscape node and edge data | Implemented |
| `/triage/intake` | POST | Run a new LangGraph assessment | Implemented |
| `/patients/{id}/vitals` | POST | Update vitals and conditionally reassess | Implemented |
| `/surge` | POST | Enable or reset mock surge | Implemented |
| `/demo/failsafe` | POST | Toggle deterministic demo mode | Implemented |
| `/override` | POST | Record clinician override and edge update | Implemented |
| `/ws/queue` | WebSocket | Stream queue snapshots | Implemented, needs stronger reconnect UX |

## 5. Technology by Repository Area

```text
backend/
  app/main.py                 FastAPI lifecycle, routes, WebSocket, orchestration calls
  app/graph/agents.py         LangGraph state, agents, model adapters, fallback logic
  app/graph/symptom_graph.py  NetworkX graph and synaptic update
  app/core/queue_decay.py     NumPy queue math and vital-delta checks
  app/db/database.py          SQLite schema and persistence functions
  app/db/models.py             Pydantic request and result models
  app/mock_data/*.json         Fictional demo records
  requirements.txt             Python dependencies

frontend/
  src/app/page.tsx            Main clinical HUD and state flow
  src/components/             Queue, graph, banner, surge, and override UI
  src/lib/api.ts              Typed REST client
  src/app/globals.css         Visual system and responsive layout
  package.json                Next.js and UI dependencies
```

## 6. Your Proposed Improvements

### 6.1 Build a comprehensive dataset

**Goal:** Move from manually written fictional records to a versioned, representative evaluation dataset.

**Recommended stages:**

1. Create a dataset specification before collecting data.
2. Define required fields, units, allowable ranges, missingness rules, provenance, and consent status.
3. Separate training, validation, demonstration, and hidden evaluation records.
4. Include age, sex where appropriate, pregnancy status where appropriate, comorbidities, medications, complaint text, vitals, arrival time, disposition, and clinician-assigned acuity.
5. Add difficult cases deliberately: ambiguous complaints, atypical presentations, pediatric cases, geriatric cases, language variation, missing fields, conflicting histories, and changing vitals.
6. Version every dataset change.
7. Add a data card describing origin, limitations, bias, intended use, and prohibited use.

**Important:** Do not use real patient data in this prototype without institutional approval, de-identification, privacy review, and an appropriate data-use agreement.

**Suggested future files:**

```text
data/
  schema/patient_input.schema.json
  schema/triage_label.schema.json
  raw/                 # excluded from Git
  processed/
  splits/
  data_card.md
  validate_dataset.py
```

**Success metrics:** schema-valid record rate, missingness by field, label agreement, subgroup coverage, and performance by age band and complaint category.

### 6.2 Handle less or missing data

**Goal:** Make uncertainty explicit and prevent false reassurance.

**Implement next:**

- Add a `data_quality` object to every result.
- Classify each field as `observed`, `missing`, `invalid`, `stale`, or `conflicting`.
- Add field-level confidence rather than only one global confidence value.
- Never replace missing vitals with normal values.
- Distinguish “not measured” from “normal.”
- Ask for the next highest-value missing datum when an interactive workflow is available.
- Apply conservative escalation when high-risk fields are missing.
- Record missingness in the audit log.

**Example contract:**

```json
{
  "data_quality": {
    "status": "incomplete",
    "missing_fields": ["systolic_bp"],
    "invalid_fields": [],
    "stale_fields": [],
    "next_best_questions": ["Measure systolic blood pressure"]
  }
}
```

**Success metrics:** no silent imputation, correct missingness classification, calibration by missingness pattern, and clinician acceptance of follow-up questions.

### 6.3 Expand the symptom library

**Goal:** Improve recall without allowing the LLM to invent graph nodes.

**Recommended design:**

- Maintain a canonical symptom vocabulary.
- Add synonyms, abbreviations, spelling variants, lay terms, and multilingual aliases.
- Store each term with `canonical_id`, `display_name`, `category`, `aliases`, and `source`.
- Map terms to graph nodes through a versioned mapping table.
- Track unmapped phrases rather than dropping them.
- Add unit tests for every alias.
- Use an ontology only with licensing and clinical review.

**Suggested schema:**

```json
{
  "canonical_id": "shortness_of_breath",
  "display_name": "Shortness of breath",
  "aliases": ["SOB", "breathless", "can't catch my breath"],
  "category": "respiratory",
  "graph_nodes": ["shortness_of_breath"],
  "source": "reviewed-demo-v1",
  "status": "active"
}
```

**Success metrics:** synonym recall, unmapped-text rate, false-positive rate, and coverage by age and language.

### 6.4 Improve explainable answers

**Goal:** Explain what was observed, what was inferred, why urgency changed, and what remains uncertain.

**Recommended explanation structure:**

```text
Recommendation: Level 1

Observed:
- Epigastric pain
- Jaw radiation
- Nausea

Safety concern:
- These symptoms activate a path to cardiac risk and myocardial infarction.

Patient context:
- Adult age band
- No demographic threshold flags

Uncertainty:
- Pain severity does not rule out serious disease.
- This is decision support, not a diagnosis.

Why this level:
- The safety adversary found a short critical path.
- The final level is bounded by the highest-risk branch.

Next data to collect:
- ECG and clinician-directed cardiac assessment
```

**Technical changes:**

- Replace free-form conclusion strings with typed explanation objects.
- Store evidence IDs and graph-edge IDs.
- Add `why_escalated`, `why_not_lower`, `uncertainty_factors`, and `next_data_needed`.
- Show deterministic constraints separately from LLM suggestions.
- Add counterfactual text: “If jaw radiation were absent, this safety path would not activate.”
- Prohibit the model from claiming a diagnosis or certainty it did not establish.

### 6.5 Build a ranking system

**Goal:** Rank queue patients consistently using urgency, deterioration risk, wait time, uncertainty, and data quality.

**Recommended initial score:**

```text
priority_score =
    acuity_score
  + deterioration_score
  + uncertainty_score
  + wait_decay_score
  - completed_care_score
```

Keep each component visible. Do not expose a single opaque number without its factors.

**Suggested ranking policy:**

1. Critical safety flags and unstable vitals dominate.
2. Deterioration risk comes next.
3. Wait-time decay prevents indefinite waiting.
4. Uncertainty can increase priority when high-risk information is missing.
5. Stable low-acuity patients remain lower priority even during normal conditions.
6. Clinicians can override ranking, with an audit record.

**Technical changes:**

- Create `ranking.py` with pure functions.
- Return score components in `/queue`.
- Add deterministic tie-breakers: criticality, deterioration risk, arrival time, patient ID.
- Version the ranking formula.
- Test monotonicity: worsening vitals must never lower priority.
- Evaluate ranking fairness by age band and missingness pattern.

## 7. High-Priority Feature Roadmap

### Priority 0 — Reliability and correctness

- Add automated backend tests for every API endpoint.
- Add tests for both live-provider and fallback paths.
- Add request IDs and structured logs.
- Persist graph weight updates across restarts.
- Add provider circuit breakers and cooldowns.
- Add retry only for safe transient errors, with exponential backoff.
- Add a model/provider status endpoint that exposes status categories, never keys.
- Add explicit input validation for units and timestamps.

### Priority 1 — Clinical explainability and missing data

- Add field-level data quality.
- Add structured explanation objects.
- Add next-best-question support.
- Add counterfactual reasoning.
- Add evidence and graph-edge references.
- Add clinician feedback on explanation usefulness.

### Priority 2 — Ranking and queue intelligence

- Extract ranking into a versioned pure scoring module.
- Return score components and reason codes.
- Add deterioration trend features from repeated vitals.
- Add configurable surge profiles.
- Add fairness and monotonicity evaluation.

### Priority 3 — Dataset and symptom library

- Create JSON Schema and dataset validator.
- Expand to a reviewed fictional dataset.
- Add alias and multilingual symptom mapping.
- Add train/evaluation/demo split discipline.
- Add synthetic data generation with validation, not unrestricted model output.

### Priority 4 — Production hardening

- Replace SQLite with a managed transactional database when needed.
- Add authentication and role-based access control.
- Add encrypted secrets management.
- Add immutable audit export.
- Add retention and deletion workflows.
- Add observability dashboards.
- Add load testing and provider quota monitoring.

## 8. Suggested Test Strategy

### Unit tests

- Symptom alias mapping
- Age-band thresholds
- Missing-data classification
- NetworkX path selection
- Priority-score monotonicity
- Synaptic update bounds
- Queue decay math
- Pydantic validation

### Integration tests

- Intake to SQLite audit log
- Vitals update to conditional reassessment
- Override to audit record and graph update
- Surge on/off behavior
- WebSocket snapshot delivery
- LangGraph live-provider path
- LangGraph fallback path

### Safety-oriented tests

- Missing high-risk vitals never produce a falsely reassuring “complete” state.
- A critical path cannot be removed by a lower-confidence LLM suggestion.
- Provider errors never return an empty or unbounded triage result.
- Worsened vitals cannot reduce priority.
- Every clinician override remains in the audit table.

### Evaluation metrics

- Schema validation rate
- Symptom extraction precision and recall
- Critical-path recall
- Calibration error by age band
- Sensitivity to deterioration
- False reassurance rate
- Fallback completion rate
- Median and p95 triage latency
- Queue ranking stability
- Explanation usefulness rating

## 9. Recommended Next Build Slice

The most valuable next increment is not more model complexity. Build a trustworthy data and explanation layer first:

1. Add `data_quality` and `explanation` fields to `TriageResult`.
2. Create a versioned symptom-library JSON file with aliases.
3. Add a dataset validator and 50 to 100 fictional evaluation cases.
4. Extract the ranking formula into a tested module with visible score components.
5. Add API and LangGraph integration tests for live and fallback modes.
6. Update the frontend to show observed facts, safety paths, uncertainty, and next data needed.

That slice improves safety, demo clarity, evaluation quality, and future model replacement at the same time.

## 10. Definition of Done for the Next Version

The next version is ready for a stronger demo when:

- Every triage result explains its evidence and uncertainty.
- Missing data is visible and never silently imputed.
- The symptom library is versioned and test-covered.
- Queue ranking exposes component scores and reason codes.
- All 20 demo patients plus an evaluation set pass validation.
- Live API failure switches to fallback without a broken screen.
- Overrides persist across backend restarts.
- Tests cover intake, reassessment, surge, override, WebSocket, live LLM, and fallback flows.
- Documentation clearly separates implemented prototype behavior from planned clinical-grade work.

## 11. Canonical Dataset Versus Active Hospital Queue

### Decision

Keep `simulated_patients.json` as the **ultimate fictional dataset**: the complete pool of patients that can be used for demos, testing, evaluation, surge simulation, and regression checks.

Do not treat every record in that file as currently seeking treatment. Treat the file as a source-of-truth catalogue, then maintain a separate active-treatment state in the database.

```text
simulated_patients.json
  = complete fictional patient catalogue

SQLite active encounters
  = patients currently seeking treatment

Live queue
  = active encounters filtered and ranked by acuity, deterioration, uncertainty, and wait time
```

### Why this is better

- The full dataset remains stable for repeatable evaluation.
- The active queue can contain 5, 20, or 1,000 simulated patients without changing the source file.
- Patients can move through intake, waiting, treatment, discharge, or cancellation states.
- Surge mode can activate more catalogue records without duplicating patient definitions.
- Tests can reset the active queue while preserving the dataset.
- Ranking is based on current encounters rather than on every available test record.

### Current behavior

The current prototype already approximates this model:

- The JSON file contains 20 fictional patient records.
- On a clean startup, the first five are inserted into the active database queue.
- Surge mode inserts additional records from the same JSON pool.
- Surge reset removes injected records and returns to the five-patient baseline.

However, the current database does not yet have an explicit encounter status. It infers active membership from which patient rows exist, so it should be upgraded before the dataset grows.

### Recommended data model

Add an `encounters` table rather than modifying the source dataset:

```sql
CREATE TABLE encounters (
    encounter_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'waiting', 'triaged', 'in_treatment', 'discharged', 'cancelled'
    )),
    arrival_ts TEXT NOT NULL,
    departure_ts TEXT,
    source_dataset TEXT NOT NULL DEFAULT 'simulated_patients_v1',
    surge_batch_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

Then change queue retrieval to:

```sql
SELECT ...
FROM encounters e
JOIN patients p ON p.patient_id = e.patient_id
JOIN latest_triages t ON t.encounter_id = e.encounter_id
WHERE e.status IN ('waiting', 'triaged')
ORDER BY dynamic_score DESC;
```

### Recommended dataset structure

Keep the current simple JSON file for the prototype, then evolve toward:

```text
data/
  catalogue/
    simulated_patients_v1.json
    simulated_patients_v2.json
  scenarios/
    baseline_5.json
    surge_3x.json
    missing_vitals.json
    deterioration.json
  schemas/
    patient.schema.json
    encounter.schema.json
  manifests/
    dataset_manifest.json
```

The manifest should record the dataset version, number of records, scenario labels, generation date, and validation results.

### Example lifecycle

```text
P001 exists in the catalogue
  -> encounter E001 is created at 09:14
  -> E001 status = waiting
  -> triage assessment is stored
  -> E001 status = in_treatment
  -> E001 status = discharged
```

The catalogue record remains unchanged. Only the encounter and triage history change.

### Recommended APIs

```text
POST /encounters              Create an active treatment encounter
GET  /encounters              List active and historical encounters
GET  /queue                   List waiting/triaged encounters only
PATCH /encounters/{id}/status Move an encounter through its lifecycle
POST /surge                   Activate a scenario or batch of catalogue records
POST /surge/reset             End the active surge batch
```

### Build order

1. Keep `simulated_patients.json` unchanged as the catalogue.
2. Add explicit `encounter_id` and `status` fields in SQLite.
3. Add a clean-queue command for development and demos.
4. Add scenario manifests for baseline, surge, missing-data, and deterioration tests.
5. Update the frontend queue to display encounter status.
6. Add tests proving that catalogue size and active queue size are independent.

This means the answer is **yes**: the 20-record file can remain the ultimate dataset, while only a selected subset is currently seeking treatment. The database should own active treatment state; the JSON file should remain immutable test and simulation input.

## 12. Optimization Policy for the 20-Patient Demo

The current catalogue may contain 100 records for evaluation, but the active hospital simulation is intentionally capped at 20 patients. Bulk assessments use this policy:

- Deterministic symptom extraction, demographic checks, and NetworkX safety traversal run first.
- Groq and Gemini are called only for ambiguous cases, not every patient.
- Provider calls are limited to four concurrent requests.
- Successful intake results are cached by patient input and runtime mode.
- Each backend process allows at most five calls per provider by default.
- Provider quota or timeout failures activate a 30-second circuit breaker and immediately use deterministic fallback.
- Queue refreshes, wait-time decay, graph rendering, and ranking never call external providers.

This keeps the 20-patient demo responsive and protects free-tier quotas while preserving live AI for the few cases where it adds the most value.

## 13. Independent Hospital Cost and ROI Model

### Planning assumptions

This model is for one independent hospital in India with approximately 100 to 300 beds and 150 to 300 emergency-department visits per day. It is a planning model, not a guarantee of savings or clinical outcomes.

### Indicative cost ranges

| Stage | One-time implementation | Monthly operating cost |
|---|---:|---:|
| Prototype/demo | ₹0–₹3 lakh | ₹0–₹25,000 |
| Controlled hospital pilot | ₹15–₹60 lakh | ₹1–₹5 lakh |
| Production deployment | ₹60 lakh–₹3 crore | ₹5–₹25 lakh |

The prototype cost is low because it uses fictional data, SQLite, local rules, and optional hosted model APIs. Production costs rise because of security, clinical validation, hospital-system integration, support, and governance rather than because of model inference alone.

### Pilot cost categories

- Backend and frontend hardening: ₹5–₹15 lakh
- Security, authentication, and access controls: ₹3–₹10 lakh
- Hospital workflow configuration: ₹5–₹20 lakh
- Clinical validation and staff training: ₹5–₹15 lakh
- Hosting, monitoring, backups, and support: ₹1–₹5 lakh per month

### LLM operating cost

The local-first optimization is central to the business case:

```text
Routine case -> deterministic rules and graph
Ambiguous case -> Groq extraction and possibly Gemini synthesis
Provider failure -> deterministic fallback
```

For 200 ED patients per day, if only 10–20% require LLM assistance, the system would process approximately 20–40 LLM-assisted patients per day. Depending on prompt size, model choice, quotas, and provider pricing, hosted model usage may initially be approximately ₹5,000–₹50,000 per month. Provider pricing must be rechecked before a commercial proposal.

### Potential annual value scenarios

| Benefit source | Conservative scenario | Strong pilot scenario |
|---|---:|---:|
| Avoidable adverse-event cost | ₹10 lakh | ₹75 lakh |
| Improved ED throughput/capacity | ₹15 lakh | ₹1 crore |
| Reduced staff coordination time | ₹5 lakh | ₹25 lakh |
| Reduced unnecessary admission/escalation | ₹5 lakh | ₹40 lakh |
| **Total modeled annual benefit** | **₹35 lakh** | **₹2.4 crore** |

These figures should be replaced with hospital-specific measurements after a silent-mode pilot.

### ROI scenarios

**Conservative:**

```text
Annual benefit: ₹35 lakh
Annual operating cost: ₹20 lakh
Net annual benefit: ₹15 lakh
Implementation cost: ₹50 lakh
Approximate payback: 3.3 years
```

**Base case:**

```text
Annual benefit: ₹90 lakh
Annual operating cost: ₹30 lakh
Net annual benefit: ₹60 lakh
Implementation cost: ₹50 lakh
Approximate payback: 10 months
```

**Strong outcome:**

```text
Annual benefit: ₹2.4 crore
Annual operating cost: ₹50 lakh
Net annual benefit: ₹1.9 crore
Implementation cost: ₹75 lakh
Approximate payback: 5 months
```

### Clinical benefit claims

Do not claim a fixed number of lives saved before clinical outcome evidence exists. The correct pilot metrics are:

- Critical under-triage events
- Delayed escalation events
- Deterioration before reassessment
- False reassurance events
- Time to clinician review
- Unnecessary escalation and admission rate
- Outcome differences by age band and missing-data pattern

A research scenario might model 1–5 serious deterioration or under-triage events identified earlier per hospital per year, but these are not equivalent to confirmed lives saved. Actual lives saved require prospective clinical evaluation and outcome review.

### Recommended business-case statement

> For one independent hospital, PatientTriage.ai could require approximately ₹15–₹60 lakh for a controlled pilot and ₹1–₹5 lakh monthly operating cost. If it prevents a small number of serious under-triage events and improves ED throughput by 1–3%, the modeled annual value could range from ₹35 lakh to ₹2.4 crore. Clinical and financial benefits must be validated prospectively rather than promised in advance.
