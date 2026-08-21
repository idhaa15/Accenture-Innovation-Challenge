from __future__ import annotations

import numpy as np


def recompute_queue(base_scores: np.ndarray, wait_seconds: np.ndarray, decay_lambda: float = .0006) -> np.ndarray:
    return base_scores * np.exp(decay_lambda * wait_seconds)


def check_vitals_re_triage(current: dict, prior: dict, age_band: str) -> bool:
    thresholds = {'pediatric': (20, -3), 'adult': (25, -4), 'geriatric': (15, -3)}
    hr_limit, spo2_limit = thresholds[age_band]
    hr_now, hr_before = current.get('heart_rate'), prior.get('heart_rate')
    sp_now, sp_before = current.get('spo2'), prior.get('spo2')
    return ((hr_now is not None and hr_before is not None and hr_now - hr_before >= hr_limit) or
            (sp_now is not None and sp_before is not None and sp_now - sp_before <= spo2_limit))
