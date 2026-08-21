# PatientTriage.ai — Project Master Plan & System Specification (v2)
### Accenture Innovation Challenge 2026 — Round 2 Prototype
**Architecture: Neuro-Symbolic Agent Graph (hackathon-hardened)**

> **Changelog from v1 draft:** Removed the Pybind11/C++ queue core (build-failure risk with zero# PatientTriage.ai — Project Master Plan & System Specification (v2)
### Accenture Innovation Challenge 2026 — Round 2 Prototype
**Architecture: Neuro-Symbolic Agent Graph (hackathon-hardened)**

> **Changelog from v1 draft:** Removed the Pybind11/C++ queue core (build-failure risk with zero
> judge-visible benefit at this scale — replaced with vectorized NumPy that implements the identical
> decay formula). Added a mandatory deterministic fallback path for API rate-limit failure. Added
> vitals-triggered re-assessment (was missing — explicitly required by the brief). Added concrete
> compliance fields to the override log. Rebalanced the build roadmap accordingly.

---

## 1. System Architecture & Data Topography

```
┌─────────────────────────────────────────────────────────────────────┐
│  FRONTEND — Next.js 14 (App Router)                                  │
│  ┌───────────────────────┐   ┌──────────────────────────────────┐   │
│  │ Left: Clinical HUD     │   │ Right: Cytoscape.js Reasoning     │   │
│  │ - Live queue           │   │ Graph (animated agent traversal)  │   │
│  │ - Vitals + conf. bar   │   │                                    │   │
│  │ - Escalation badges    │   │                                    │   │
│  └───────────┬────────────┘   └────────────────┬───────────────────┘   │
│              │  WebSocket (live queue/vitals)   │ HTTP GET (graph)     │
└──────────────┼───────────────────────────────────┼──────────────────┘
               ▼                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  BACKEND — FastAPI (Python 3.11, async)                              │
│                                                                        │
│  POST /triage/intake ─────► LangGraph Multi-Agent Engine             │
│                                │                                      │
│                                ▼                                      │
│                     ┌─────────────────────┐                          │
│                     │ 1. Node Extraction   │ (Groq / Llama 3.1 8B)   │
│                     │ 2. Demographic Spec. │ ─┐ run in parallel      │
│                     │ 3. Safety Adversary  │ ─┘ (both need only      │
│                     │ 4. Synthesizer       │    extracted symptoms)  │
│                     └──────────┬───────────┘ (Gemini Flash)          │
│                                │                                      │
│                                ▼                                      │
│                     NetworkX Scale-Free Symptom Graph                │
│                     (50 nodes: symptom hubs → condition endpoints)   │
│                                │                                      │
│                     ┌──────────┴───────────┐                         │
│                     ▼                       ▼                         │
│           SQLite (WAL mode)         Queue Decay Engine (NumPy)       │
│           - patients                - vectorized S = S₀·e^(λt)      │
│           - triage_logs             - vitals-delta re-triage check   │
│           - clinician_overrides                                      │
│           - synaptic_weight_history                                  │
└─────────────────────────────────────────────────────────────────────┘
```

**Protocol split:** REST/JSON for intake, overrides, and graph fetch (stateless, cacheable). WebSocket
only for the queue panel — wait times and vitals need push updates; nothing else does. Don't put the
whole app on WebSockets, it complicates the demo for no reason.

**Fallback path (new):** every agent call goes through a wrapper that, on timeout or rate-limit
(HTTP 429), falls back to a deterministic rule-based ESI-style scorer and sets `degraded_mode: true`
on the response. The frontend renders a visible amber banner: *"AI reasoning unavailable — rule-based
fail-safe active."* This is not a bug to hide; script it into the demo (see Section 10).

---

## 2. Tech Stack & Dependency Matrix

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS | Fast to build, judge-familiar |
| Graph viz | Cytoscape.js + cytoscape-cose-bilkent (layout) | Handles 50-node animated graphs cleanly |
| Icons | lucide-react | Consistent, lightweight |
| Backend | FastAPI + Uvicorn, Python 3.11 | Async, typed, fast to stand up |
| Graph engine | NetworkX 3.x | Pure Python, no build step |
| Queue math | **NumPy** (replaces C++/Pybind11) | Same formula, zero build risk |
| Orchestration | LangGraph + langchain-core | Native multi-agent state graph |
| LLM (fast extraction) | Groq API — Llama 3.1 8B Instant | Sub-300ms symptom extraction |
| LLM (synthesis) | Google Generative AI SDK — Gemini 1.5/2.0 Flash | Cheap, fast, good at structured output |
| DB | SQLite3, WAL mode | Zero-ops, still durable for audit needs |
| Logging | structlog | Structured logs double as a debugging aid during the demo |
| Validation | Pydantic v2 | Type-safe contracts across every API boundary |

**Install:**
```bash
# backend
pip install fastapi uvicorn[standard] networkx pydantic groq google-generativeai \
            langgraph langchain-core numpy structlog python-dotenv aiosqlite

# frontend
npm install next react react-dom cytoscape cytoscape-cose-bilkent \
            lucide-react tailwindcss
```

No `setup.py`, no CMake, no compiler toolchain dependency. This alone removes the single biggest
cross-machine failure risk in the original plan.

---

## 3. File Directory

```
patient-triage-ai/
├── backend/
│   ├── app/
│   │   ├── main.py                      # FastAPI app, routes, WS endpoint
│   │   ├── graph/
│   │   │   ├── symptom_graph.py         # NetworkX graph build + synaptic_update()
│   │   │   └── agents.py                # LangGraph flow: 4 agent nodes + fallback wrapper
│   │   ├── core/
│   │   │   ├── queue_decay.py           # NumPy vectorized decay + vitals-delta re-triage
│   │   │   └── config.py                # env vars, API keys, thresholds
│   │   ├── db/
│   │   │   ├── database.py              # SQLite init, WAL pragma, connection pool
│   │   │   └── models.py                # Pydantic schemas
│   │   └── mock_data/
│   │       └── simulated_patients.json  # 20 patient records
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── app/page.tsx                 # Split-screen HUD shell
│   │   ├── components/
│   │   │   ├── CytoscapeGraph.tsx
│   │   │   ├── PatientCard.tsx
│   │   │   ├── SurgeToggle.tsx
│   │   │   ├── OverrideModal.tsx
│   │   │   └── DegradedModeBanner.tsx   # NEW — renders fallback state
│   │   └── lib/api.ts                   # typed fetch/WS client
│   └── package.json
└── README.md
```

---

## 4. Database Schema, Data Models & Mock Data

### SQLite Schema (audit-first design)

```sql
PRAGMA journal_mode=WAL;

CREATE TABLE patients (
    patient_id TEXT PRIMARY KEY,
    age_years INTEGER NOT NULL,
    age_band TEXT CHECK(age_band IN ('pediatric','adult','geriatric')) NOT NULL,
    has_prior_history BOOLEAN NOT NULL,
    arrival_ts TEXT NOT NULL,
    chief_complaint TEXT NOT NULL,
    consent_flag BOOLEAN NOT NULL DEFAULT 1     -- required under most health-data regs
);

CREATE TABLE triage_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL REFERENCES patients(patient_id),
    ts TEXT NOT NULL,
    triage_level INTEGER CHECK(triage_level BETWEEN 1 AND 5),
    confidence REAL NOT NULL,
    escalated_for_uncertainty BOOLEAN NOT NULL DEFAULT 0,
    reasoning_path TEXT NOT NULL,               -- JSON: node-by-node graph path
    degraded_mode BOOLEAN NOT NULL DEFAULT 0,   -- true if fallback scorer was used
    trigger_reason TEXT NOT NULL DEFAULT 'intake'  -- 'intake' | 'wait_decay' | 'vitals_change'
);

CREATE TABLE clinician_overrides (
    override_id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL REFERENCES patients(patient_id),
    clinician_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    ai_recommended_level INTEGER NOT NULL,
    ai_confidence REAL NOT NULL,
    overridden_level INTEGER NOT NULL,
    justification TEXT NOT NULL,                -- mandatory free-text, not optional
    jurisdiction TEXT NOT NULL DEFAULT 'HIPAA'   -- state your regime explicitly
);

CREATE TABLE synaptic_weight_history (
    update_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_node TEXT NOT NULL,
    target_node TEXT NOT NULL,
    old_weight REAL NOT NULL,
    new_weight REAL NOT NULL,
    triggered_by_override_id INTEGER REFERENCES clinician_overrides(override_id),
    ts TEXT NOT NULL
);
```

`clinician_overrides.justification` is `NOT NULL` on purpose — a compliance-grade override record
needs a reason, not just a new number. This single field is what makes "auditability" a real claim
instead of a bullet point.

### Pydantic Models (`db/models.py`)

```python
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime

class Vitals(BaseModel):
    heart_rate: int
    resp_rate: int
    temp_c: float
    spo2: int
    systolic_bp: int | None = None

class PatientInput(BaseModel):
    patient_id: str
    age_years: int
    has_prior_history: bool
    chief_complaint: str
    vitals: Vitals
    self_reported_pain: int = Field(ge=0, le=10)

class AgentReasoningPath(BaseModel):
    agent_name: str
    graph_nodes_visited: list[str]
    conclusion: str
    confidence_delta: float

class TriageResult(BaseModel):
    patient_id: str
    triage_level: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0, le=1)
    escalated_for_uncertainty: bool
    degraded_mode: bool
    reasoning_path: list[AgentReasoningPath]
    trigger_reason: Literal["intake", "wait_decay", "vitals_change"]

class OverridePayload(BaseModel):
    patient_id: str
    clinician_id: str
    overridden_level: int = Field(ge=1, le=5)
    justification: str = Field(min_length=10)   # force a real reason, not "n/a"
```

### Sample Records (5 of the 20 required)

```json
[
  {
    "patient_id": "P001", "age_years": 45, "has_prior_history": true,
    "chief_complaint": "vague epigastric pain, mild nausea, radiating to jaw",
    "vitals": {"heart_rate": 98, "resp_rate": 18, "temp_c": 37.1, "spo2": 97, "systolic_bp": 132},
    "self_reported_pain": 4,
    "note": "AMBIGUOUS — should trigger Safety Adversary to rule out atypical MI despite low pain score"
  },
  {
    "patient_id": "P002", "age_years": 3, "has_prior_history": false,
    "chief_complaint": "fever, lethargy, poor feeding",
    "vitals": {"heart_rate": 168, "resp_rate": 42, "temp_c": 38.6, "spo2": 94},
    "self_reported_pain": null,
    "note": "PEDIATRIC — adult-calibrated thresholds would under-triage this; HR/RR are age-abnormal, not absolute-abnormal"
  },
  {
    "patient_id": "P003", "age_years": 29, "has_prior_history": false,
    "chief_complaint": "MVC, visible arm deformity, no LOC reported",
    "vitals": {"heart_rate": 110, "resp_rate": 20, "temp_c": 36.9, "spo2": 98},
    "self_reported_pain": 8,
    "note": "ZERO-HISTORY trauma — no prior record; epistemic uncertainty should be explicitly elevated"
  },
  {
    "patient_id": "P004", "age_years": 78, "has_prior_history": true,
    "chief_complaint": "new confusion, family reports 'not himself since this morning'",
    "vitals": {"heart_rate": 88, "resp_rate": 16, "temp_c": 37.8, "spo2": 95},
    "self_reported_pain": 0,
    "note": "GERIATRIC — normal-looking vitals mask sepsis/delirium risk; pain score is unreliable in this population"
  },
  {
    "patient_id": "P005", "age_years": 34, "has_prior_history": true,
    "chief_complaint": "sprained ankle",
    "vitals": {"heart_rate": 76, "resp_rate": 14, "temp_c": 36.8, "spo2": 99},
    "self_reported_pain": 3,
    "note": "SURGE FILLER — low-acuity case used to populate queue during 3x volume simulation"
  }
]
```

---

## 5. Multi-Agent Engine (LangGraph)

### State Schema

```python
from typing import TypedDict

class TriageState(TypedDict):
    patient_input: dict
    extracted_symptoms: list[str]
    activated_nodes: list[str]
    demographic_flags: list[str]
    worst_case_path: list[str]          # from Safety Adversary
    triage_level: int
    confidence: float
    degraded_mode: bool
    reasoning_log: list[dict]
```

### 1. Node Extraction Agent (Groq / Llama 3.1 8B)
System prompt (paraphrased intent): parse free-text chief complaint + vitals into a strict JSON list
of symptom labels that exist in the graph's node vocabulary — no invented nodes. Timeout at 3s → fallback.

### 2. Demographic Specialist Agent — calibration tables

| Vital | Pediatric (<12) | Adult (12–65) | Geriatric (>65) |
|---|---|---|---|
| Heart rate (bpm) | 100–160 (age-scaled) | 60–100 | 60–100 (beta-blocker caveat) |
| Resp rate | 20–40 (age-scaled) | 12–20 | 12–24 |
| Temp (fever threshold) | ≥38.0°C is significant | ≥38.0°C | ≥37.8°C **or hypothermia <36°C** is significant (blunted febrile response) |
| SpO2 | <95% concerning | <94% concerning | <92% concerning (baseline COPD adjustment) |

*(State clearly in your deck: these are illustrative reference ranges, not a substitute for a real
clinical protocol — you're not expected to have validated pediatric/geriatric clinical data.)*

### 3. Safety Adversary Agent
Runs `networkx.shortest_path` from each activated symptom node to every "critical" terminal node
(MI, sepsis, stroke, etc.), and if a path of length ≤2 exists, it forces that differential into
consideration regardless of what the Extraction Agent scored as most likely. This is the mechanism
that directly answers "bias toward escalation under uncertainty."

### 4. Synthesizer Agent (Gemini Flash) — decision logic

```python
def synthesize(demographic_flags, worst_case_path, base_confidence):
    triage_level = compute_base_level(demographic_flags, worst_case_path)
    confidence = base_confidence

    if confidence < 0.70:
        triage_level = max(1, triage_level - 1)   # level 1 = most urgent
        escalated = True
    else:
        escalated = False

    return triage_level, confidence, escalated
```

**Parallelization note:** Demographic Specialist and Safety Adversary both only need
`extracted_symptoms` — run them concurrently with `asyncio.gather`, not sequentially. This removes
one full network round-trip from the critical path per patient.

---

## 6. Dynamic Algorithms

### Synaptic Plasticity (edge weight update on override)

```python
def synaptic_update(graph, source_node, target_node, override_delta, learning_rate=0.15):
    """
    override_delta: +1 if clinician escalated beyond AI's call, -1 if de-escalated, 0 if confirmed.
    Nudges the edge weight toward what actually happened, bounded to [0,1].
    """
    current = graph[source_node][target_node].get("weight", 0.5)
    new_weight = min(1.0, max(0.0, current + learning_rate * override_delta))
    graph[source_node][target_node]["weight"] = new_weight
    return current, new_weight   # log both for synaptic_weight_history
```

### Queue Decay + Vitals-Triggered Re-Triage (NumPy — replaces the C++ module)

```python
import numpy as np

def recompute_queue(base_scores: np.ndarray, wait_seconds: np.ndarray,
                     decay_lambda: float = 0.0006) -> np.ndarray:
    """S_dynamic = S_base * e^(lambda * t) — vectorized across the whole queue at once."""
    return base_scores * np.exp(decay_lambda * wait_seconds)

def check_vitals_re_triage(patient_id: str, current_vitals: dict, prior_vitals: dict,
                            age_band: str) -> bool:
    """
    Returns True if a re-assessment should fire NOW, independent of wait-time decay.
    This is the requirement the original plan was missing.
    """
    hr_delta = current_vitals["heart_rate"] - prior_vitals["heart_rate"]
    spo2_delta = current_vitals["spo2"] - prior_vitals["spo2"]
    thresholds = {"pediatric": (20, -3), "adult": (25, -4), "geriatric": (15, -3)}
    hr_thresh, spo2_thresh = thresholds[age_band]
    return hr_delta >= hr_thresh or spo2_delta <= spo2_thresh
```

Both wait-time decay AND vitals-delta checks should run on every polling tick — a patient can become
urgent from either cause, and the brief explicitly calls out both.

---

## 7. Frontend Spec

**Palette:** background `#0a1f1c`, panel `#0f2b26`, mint accent `#10b981`, critical red `#ef4444`,
amber (degraded mode) `#f59e0b`, text `#e6f4f1`.

- `PatientCard.tsx` — triage level badge (color-coded 1–5), horizontal confidence bar (mint fill,
  red under 70%), a small "escalated for uncertainty" pill when applicable.
- `CytoscapeGraph.tsx` — `cose-bilkent` layout, hub nodes larger radius, edges pulse/animate along
  the Safety Adversary's traversed path in sequence (not all at once — sequential reveal reads as
  "reasoning," a static highlighted path reads as decoration).
- `SurgeToggle.tsx` — injects N mock patients over M seconds, visibly re-sorts the queue live as
  `recompute_queue` re-scores.
- `OverrideModal.tsx` — clinician ID, radio select for new level, **required** justification textarea
  (client-side min length, mirrors the DB constraint), submit → fires `synaptic_update`.
- `DegradedModeBanner.tsx` (new) — amber banner + icon, shown whenever any active patient's last
  `triage_logs` row has `degraded_mode = true`.

---

## 8. Build Roadmap (rebalanced — C++ removal buys back ~3 hrs)

| Phase | Hours | Deliverable |
|---|---|---|
| 1 | 0–3 | NetworkX graph (50 nodes), SQLite schema + WAL, FastAPI skeleton, Pydantic models |
| 2 | 3–9 | LangGraph 4-agent flow, prompts, parallel exec, fallback wrapper, NumPy queue math |
| 3 | 9–14 | Next.js HUD, Cytoscape render + animated path reveal, WebSocket queue feed |
| 4 | 14–18 | 20-patient mock dataset, surge simulation tuning, vitals-re-triage wiring, override→synaptic loop end-to-end |
| 5 | 18–20 | Demo script rehearsal, deliberately trigger the fallback path once on camera, deck polish |

---

## 9. Edge-Case & Failure Mode Matrix

| Failure | Trigger | Fail-safe |
|---|---|---|
| Groq/Gemini rate limit or timeout | Surge burst of concurrent calls | Deterministic rule-based scorer + `degraded_mode` banner |
| Missing vitals field | Zero-history / partial intake | Treat as elevated uncertainty, not as "normal" default — never silently impute a healthy value |
| Symptom not in graph vocabulary | Free-text extraction drifts | Extraction Agent constrained to a closed label set; unmapped text logged, not discarded |
| Graph traversal finds no path to any critical node | Truly benign presentation | Fine — this is the expected negative case, log it as such |
| Two overrides conflict on same patient in quick succession | Shift handoff | Last-write-wins on `triage_level`, but both rows persist in `clinician_overrides` — nothing is overwritten in the audit table |
| WebSocket disconnect mid-surge | Network hiccup during demo | Frontend polls REST every 5s as a silent backup while reconnecting |

---

## 10. Pitch & Demo Script (5 slides, 3 minutes)

1. **Problem** — under-triage is catastrophic, over-triage wastes capacity; existing tools use one
   adult-calibrated score for everyone.
2. **Architecture** — one animated graphic: symptom graph + 4 agents, 15 seconds, plain language
   (see the 60-second explanation from the prior review).
3. **Live demo, ambiguous case (P001)** — show the Safety Adversary override a low pain-score toward
   MI rule-out. This is your "aha" moment.
4. **Live demo, surge + vitals re-triage** — trigger surge toggle, then manually worsen one waiting
   patient's vitals and show it jump the queue *before* its wait-decay would have.
5. **Live demo, fallback + override** — deliberately throttle the API key on stage, show the amber
   degraded-mode banner and rule-based scoring take over without crashing; then override a result and
   show the justification field write to the audit table and the graph edge weight shift in real time.

Ending on "watch it fail safely" is a stronger closer than ending on the graph animation — it's the
one moment that proves you designed for the worst case, not just the demo case.
> judge-visible benefit at this scale — replaced with vectorized NumPy that implements the identical
> decay formula). Added a mandatory deterministic fallback path for API rate-limit failure. Added
> vitals-triggered re-assessment (was missing — explicitly required by the brief). Added concrete
> compliance fields to the override log. Rebalanced the build roadmap accordingly.

---

## 1. System Architecture & Data Topography

```
┌─────────────────────────────────────────────────────────────────────┐
│  FRONTEND — Next.js 14 (App Router)                                  │
│  ┌───────────────────────┐   ┌──────────────────────────────────┐   │
│  │ Left: Clinical HUD     │   │ Right: Cytoscape.js Reasoning     │   │
│  │ - Live queue           │   │ Graph (animated agent traversal)  │   │
│  │ - Vitals + conf. bar   │   │                                    │   │
│  │ - Escalation badges    │   │                                    │   │
│  └───────────┬────────────┘   └────────────────┬───────────────────┘   │
│              │  WebSocket (live queue/vitals)   │ HTTP GET (graph)     │
└──────────────┼───────────────────────────────────┼──────────────────┘
               ▼                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  BACKEND — FastAPI (Python 3.11, async)                              │
│                                                                        │
│  POST /triage/intake ─────► LangGraph Multi-Agent Engine             │
│                                │                                      │
│                                ▼                                      │
│                     ┌─────────────────────┐                          │
│                     │ 1. Node Extraction   │ (Groq / Llama 3.1 8B)   │
│                     │ 2. Demographic Spec. │ ─┐ run in parallel      │
│                     │ 3. Safety Adversary  │ ─┘ (both need only      │
│                     │ 4. Synthesizer       │    extracted symptoms)  │
│                     └──────────┬───────────┘ (Gemini Flash)          │
│                                │                                      │
│                                ▼                                      │
│                     NetworkX Scale-Free Symptom Graph                │
│                     (50 nodes: symptom hubs → condition endpoints)   │
│                                │                                      │
│                     ┌──────────┴───────────┐                         │
│                     ▼                       ▼                         │
│           SQLite (WAL mode)         Queue Decay Engine (NumPy)       │
│           - patients                - vectorized S = S₀·e^(λt)      │
│           - triage_logs             - vitals-delta re-triage check   │
│           - clinician_overrides                                      │
│           - synaptic_weight_history                                  │
└─────────────────────────────────────────────────────────────────────┘
```

**Protocol split:** REST/JSON for intake, overrides, and graph fetch (stateless, cacheable). WebSocket
only for the queue panel — wait times and vitals need push updates; nothing else does. Don't put the
whole app on WebSockets, it complicates the demo for no reason.

**Fallback path (new):** every agent call goes through a wrapper that, on timeout or rate-limit
(HTTP 429), falls back to a deterministic rule-based ESI-style scorer and sets `degraded_mode: true`
on the response. The frontend renders a visible amber banner: *"AI reasoning unavailable — rule-based
fail-safe active."* This is not a bug to hide; script it into the demo (see Section 10).

---

## 2. Tech Stack & Dependency Matrix

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS | Fast to build, judge-familiar |
| Graph viz | Cytoscape.js + cytoscape-cose-bilkent (layout) | Handles 50-node animated graphs cleanly |
| Icons | lucide-react | Consistent, lightweight |
| Backend | FastAPI + Uvicorn, Python 3.11 | Async, typed, fast to stand up |
| Graph engine | NetworkX 3.x | Pure Python, no build step |
| Queue math | **NumPy** (replaces C++/Pybind11) | Same formula, zero build risk |
| Orchestration | LangGraph + langchain-core | Native multi-agent state graph |
| LLM (fast extraction) | Groq API — Llama 3.1 8B Instant | Sub-300ms symptom extraction |
| LLM (synthesis) | Google Generative AI SDK — Gemini 1.5/2.0 Flash | Cheap, fast, good at structured output |
| DB | SQLite3, WAL mode | Zero-ops, still durable for audit needs |
| Logging | structlog | Structured logs double as a debugging aid during the demo |
| Validation | Pydantic v2 | Type-safe contracts across every API boundary |

**Install:**
```bash
# backend
pip install fastapi uvicorn[standard] networkx pydantic groq google-generativeai \
            langgraph langchain-core numpy structlog python-dotenv aiosqlite

# frontend
npm install next react react-dom cytoscape cytoscape-cose-bilkent \
            lucide-react tailwindcss
```

No `setup.py`, no CMake, no compiler toolchain dependency. This alone removes the single biggest
cross-machine failure risk in the original plan.

---

## 3. File Directory

```
patient-triage-ai/
├── backend/
│   ├── app/
│   │   ├── main.py                      # FastAPI app, routes, WS endpoint
│   │   ├── graph/
│   │   │   ├── symptom_graph.py         # NetworkX graph build + synaptic_update()
│   │   │   └── agents.py                # LangGraph flow: 4 agent nodes + fallback wrapper
│   │   ├── core/
│   │   │   ├── queue_decay.py           # NumPy vectorized decay + vitals-delta re-triage
│   │   │   └── config.py                # env vars, API keys, thresholds
│   │   ├── db/
│   │   │   ├── database.py              # SQLite init, WAL pragma, connection pool
│   │   │   └── models.py                # Pydantic schemas
│   │   └── mock_data/
│   │       └── simulated_patients.json  # 20 patient records
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── app/page.tsx                 # Split-screen HUD shell
│   │   ├── components/
│   │   │   ├── CytoscapeGraph.tsx
│   │   │   ├── PatientCard.tsx
│   │   │   ├── SurgeToggle.tsx
│   │   │   ├── OverrideModal.tsx
│   │   │   └── DegradedModeBanner.tsx   # NEW — renders fallback state
│   │   └── lib/api.ts                   # typed fetch/WS client
│   └── package.json
└── README.md
```

---

## 4. Database Schema, Data Models & Mock Data

### SQLite Schema (audit-first design)

```sql
PRAGMA journal_mode=WAL;

CREATE TABLE patients (
    patient_id TEXT PRIMARY KEY,
    age_years INTEGER NOT NULL,
    age_band TEXT CHECK(age_band IN ('pediatric','adult','geriatric')) NOT NULL,
    has_prior_history BOOLEAN NOT NULL,
    arrival_ts TEXT NOT NULL,
    chief_complaint TEXT NOT NULL,
    consent_flag BOOLEAN NOT NULL DEFAULT 1     -- required under most health-data regs
);

CREATE TABLE triage_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL REFERENCES patients(patient_id),
    ts TEXT NOT NULL,
    triage_level INTEGER CHECK(triage_level BETWEEN 1 AND 5),
    confidence REAL NOT NULL,
    escalated_for_uncertainty BOOLEAN NOT NULL DEFAULT 0,
    reasoning_path TEXT NOT NULL,               -- JSON: node-by-node graph path
    degraded_mode BOOLEAN NOT NULL DEFAULT 0,   -- true if fallback scorer was used
    trigger_reason TEXT NOT NULL DEFAULT 'intake'  -- 'intake' | 'wait_decay' | 'vitals_change'
);

CREATE TABLE clinician_overrides (
    override_id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL REFERENCES patients(patient_id),
    clinician_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    ai_recommended_level INTEGER NOT NULL,
    ai_confidence REAL NOT NULL,
    overridden_level INTEGER NOT NULL,
    justification TEXT NOT NULL,                -- mandatory free-text, not optional
    jurisdiction TEXT NOT NULL DEFAULT 'HIPAA'   -- state your regime explicitly
);

CREATE TABLE synaptic_weight_history (
    update_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_node TEXT NOT NULL,
    target_node TEXT NOT NULL,
    old_weight REAL NOT NULL,
    new_weight REAL NOT NULL,
    triggered_by_override_id INTEGER REFERENCES clinician_overrides(override_id),
    ts TEXT NOT NULL
);
```

`clinician_overrides.justification` is `NOT NULL` on purpose — a compliance-grade override record
needs a reason, not just a new number. This single field is what makes "auditability" a real claim
instead of a bullet point.

### Pydantic Models (`db/models.py`)

```python
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime

class Vitals(BaseModel):
    heart_rate: int
    resp_rate: int
    temp_c: float
    spo2: int
    systolic_bp: int | None = None

class PatientInput(BaseModel):
    patient_id: str
    age_years: int
    has_prior_history: bool
    chief_complaint: str
    vitals: Vitals
    self_reported_pain: int = Field(ge=0, le=10)

class AgentReasoningPath(BaseModel):
    agent_name: str
    graph_nodes_visited: list[str]
    conclusion: str
    confidence_delta: float

class TriageResult(BaseModel):
    patient_id: str
    triage_level: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0, le=1)
    escalated_for_uncertainty: bool
    degraded_mode: bool
    reasoning_path: list[AgentReasoningPath]
    trigger_reason: Literal["intake", "wait_decay", "vitals_change"]

class OverridePayload(BaseModel):
    patient_id: str
    clinician_id: str
    overridden_level: int = Field(ge=1, le=5)
    justification: str = Field(min_length=10)   # force a real reason, not "n/a"
```

### Sample Records (5 of the 20 required)

```json
[
  {
    "patient_id": "P001", "age_years": 45, "has_prior_history": true,
    "chief_complaint": "vague epigastric pain, mild nausea, radiating to jaw",
    "vitals": {"heart_rate": 98, "resp_rate": 18, "temp_c": 37.1, "spo2": 97, "systolic_bp": 132},
    "self_reported_pain": 4,
    "note": "AMBIGUOUS — should trigger Safety Adversary to rule out atypical MI despite low pain score"
  },
  {
    "patient_id": "P002", "age_years": 3, "has_prior_history": false,
    "chief_complaint": "fever, lethargy, poor feeding",
    "vitals": {"heart_rate": 168, "resp_rate": 42, "temp_c": 38.6, "spo2": 94},
    "self_reported_pain": null,
    "note": "PEDIATRIC — adult-calibrated thresholds would under-triage this; HR/RR are age-abnormal, not absolute-abnormal"
  },
  {
    "patient_id": "P003", "age_years": 29, "has_prior_history": false,
    "chief_complaint": "MVC, visible arm deformity, no LOC reported",
    "vitals": {"heart_rate": 110, "resp_rate": 20, "temp_c": 36.9, "spo2": 98},
    "self_reported_pain": 8,
    "note": "ZERO-HISTORY trauma — no prior record; epistemic uncertainty should be explicitly elevated"
  },
  {
    "patient_id": "P004", "age_years": 78, "has_prior_history": true,
    "chief_complaint": "new confusion, family reports 'not himself since this morning'",
    "vitals": {"heart_rate": 88, "resp_rate": 16, "temp_c": 37.8, "spo2": 95},
    "self_reported_pain": 0,
    "note": "GERIATRIC — normal-looking vitals mask sepsis/delirium risk; pain score is unreliable in this population"
  },
  {
    "patient_id": "P005", "age_years": 34, "has_prior_history": true,
    "chief_complaint": "sprained ankle",
    "vitals": {"heart_rate": 76, "resp_rate": 14, "temp_c": 36.8, "spo2": 99},
    "self_reported_pain": 3,
    "note": "SURGE FILLER — low-acuity case used to populate queue during 3x volume simulation"
  }
]
```

---

## 5. Multi-Agent Engine (LangGraph)

### State Schema

```python
from typing import TypedDict

class TriageState(TypedDict):
    patient_input: dict
    extracted_symptoms: list[str]
    activated_nodes: list[str]
    demographic_flags: list[str]
    worst_case_path: list[str]          # from Safety Adversary
    triage_level: int
    confidence: float
    degraded_mode: bool
    reasoning_log: list[dict]
```

### 1. Node Extraction Agent (Groq / Llama 3.1 8B)
System prompt (paraphrased intent): parse free-text chief complaint + vitals into a strict JSON list
of symptom labels that exist in the graph's node vocabulary — no invented nodes. Timeout at 3s → fallback.

### 2. Demographic Specialist Agent — calibration tables

| Vital | Pediatric (<12) | Adult (12–65) | Geriatric (>65) |
|---|---|---|---|
| Heart rate (bpm) | 100–160 (age-scaled) | 60–100 | 60–100 (beta-blocker caveat) |
| Resp rate | 20–40 (age-scaled) | 12–20 | 12–24 |
| Temp (fever threshold) | ≥38.0°C is significant | ≥38.0°C | ≥37.8°C **or hypothermia <36°C** is significant (blunted febrile response) |
| SpO2 | <95% concerning | <94% concerning | <92% concerning (baseline COPD adjustment) |

*(State clearly in your deck: these are illustrative reference ranges, not a substitute for a real
clinical protocol — you're not expected to have validated pediatric/geriatric clinical data.)*

### 3. Safety Adversary Agent
Runs `networkx.shortest_path` from each activated symptom node to every "critical" terminal node
(MI, sepsis, stroke, etc.), and if a path of length ≤2 exists, it forces that differential into
consideration regardless of what the Extraction Agent scored as most likely. This is the mechanism
that directly answers "bias toward escalation under uncertainty."

### 4. Synthesizer Agent (Gemini Flash) — decision logic

```python
def synthesize(demographic_flags, worst_case_path, base_confidence):
    triage_level = compute_base_level(demographic_flags, worst_case_path)
    confidence = base_confidence

    if confidence < 0.70:
        triage_level = max(1, triage_level - 1)   # level 1 = most urgent
        escalated = True
    else:
        escalated = False

    return triage_level, confidence, escalated
```

**Parallelization note:** Demographic Specialist and Safety Adversary both only need
`extracted_symptoms` — run them concurrently with `asyncio.gather`, not sequentially. This removes
one full network round-trip from the critical path per patient.

---

## 6. Dynamic Algorithms

### Synaptic Plasticity (edge weight update on override)

```python
def synaptic_update(graph, source_node, target_node, override_delta, learning_rate=0.15):
    """
    override_delta: +1 if clinician escalated beyond AI's call, -1 if de-escalated, 0 if confirmed.
    Nudges the edge weight toward what actually happened, bounded to [0,1].
    """
    current = graph[source_node][target_node].get("weight", 0.5)
    new_weight = min(1.0, max(0.0, current + learning_rate * override_delta))
    graph[source_node][target_node]["weight"] = new_weight
    return current, new_weight   # log both for synaptic_weight_history
```

### Queue Decay + Vitals-Triggered Re-Triage (NumPy — replaces the C++ module)

```python
import numpy as np

def recompute_queue(base_scores: np.ndarray, wait_seconds: np.ndarray,
                     decay_lambda: float = 0.0006) -> np.ndarray:
    """S_dynamic = S_base * e^(lambda * t) — vectorized across the whole queue at once."""
    return base_scores * np.exp(decay_lambda * wait_seconds)

def check_vitals_re_triage(patient_id: str, current_vitals: dict, prior_vitals: dict,
                            age_band: str) -> bool:
    """
    Returns True if a re-assessment should fire NOW, independent of wait-time decay.
    This is the requirement the original plan was missing.
    """
    hr_delta = current_vitals["heart_rate"] - prior_vitals["heart_rate"]
    spo2_delta = current_vitals["spo2"] - prior_vitals["spo2"]
    thresholds = {"pediatric": (20, -3), "adult": (25, -4), "geriatric": (15, -3)}
    hr_thresh, spo2_thresh = thresholds[age_band]
    return hr_delta >= hr_thresh or spo2_delta <= spo2_thresh
```

Both wait-time decay AND vitals-delta checks should run on every polling tick — a patient can become
urgent from either cause, and the brief explicitly calls out both.

---

## 7. Frontend Spec

**Palette:** background `#0a1f1c`, panel `#0f2b26`, mint accent `#10b981`, critical red `#ef4444`,
amber (degraded mode) `#f59e0b`, text `#e6f4f1`.

- `PatientCard.tsx` — triage level badge (color-coded 1–5), horizontal confidence bar (mint fill,
  red under 70%), a small "escalated for uncertainty" pill when applicable.
- `CytoscapeGraph.tsx` — `cose-bilkent` layout, hub nodes larger radius, edges pulse/animate along
  the Safety Adversary's traversed path in sequence (not all at once — sequential reveal reads as
  "reasoning," a static highlighted path reads as decoration).
- `SurgeToggle.tsx` — injects N mock patients over M seconds, visibly re-sorts the queue live as
  `recompute_queue` re-scores.
- `OverrideModal.tsx` — clinician ID, radio select for new level, **required** justification textarea
  (client-side min length, mirrors the DB constraint), submit → fires `synaptic_update`.
- `DegradedModeBanner.tsx` (new) — amber banner + icon, shown whenever any active patient's last
  `triage_logs` row has `degraded_mode = true`.

---

## 8. Build Roadmap (rebalanced — C++ removal buys back ~3 hrs)

| Phase | Hours | Deliverable |
|---|---|---|
| 1 | 0–3 | NetworkX graph (50 nodes), SQLite schema + WAL, FastAPI skeleton, Pydantic models |
| 2 | 3–9 | LangGraph 4-agent flow, prompts, parallel exec, fallback wrapper, NumPy queue math |
| 3 | 9–14 | Next.js HUD, Cytoscape render + animated path reveal, WebSocket queue feed |
| 4 | 14–18 | 20-patient mock dataset, surge simulation tuning, vitals-re-triage wiring, override→synaptic loop end-to-end |
| 5 | 18–20 | Demo script rehearsal, deliberately trigger the fallback path once on camera, deck polish |

---

## 9. Edge-Case & Failure Mode Matrix

| Failure | Trigger | Fail-safe |
|---|---|---|
| Groq/Gemini rate limit or timeout | Surge burst of concurrent calls | Deterministic rule-based scorer + `degraded_mode` banner |
| Missing vitals field | Zero-history / partial intake | Treat as elevated uncertainty, not as "normal" default — never silently impute a healthy value |
| Symptom not in graph vocabulary | Free-text extraction drifts | Extraction Agent constrained to a closed label set; unmapped text logged, not discarded |
| Graph traversal finds no path to any critical node | Truly benign presentation | Fine — this is the expected negative case, log it as such |
| Two overrides conflict on same patient in quick succession | Shift handoff | Last-write-wins on `triage_level`, but both rows persist in `clinician_overrides` — nothing is overwritten in the audit table |
| WebSocket disconnect mid-surge | Network hiccup during demo | Frontend polls REST every 5s as a silent backup while reconnecting |

---

## 10. Pitch & Demo Script (5 slides, 3 minutes)

1. **Problem** — under-triage is catastrophic, over-triage wastes capacity; existing tools use one
   adult-calibrated score for everyone.
2. **Architecture** — one animated graphic: symptom graph + 4 agents, 15 seconds, plain language
   (see the 60-second explanation from the prior review).
3. **Live demo, ambiguous case (P001)** — show the Safety Adversary override a low pain-score toward
   MI rule-out. This is your "aha" moment.
4. **Live demo, surge + vitals re-triage** — trigger surge toggle, then manually worsen one waiting
   patient's vitals and show it jump the queue *before* its wait-decay would have.
5. **Live demo, fallback + override** — deliberately throttle the API key on stage, show the amber
   degraded-mode banner and rule-based scoring take over without crashing; then override a result and
   show the justification field write to the audit table and the graph edge weight shift in real time.

Ending on "watch it fail safely" is a stronger closer than ending on the graph animation — it's the
one moment that proves you designed for the worst case, not just the demo case.
