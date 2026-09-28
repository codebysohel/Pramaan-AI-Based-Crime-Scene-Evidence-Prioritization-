"""Evidential-quality degradation model.

    Q(t) = 0.5 ** (equivalent_age)      equivalent_age = sum(dt_i / half_life[condition_i])

Two exposure phases are modelled: at the scene (scene condition) until the item
was collected, then in its current storage condition. From Q_now we derive the
number of hours until quality falls below the KB ``risk_threshold`` — both in the
current condition and in the best recommended preservation condition, which
gives the investigator a concrete, quantified instruction ("refrigerate: +26 days").

Also computes the remaining *field window* for items not yet collected
(CCTV overwrite, GSR on hands, rain on impressions).
"""

from __future__ import annotations

import math
from datetime import datetime

from .knowledge import EvidenceType, KnowledgeBase
from .models import Degradation, SceneContext

STABLE_CUTOFF_H = 50_000.0  # half-lives above this are treated as "does not degrade"


def scene_condition(scene: SceneContext) -> str:
    if scene.weather == "rain" and scene.setting in ("outdoor", "mixed"):
        return "wet"
    if scene.ambient_temp_c is not None and scene.ambient_temp_c >= 35:
        return "hot"
    return "ambient"


def hours_to_threshold(q_now: float, half_life: float, threshold: float) -> float:
    if q_now <= threshold:
        return 0.0
    return half_life * math.log2(q_now / threshold)


def assess(
    kb: KnowledgeBase,
    etype: EvidenceType,
    profile: str,
    *,
    scene: SceneContext,
    condition: str | None,
    collected: bool,
    incident_time: datetime | None,
    collected_at: datetime | None,
    reference_time: datetime,
) -> Degradation:
    thr = kb.risk_threshold
    scene_cond = scene_condition(scene)
    current = condition or (scene_cond if not collected else ("hot" if scene_cond == "hot" else "ambient"))

    start = incident_time or collected_at or reference_time
    elapsed = max(0.0, (reference_time - start).total_seconds() / 3600.0)

    if collected and collected_at and incident_time and collected_at > incident_time:
        at_scene = min(elapsed, (collected_at - incident_time).total_seconds() / 3600.0)
        age = at_scene / kb.half_life(profile, scene_cond) + (elapsed - at_scene) / kb.half_life(profile, current)
    else:
        age = elapsed / kb.half_life(profile, current)
    q_now = 0.5 ** age

    hl_now = kb.half_life(profile, current)
    stable = hl_now >= STABLE_CUTOFF_H
    to_risk = None if stable else round(hours_to_threshold(q_now, hl_now, thr), 1)

    better, better_hours = None, None
    if not stable:
        for cand in kb.preservation_advice.get(profile, []):
            if kb.half_life(profile, cand) > hl_now:
                better = cand
                better_hours = round(hours_to_threshold(q_now, kb.half_life(profile, cand), thr), 1)
                break

    field_remaining = None
    if not collected and etype.field_window_h:
        window = float(etype.field_window_h)
        if etype.weather_sensitive and scene.weather == "rain" and scene.setting in ("outdoor", "mixed"):
            window /= 6.0
        field_remaining = round(window - elapsed, 1)

    return Degradation(
        profile=profile,
        condition=current,
        elapsed_hours=round(elapsed, 1),
        quality_now=round(q_now, 3),
        hours_to_risk=to_risk,
        at_risk=(q_now <= thr) or (field_remaining is not None and field_remaining <= 0),
        better_condition=better,
        hours_to_risk_if_preserved=better_hours,
        field_window_remaining_h=field_remaining,
    )


def lab_due_hours(kb: KnowledgeBase, profile: str, q_at_submission: float) -> float | None:
    """Wall-clock hours after submission until quality crosses the threshold in lab storage."""
    hl = kb.half_life(profile, kb.lab_storage_condition)
    if hl >= STABLE_CUTOFF_H:
        return None
    return hours_to_threshold(q_at_submission, hl, kb.risk_threshold)


def quality_after(kb: KnowledgeBase, profile: str, q0: float, wall_hours: float) -> float:
    hl = kb.half_life(profile, kb.lab_storage_condition)
    if hl >= STABLE_CUTOFF_H:
        return q0
    return q0 * 0.5 ** (wall_hours / hl)
