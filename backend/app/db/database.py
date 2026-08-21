from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / 'patient_triage.db'

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS patients (patient_id TEXT PRIMARY KEY, age_years INTEGER NOT NULL, age_band TEXT NOT NULL, has_prior_history BOOLEAN NOT NULL, arrival_ts TEXT NOT NULL, chief_complaint TEXT NOT NULL, consent_flag BOOLEAN NOT NULL DEFAULT 1, vitals_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS encounters (encounter_id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'waiting' CHECK(status IN ('waiting','triaged','in_treatment','discharged','cancelled')), arrival_ts TEXT NOT NULL, source_dataset TEXT NOT NULL DEFAULT 'simulated_patients_v1', surge_batch_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS triage_logs (log_id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT NOT NULL, ts TEXT NOT NULL, triage_level INTEGER NOT NULL, confidence REAL NOT NULL, escalated_for_uncertainty BOOLEAN NOT NULL, reasoning_path TEXT NOT NULL, degraded_mode BOOLEAN NOT NULL DEFAULT 0, trigger_reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS clinician_overrides (override_id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT NOT NULL, clinician_id TEXT NOT NULL, ts TEXT NOT NULL, ai_recommended_level INTEGER NOT NULL, ai_confidence REAL NOT NULL, overridden_level INTEGER NOT NULL, justification TEXT NOT NULL, jurisdiction TEXT NOT NULL DEFAULT 'HIPAA');
CREATE TABLE IF NOT EXISTS synaptic_weight_history (update_id INTEGER PRIMARY KEY AUTOINCREMENT, source_node TEXT NOT NULL, target_node TEXT NOT NULL, old_weight REAL NOT NULL, new_weight REAL NOT NULL, triggered_by_override_id INTEGER, ts TEXT NOT NULL);
'''


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def age_band(age: int) -> str:
    return 'pediatric' if age < 12 else 'geriatric' if age > 65 else 'adult'


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialise() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def upsert_patient(payload: dict) -> None:
    with connect() as conn:
        timestamp = payload.get('arrival_ts', now())
        conn.execute('''INSERT INTO patients(patient_id,age_years,age_band,has_prior_history,arrival_ts,chief_complaint,consent_flag,vitals_json)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(patient_id) DO UPDATE SET age_years=excluded.age_years,age_band=excluded.age_band,has_prior_history=excluded.has_prior_history,chief_complaint=excluded.chief_complaint,vitals_json=excluded.vitals_json''',
            (payload['patient_id'], payload['age_years'], age_band(payload['age_years']), payload['has_prior_history'], timestamp, payload['chief_complaint'], True, json.dumps(payload['vitals'])))
        conn.execute('''INSERT INTO encounters(encounter_id,patient_id,status,arrival_ts,source_dataset,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(encounter_id) DO NOTHING''',
            (payload['patient_id'], payload['patient_id'], 'waiting', timestamp, 'simulated_patients_v1', timestamp, now()))


def log_triage(result: dict) -> None:
    with connect() as conn:
        conn.execute('INSERT INTO triage_logs(patient_id,ts,triage_level,confidence,escalated_for_uncertainty,reasoning_path,degraded_mode,trigger_reason) VALUES(?,?,?,?,?,?,?,?)',
            (result['patient_id'], result['updated_at'], result['triage_level'], result['confidence'], result['escalated_for_uncertainty'], json.dumps(result['reasoning_path']), result['degraded_mode'], result['trigger_reason']))


def latest_triage(patient_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute('SELECT * FROM triage_logs WHERE patient_id=? ORDER BY log_id DESC LIMIT 1', (patient_id,)).fetchone()
        return dict(row) if row else None


def queue_rows() -> list[dict]:
    with connect() as conn:
        rows = conn.execute('''SELECT p.*, t.triage_level,t.confidence,t.escalated_for_uncertainty,t.degraded_mode,t.trigger_reason,t.reasoning_path
            FROM patients p JOIN encounters e ON e.patient_id=p.patient_id AND e.status IN ('waiting','triaged')
            JOIN triage_logs t ON t.log_id=(SELECT log_id FROM triage_logs WHERE patient_id=p.patient_id ORDER BY log_id DESC LIMIT 1)''').fetchall()
        return [dict(row) for row in rows]


def delete_patients(patient_ids: list[str]) -> None:
    if not patient_ids:
        return
    with connect() as conn:
        placeholders = ','.join('?' for _ in patient_ids)
        conn.execute(f'DELETE FROM triage_logs WHERE patient_id IN ({placeholders})', patient_ids)
        conn.execute(f'DELETE FROM encounters WHERE patient_id IN ({placeholders})', patient_ids)
        conn.execute(f'DELETE FROM patients WHERE patient_id IN ({placeholders})', patient_ids)


def get_patient(patient_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute('SELECT * FROM patients WHERE patient_id=?', (patient_id,)).fetchone()
        return dict(row) if row else None


def record_override(patient_id: str, clinician_id: str, ai_level: int, confidence: float, new_level: int, justification: str, jurisdiction: str) -> int:
    with connect() as conn:
        cur = conn.execute('INSERT INTO clinician_overrides(patient_id,clinician_id,ts,ai_recommended_level,ai_confidence,overridden_level,justification,jurisdiction) VALUES(?,?,?,?,?,?,?,?)',
            (patient_id, clinician_id, now(), ai_level, confidence, new_level, justification, jurisdiction))
        return cur.lastrowid


def record_weight(source: str, target: str, old: float, new: float, override_id: int) -> None:
    with connect() as conn:
        conn.execute('INSERT INTO synaptic_weight_history(source_node,target_node,old_weight,new_weight,triggered_by_override_id,ts) VALUES(?,?,?,?,?,?)', (source, target, old, new, override_id, now()))
