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


class TriageResult(BaseModel):
    patient_id: str
    triage_level: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0, le=1)
    escalated_for_uncertainty: bool
    degraded_mode: bool
    reasoning_path: list[AgentReasoningPath]
    trigger_reason: Literal['intake', 'wait_decay', 'vitals_change']
    symptoms: list[str] = []
    demographic_flags: list[str] = []
    updated_at: datetime


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
