# PatientTriage.ai

A safety-first emergency department triage prototype for the Accenture Innovation Challenge. It is a clinical decision-support demo only, not a diagnostic device or clinical protocol.

## Run locally

Open two terminals from this folder:# ROLE & TASK
Act as a Principal Healthcare Systems Architect, Lead AI/ML Engineer, and Accenture Hackathon Winner. 

Generate an end-to-end, production-grade **Project Master Plan & System Specification Document** for building **"PatientTriage.ai"**—a state-of-the-art emergency department (ED) triage system powered by a **Neuro-Symbolic Agent Graph**.

The output must be deeply technical, complete, and actionable down to exact code signatures, schemas, file structures, and UI layout grids. Avoid hand-waving or high-level summaries.

---

## CONTEXT & OBJECTIVES
* **Competition Context:** Accenture Innovation Challenge 2026 - Round 2 Prototype Development.
* **Core Problem:** Standard triage tools fail under real-world Emergency Department pressures due to ambiguous symptom presentations, severe age-based vital sign variations (pediatric vs. geriatric), asymmetric cost (under-triage is catastrophic), waiting room deterioration, and clinician alert fatigue.
* **Core Solution Architecture:** A Neuro-Symbolic Agent Graph. The system translates medical knowledge into a scale-free graph using NetworkX (symptoms as hubs, conditions as terminal nodes). A multi-agent system powered by LangGraph, Groq (Llama 3.1 8B), and Google Gemini Flash traverses this graph to evaluate patients, explicitly surfaces uncertainty, supports instant clinician overrides with dynamic "synaptic plasticity" learning, and handles $3\times$ volume surges via a C++ queue decay engine.

---

## REQUIRED PLAN SECTIONS

Provide ultra-detailed specs for each of the following 10 sections:

### 1. System Architecture & High-Level Data Topography
* Complete ASCII diagram illustrating the flow from Frontend (Next.js/Cytoscape.js) $\rightarrow$ REST/WebSocket API (FastAPI) $\rightarrow$ LangGraph Multi-Agent Engine $\rightarrow$ NetworkX Scale-Free Graph $\rightarrow$ C++ Core Queue Worker $\rightarrow$ SQLite Audit Store.
* Explicit component responsibilities, data contracts, and protocol definitions (HTTP/JSON vs. WebSockets).

### 2. Definitive Tech Stack & Dependency Matrix
* Complete breakdown of frameworks, versions, and libraries across:
  * **Frontend:** Next.js (App Router), Tailwind CSS, Lucide Icons, Cytoscape.js, Cytoscape-D3-Force.
  * **Backend:** Python 3.11+, FastAPI, Uvicorn, NetworkX, Pybind11, Pydantic v2.
  * **AI Orchestration:** LangGraph, LangChain-Core, Groq API SDK, Google Generative AI SDK.
  * **Database & Caching:** SQLite3 (WAL mode), Structlog.
  * **Build & C++ Toolchain:** CMake / Setup.py, GCC/Clang, Pybind11.
* Direct installation script commands (`pip install`, `npm install`) with exact package lists.

### 3. File Directory & Project Structure
* Full file tree with zero missing directories.
* Purpose and internal functions/classes for *every single file* in the codebase.

### 4. Database Schema, Data Models & Mock Datasets
* **SQLite Schema:** Complete SQL statements for `patients`, `triage_logs`, `clinician_overrides`, and `synaptic_weight_history` tables (ensuring HIPAA/GDPR auditability).
* **Pydantic Data Models:** Python class definitions for `PatientInput`, `Vitals`, `TriageResult`, `AgentReasoningPath`, and `OverridePayload`.
* **Mock Patient Dataset Specs:** Exact JSON schema and 5 detailed sample patient records out of the 20 required (including 1 ambiguous adult presentation, 1 pediatric sepsis case, 1 zero-history trauma case, 1 geriatric confusion case, and 1 surge load case).

### 5. Multi-Agent Engine Architecture (LangGraph Deep-Dive)
* **Agent Graph State Schema:** Exact Python TypedDict representing the `TriageState`.
* **Individual Agent Specs & Prompts:**
  1. *Node Extraction Agent (Groq / Llama 3.1 8B):* System prompt, extraction format, parsing logic.
  2. *Demographic Specialist Agent:* Precise physiological vital threshold tables for Pediatric ($<12$), Adult ($12\text{--}65$), and Geriatric ($>65$).
  3. *Safety Adversary Agent:* Shortest-path search algorithm across the graph to prove worst-case differential diagnoses.
  4. *Synthesizer Agent (Gemini Flash):* Decision logic matrix, epistemic uncertainty formula, and automatic +1 level escalation trigger rules when confidence is $<70\%$.

### 6. Dynamic Algorithms & Algorithmic Mechanics
* **Synaptic Plasticity Formula:** Mathematical specification and Python function for modifying NetworkX edge weights when a clinician overrides an AI output.
* **C++ High-Performance Queue Core:** Complete C++ source code (`queue_decay.cpp`) and Pybind11 binding file (`cpp_bindings.cpp`) calculating wait-time score inflation ($S_{\text{dynamic}} = S_{\text{base}} \times e^{\lambda t}$) during simulated $3\times$ volume surges.

### 7. Frontend UI/UX & Clinical HUD Layout Specs
* **Visual Palette:** HEX codes, Tailwind classes for dark clinical dark-green aesthetic (`#0a1f1c`), mint status badges (`#10b981`), high-risk flags (`#ef4444`), and graph node styles.
* **Component Specs:**
  * `CytoscapeGraph.tsx`: Node styling rules, animated edge traversal logic, layout algorithms.
  * `PatientCard.tsx`: Vitals display layout, confidence bar visualizer, level indicator.
  * `SurgeToggle.tsx`: Trigger mechanism for real-time background queue flooding.
  * `OverrideModal.tsx`: UX flow for logging nurse reasoning and firing synaptic update API calls.

### 8. Phase-by-Phase Build & Implementation Roadmap
* Step-by-step coding plan broken down into 4 discrete phases (designed for a tight hackathon timeline):
  * **Phase 1 (Hours 0-4):** Graph setup, C++ bindings, SQLite schemas, FastAPI foundation.
  * **Phase 2 (Hours 4-10):** LangGraph multi-agent flow, prompt tuning, free API integrations.
  * **Phase 3 (Hours 10-16):** Next.js dashboard, Cytoscape graph rendering, live WebSockets/polling.
  * **Phase 4 (Hours 16-20):** Mock dataset generation (20 cases), surge simulation tuning, pitch polish.

### 9. Edge-Case Validation & Failure Mode Matrix
* Table covering potential technical failure points (API rate limits, missing patient vitals, invalid graph traversals, C++ build failures) and their programmatic fail-safes.

### 10. Pitch Deck Strategy & Live Demo Script
* 3-minute presentation slide breakdown (5 slides max).
* Step-by-step live demo script outlining the exact sequence of clicks, simulated edge cases to showcase to the judges, and verbal talking points that prove technical novelty and clinical safety.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. The frontend expects the API at http://localhost:8000; override this with `NEXT_PUBLIC_API_URL`.

## Demo flow

1. Open P001 to see an ambiguous, low-pain possible cardiac presentation escalated by the safety adversary.
2. Enable surge mode to inject waiting-room patients and watch priority decay re-sort the queue.
3. Select a patient and press **Worsen vitals** to force an immediate vitals-triggered re-triage.
4. Open **Clinician override**, enter a 10+ character rationale, and submit. The audit record and graph learning signal update.
5. Toggle **Fail-safe demo** to make new assessments visibly use deterministic rule-based scoring.

## Design notes

- SQLite runs in WAL mode and stores patient, triage, override, and synaptic-weight audit history.
- The orchestrator uses a deterministic, explainable four-stage neuro-symbolic flow (symptom extraction, demographic calibration, safety adversary, synthesis). It is intentionally offline-ready; an external LLM wrapper can be added without changing the API contract.
- No patient data is sent to a third party by this prototype. The sample data is fictional.
