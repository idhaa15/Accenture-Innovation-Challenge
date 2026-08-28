from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class Vitals(BaseModel):
    heart_rate: int | None = Field(default=None, ge=0, le=300)
    resp_rate: int | None = Field(default=None, ge=0, le=100)
    temp_c: float | None = Field(default=None, ge=25, le=45)
    spo2: int | None = Field(default=None, ge=0, le=100)
    systolic_bp: int | None = Field(default=None, ge=0, le=300)


class PatientInput(BaseModel):
    patient_id: str = Field(min_length=2, max_length=64)
    patient_name: str = Field(default='', max_length=120)
    gender: str = Field(default='Not specified', max_length=40)
    pronouns: str = Field(default='', max_length=40)
    preferred_language: str = Field(default='English', max_length=80)
    age_years: int = Field(ge=0, le=130)
    has_prior_history: bool
    chief_complaint: str = Field(min_length=3, max_length=1000)
    vitals: Vitals
    self_reported_pain: int | None = Field(default=None, ge=0, le=10)


class AgentReasoningPath(BaseModel):
    agent_name: str
    graph_nodes_visited: list[str]
    conclusion: str
    confidence_delta: float


class Explanation(BaseModel):
    summary: str = Field(min_length=1)
    evidence: list[str]
    why_this_level: str = Field(min_length=1)


class DataQuality(BaseModel):
    status: Literal['complete', 'incomplete']
    missing_fields: list[str] = []
    invalid_fields: list[str] = []
    stale_fields: list[str] = []
    next_best_questions: list[str] = []


class TriageResult(BaseModel):
    patient_id: str
    triage_level: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0, le=1)
    escalated_for_uncertainty: bool
    degraded_mode: bool
    reasoning_path: list[AgentReasoningPath]
    trigger_reason: Literal['intake', 'reassessment', 'vitals_change', 'clinician_override', 'manual_escalation']
    symptoms: list[str] = []
    demographic_flags: list[str] = []
    updated_at: datetime
    explanation: Explanation
    recommended_department: str
    routing_confidence: Literal['high', 'heuristic']
    data_quality: DataQuality
    disclaimer: str = Field(min_length=1)


class OverridePayload(BaseModel):
    patient_id: str
    clinician_id: str = Field(min_length=2, max_length=100)
    overridden_level: int = Field(ge=1, le=5)
    justification: str = Field(min_length=10, max_length=1000)
    jurisdiction: str = Field(default='HIPAA', min_length=2, max_length=50)

    @field_validator('justification')
    @classmethod
    def non_blank_reason(cls, value: str) -> str:
        if len(value.strip()) < 10:
            raise ValueError('A meaningful justification of at least 10 characters is required.')
        return value.strip()


class VitalsUpdate(BaseModel):
    vitals: Vitals


class SurgePayload(BaseModel):
    count: int = Field(default=10, ge=1, le=20)
