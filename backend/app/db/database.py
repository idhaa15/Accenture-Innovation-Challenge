from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / 'patient_triage.db'

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS patients (patient_id TEXT PRIMARY KEY, age_years INTEGER NOT NULL, age_band TEXT NOT NULL, has_prior_history BOOLEAN NOT NULL, arrival_ts TEXT NOT NULL, chief_complaint TEXT NOT NULL, patient_name TEXT NOT NULL DEFAULT '', gender TEXT NOT NULL DEFAULT 'Not specified', pronouns TEXT NOT NULL DEFAULT '', preferred_language TEXT NOT NULL DEFAULT 'English', self_reported_pain INTEGER, consent_flag BOOLEAN NOT NULL DEFAULT 1, vitals_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS encounters (encounter_id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'waiting' CHECK(status IN ('waiting','triaged','in_treatment','discharged','cancelled')), arrival_ts TEXT NOT NULL, source_dataset TEXT NOT NULL DEFAULT 'simulated_patients_v1', surge_batch_id TEXT, reassessment_interval_seconds INTEGER NOT NULL DEFAULT 300, last_reassessment_at TEXT, next_reassessment_at TEXT, reassessment_due BOOLEAN NOT NULL DEFAULT 0, deteriorating BOOLEAN NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS triage_logs (log_id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT NOT NULL, ts TEXT NOT NULL, triage_level INTEGER NOT NULL, confidence REAL NOT NULL, escalated_for_uncertainty BOOLEAN NOT NULL, reasoning_path TEXT NOT NULL, degraded_mode BOOLEAN NOT NULL DEFAULT 0, trigger_reason TEXT NOT NULL, explanation_json TEXT NOT NULL DEFAULT '{}', recommended_department TEXT NOT NULL DEFAULT 'General ED', routing_confidence TEXT NOT NULL DEFAULT 'heuristic', data_quality_json TEXT NOT NULL DEFAULT '{}', llm_response_json TEXT NOT NULL DEFAULT '{}', disclaimer TEXT NOT NULL DEFAULT 'Decision support only. Not a validated diagnostic device. Graph-based reasoning is a heuristic, not a licensed clinical protocol.');
CREATE TABLE IF NOT EXISTS clinician_overrides (override_id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT NOT NULL, clinician_id TEXT NOT NULL, ts TEXT NOT NULL, ai_recommended_level INTEGER NOT NULL, ai_confidence REAL NOT NULL, overridden_level INTEGER NOT NULL, justification TEXT NOT NULL, jurisdiction TEXT NOT NULL DEFAULT 'HIPAA');
CREATE TABLE IF NOT EXISTS synaptic_weight_history (update_id INTEGER PRIMARY KEY AUTOINCREMENT, source_node TEXT NOT NULL, target_node TEXT NOT NULL, old_weight REAL NOT NULL, new_weight REAL NOT NULL, triggered_by_override_id INTEGER, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS encounter_actions (action_id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT NOT NULL, actor TEXT NOT NULL, action_type TEXT NOT NULL, details_json TEXT NOT NULL, ts TEXT NOT NULL);
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
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(triage_logs)')}
        additions = {
            'explanation_json': "TEXT NOT NULL DEFAULT '{}'",
            'recommended_department': "TEXT NOT NULL DEFAULT 'General ED'",
            'routing_confidence': "TEXT NOT NULL DEFAULT 'heuristic'",
            'data_quality_json': "TEXT NOT NULL DEFAULT '{}'",
            'llm_response_json': "TEXT NOT NULL DEFAULT '{}'",
            'disclaimer': "TEXT NOT NULL DEFAULT 'Decision support only. Not a validated diagnostic device. Graph-based reasoning is a heuristic, not a licensed clinical protocol.'",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f'ALTER TABLE triage_logs ADD COLUMN {name} {definition}')
        patient_columns = {row['name'] for row in conn.execute('PRAGMA table_info(patients)')}
        if 'patient_name' not in patient_columns:
            conn.execute("ALTER TABLE patients ADD COLUMN patient_name TEXT NOT NULL DEFAULT ''")
        for name, definition in {'gender': "TEXT NOT NULL DEFAULT 'Not specified'", 'pronouns': "TEXT NOT NULL DEFAULT ''", 'preferred_language': "TEXT NOT NULL DEFAULT 'English'", 'self_reported_pain': 'INTEGER'}.items():
            if name not in patient_columns:
                conn.execute(f'ALTER TABLE patients ADD COLUMN {name} {definition}')
        encounter_columns = {row['name'] for row in conn.execute('PRAGMA table_info(encounters)')}
        additions = {
            'reassessment_interval_seconds': 'INTEGER NOT NULL DEFAULT 300',
            'last_reassessment_at': 'TEXT',
            'next_reassessment_at': 'TEXT',
            'reassessment_due': 'BOOLEAN NOT NULL DEFAULT 0',
            'deteriorating': 'BOOLEAN NOT NULL DEFAULT 0',
        }
        for name, definition in additions.items():
            if name not in encounter_columns:
                conn.execute(f'ALTER TABLE encounters ADD COLUMN {name} {definition}')
        conn.execute("UPDATE encounters SET next_reassessment_at=COALESCE(next_reassessment_at, datetime(arrival_ts, '+5 minutes'))")


def upsert_patient(payload: dict) -> None:
    with connect() as conn:
        timestamp = payload.get('arrival_ts', now())
        conn.execute('''INSERT INTO patients(patient_id,age_years,age_band,has_prior_history,arrival_ts,chief_complaint,patient_name,gender,pronouns,preferred_language,self_reported_pain,consent_flag,vitals_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(patient_id) DO UPDATE SET age_years=excluded.age_years,age_band=excluded.age_band,has_prior_history=excluded.has_prior_history,chief_complaint=excluded.chief_complaint,patient_name=excluded.patient_name,gender=excluded.gender,pronouns=excluded.pronouns,preferred_language=excluded.preferred_language,self_reported_pain=excluded.self_reported_pain,vitals_json=excluded.vitals_json''',
            (payload['patient_id'], payload['age_years'], age_band(payload['age_years']), payload['has_prior_history'], timestamp, payload['chief_complaint'], payload.get('patient_name', ''), payload.get('gender', 'Not specified'), payload.get('pronouns', ''), payload.get('preferred_language', 'English'), payload.get('self_reported_pain'), True, json.dumps(payload['vitals'])))
        next_check = (datetime.fromisoformat(timestamp) + timedelta(minutes=5)).isoformat()
        conn.execute('''INSERT INTO encounters(encounter_id,patient_id,status,arrival_ts,source_dataset,next_reassessment_at,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(encounter_id) DO NOTHING''',
            (payload['patient_id'], payload['patient_id'], 'waiting', timestamp, 'simulated_patients_v1', next_check, timestamp, now()))


def log_triage(result: dict) -> None:
    with connect() as conn:
        conn.execute('INSERT INTO triage_logs(patient_id,ts,triage_level,confidence,escalated_for_uncertainty,reasoning_path,degraded_mode,trigger_reason,explanation_json,recommended_department,routing_confidence,data_quality_json,llm_response_json,disclaimer) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (result['patient_id'], result['updated_at'], result['triage_level'], result['confidence'], result['escalated_for_uncertainty'], json.dumps(result['reasoning_path']), result['degraded_mode'], result['trigger_reason'], json.dumps(result.get('explanation', {})), result.get('recommended_department', 'General ED'), result.get('routing_confidence', 'heuristic'), json.dumps(result.get('data_quality', {})), json.dumps(result.get('llm_response', {})), result.get('disclaimer', '')))


def latest_triage(patient_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute('SELECT * FROM triage_logs WHERE patient_id=? ORDER BY log_id DESC LIMIT 1', (patient_id,)).fetchone()
        return dict(row) if row else None


def queue_rows() -> list[dict]:
    with connect() as conn:
        rows = conn.execute('''SELECT p.*, e.reassessment_interval_seconds,e.last_reassessment_at,e.next_reassessment_at,e.reassessment_due,e.deteriorating, t.triage_level,t.confidence,t.escalated_for_uncertainty,t.degraded_mode,t.trigger_reason,t.reasoning_path,t.explanation_json,t.recommended_department,t.routing_confidence,t.data_quality_json,t.llm_response_json,t.disclaimer
            FROM patients p JOIN encounters e ON e.patient_id=p.patient_id AND e.status IN ('waiting','triaged')
            JOIN triage_logs t ON t.log_id=(SELECT log_id FROM triage_logs WHERE patient_id=p.patient_id ORDER BY log_id DESC LIMIT 1)''').fetchall()
        return [dict(row) for row in rows]


def refresh_reassessment_due() -> int:
    with connect() as conn:
        cur = conn.execute("""UPDATE encounters
            SET reassessment_due=1, updated_at=?
            WHERE status IN ('waiting','triaged') AND reassessment_due=0
              AND next_reassessment_at IS NOT NULL AND next_reassessment_at <= ?""", (now(), now()))
        return cur.rowcount


def complete_reassessment(patient_id: str, deteriorating: bool) -> None:
    with connect() as conn:
        row = conn.execute('SELECT reassessment_interval_seconds FROM encounters WHERE patient_id=?', (patient_id,)).fetchone()
        if not row:
            return
        timestamp = datetime.now(timezone.utc)
        next_check = timestamp + timedelta(seconds=row['reassessment_interval_seconds'])
        conn.execute('''UPDATE encounters SET last_reassessment_at=?, next_reassessment_at=?, reassessment_due=0,
            deteriorating=?, updated_at=? WHERE patient_id=?''', (timestamp.isoformat(), next_check.isoformat(), deteriorating, timestamp.isoformat(), patient_id))


def set_reassessment_interval(patient_id: str, seconds: int) -> None:
    with connect() as conn:
        timestamp = datetime.now(timezone.utc)
        conn.execute('''UPDATE encounters SET reassessment_interval_seconds=?, next_reassessment_at=?, reassessment_due=0,
            updated_at=? WHERE patient_id=?''', (seconds, (timestamp + timedelta(seconds=seconds)).isoformat(), timestamp.isoformat(), patient_id))


def set_encounter_status(patient_id: str, status: str) -> None:
    with connect() as conn:
        conn.execute('UPDATE encounters SET status=?, updated_at=? WHERE patient_id=?', (status, now(), patient_id))


def active_patient_inputs() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT p.patient_id,p.patient_name,p.gender,p.pronouns,p.preferred_language,p.age_years,p.has_prior_history,p.chief_complaint,p.self_reported_pain,p.vitals_json FROM patients p JOIN encounters e ON e.patient_id=p.patient_id AND e.status IN ('waiting','triaged')").fetchall()
        return [{**dict(row), 'vitals': json.loads(row['vitals_json'])} for row in rows]


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


def record_override_with_weights(patient_id: str, clinician_id: str, ai_level: int, confidence: float, new_level: int, justification: str, jurisdiction: str, weights: list[tuple[str, str, float, float]]) -> int:
    with connect() as conn:
        timestamp = now()
        cur = conn.execute('INSERT INTO clinician_overrides(patient_id,clinician_id,ts,ai_recommended_level,ai_confidence,overridden_level,justification,jurisdiction) VALUES(?,?,?,?,?,?,?,?)', (patient_id, clinician_id, timestamp, ai_level, confidence, new_level, justification, jurisdiction))
        override_id = cur.lastrowid
        conn.executemany('INSERT INTO synaptic_weight_history(source_node,target_node,old_weight,new_weight,triggered_by_override_id,ts) VALUES(?,?,?,?,?,?)', [(source, target, old, new, override_id, timestamp) for source, target, old, new in weights])
        return override_id


def weight_history() -> list[dict]:
    with connect() as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM synaptic_weight_history ORDER BY ts, update_id')]


def record_action(patient_id: str, actor: str, action_type: str, details: dict) -> int:
    with connect() as conn:
        cur = conn.execute('INSERT INTO encounter_actions(patient_id,actor,action_type,details_json,ts) VALUES(?,?,?,?,?)', (patient_id, actor, action_type, json.dumps(details), now()))
        return cur.lastrowid


def recent_action_stats(minutes: int = 5) -> dict:
    with connect() as conn:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        rows = conn.execute('SELECT action_type FROM encounter_actions WHERE ts >= ?', (cutoff,)).fetchall()
        return {'actions': len(rows), 'fallbacks': sum(row['action_type'] == 'fallback' for row in rows)}
