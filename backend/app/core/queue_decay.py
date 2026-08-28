from __future__ import annotations

import numpy as np


def within_bucket_priority(wait_seconds: np.ndarray, reassessment_seconds: np.ndarray) -> np.ndarray:
    """Capped, linear fairness signal used only after acuity and safety status.

    This is deliberately *not* a clinical severity score.  A longer wait can
    change order only among patients already in the same acuity bucket.
    """
    safe_interval = np.maximum(reassessment_seconds, 60)
    return np.minimum(wait_seconds / safe_interval, 1.0)


def check_vitals_re_triage(current: dict, prior: dict, age_band: str) -> bool:
    thresholds = {'pediatric': (20, -3, 8, -15), 'adult': (25, -4, 6, -20), 'geriatric': (15, -3, 6, -15)}
    hr_limit, spo2_limit, rr_limit, bp_limit = thresholds[age_band]

    def changed(key: str, limit: float, direction: str) -> bool:
        now, before = current.get(key), prior.get(key)
        if now is None or before is None:
            return False
        return now - before >= limit if direction == 'up' else now - before <= limit

    return any((
        changed('heart_rate', hr_limit, 'up'),
        changed('spo2', spo2_limit, 'down'),
        changed('resp_rate', rr_limit, 'up'),
        changed('systolic_bp', bp_limit, 'down'),
        current.get('spo2') is not None and current['spo2'] < 90,
        current.get('systolic_bp') is not None and current['systolic_bp'] < 90,
    ))
