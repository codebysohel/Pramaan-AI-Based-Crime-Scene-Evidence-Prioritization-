"""Evidentiary Priority Index (EPI) — explainable, deterministic, reproducible.

    P  probative value   = min(1, relevance[crime, category] * (0.35 + 0.65 * individualizing) * (0.8 + context))
                           context = capped boost from location/linkage/distance (-0.10 .. +0.35), so a
                           trace 2 m from the body outranks the same trace 40 m away instead of both
                           saturating at 1.0
    U  urgency           = 1 / (1 + effective_hours_to_loss / 24)
    R  irreplaceability  = 1 - replaceable
    EPI = 100 * (w_p * P + w_u * U + w_r * R)            weights per crime profile

Legal floor: exhibits whose examination is mandated by statute (e.g. BNSS §184
medico-legal samples) are floored at EPI 85.

Tiers:  P1 >= 60 or any critical flag | P2 >= 45 | P3 >= 30 | P4 below.
(Stable, non-perishable exhibits top out near EPI 65 because their urgency term
is ~0 — a P1 without a critical flag therefore needs both high probative value
and irreplaceability.) After tiering, the pipeline applies staged testing,
reference-sample promotion and officer overrides — each leaves a visible flag.

No language model touches this module. Given the same inputs and the same
knowledge-base hash, the ranking is bit-for-bit identical — a property we treat
as a requirement for evidence that may be contested in court.
"""

from __future__ import annotations

from .classifier import ClassifiedItem
from .knowledge import KnowledgeBase
from .models import Degradation, Flag, ScoreBreakdown

LEGAL_FLOOR = 85.0
LINKAGE_BASE = 0.8
PERISHABLE_CRITICAL_H = 48.0   # a forwarding letter rarely reaches the bench faster than this
TIER_THRESHOLDS = (("P1", 60.0), ("P2", 45.0), ("P3", 30.0))

_CONDITION_WORDS = {
    "ambient": "ambient storage", "hot": "hot conditions", "wet": "wet/damp packaging",
    "sunlight": "direct sunlight", "refrigerated": "refrigeration (2–8 °C)", "frozen": "freezing (−20 °C)",
    "dry_sealed": "dried, paper-sealed packaging",
}


_SEALED_VOLATILE = "an airtight container (unused paint can / nylon fire-debris bag)"


def condition_words(condition: str, profile: str | None = None) -> str:
    """Human wording for a storage condition; 'dry_sealed' means airtight for volatile evidence."""
    if condition == "dry_sealed" and profile in ("fire_debris", "volatile_tox"):
        return _SEALED_VOLATILE
    return _CONDITION_WORDS.get(condition, condition)


def _fmt_hours(h: float) -> str:
    if h < 1:
        return "under 1 hour"
    if h < 48:
        return f"~{h:.0f} h"
    return f"~{h / 24:.0f} days"


def effective_hours_to_loss(deg: Degradation) -> float | None:
    candidates = [h for h in (deg.hours_to_risk, deg.field_window_remaining_h) if h is not None]
    return max(0.0, min(candidates)) if candidates else None


def score(kb: KnowledgeBase, crime_type: str, item: ClassifiedItem, deg: Degradation) -> ScoreBreakdown:
    et = item.etype
    weights = kb.weights_for(crime_type)
    relevance = kb.relevance(crime_type, et.category)
    probative = min(1.0, relevance * (0.35 + 0.65 * item.individualizing) * (LINKAGE_BASE + item.context_boost))
    eff = effective_hours_to_loss(deg)
    urgency = 0.0 if eff is None else 1.0 / (1.0 + eff / 24.0)
    irreplaceable = 1.0 - et.replaceable
    epi = 100.0 * (weights["probative"] * probative + weights["urgency"] * urgency + weights["irreplaceable"] * irreplaceable)
    floor = bool(et.mandatory) and epi < LEGAL_FLOOR
    if floor:
        epi = LEGAL_FLOOR
    return ScoreBreakdown(
        relevance=round(relevance, 3), individualizing=round(item.individualizing, 3),
        context_boost=round(item.context_boost, 3), probative=round(probative, 3),
        urgency=round(urgency, 3), irreplaceable=round(irreplaceable, 3),
        weights=weights, legal_floor_applied=floor, epi=round(epi, 1),
    )


def flags_for(kb: KnowledgeBase, item: ClassifiedItem, deg: Degradation, divisions: list[str], collected: bool) -> list[Flag]:
    et = item.etype
    out: list[Flag] = []

    if deg.field_window_remaining_h is not None and not collected:
        rem = deg.field_window_remaining_h
        if rem <= 0:
            out.append(Flag(code="COLLECTION_WINDOW_PASSED", severity="high",
                            message="Typical collection window has passed — collect anyway and record the delay; value may be reduced."))
        elif rem < 48:
            out.append(Flag(code="COLLECT_NOW", severity="critical",
                            message=f"Still at the scene: evidence is likely lost in {_fmt_hours(rem)} (overwrite, weathering, washing). Collect immediately."))

    if deg.hours_to_risk is not None:
        if deg.at_risk and deg.quality_now <= kb.risk_threshold:
            out.append(Flag(code="QUALITY_AT_RISK", severity="high",
                            message=f"Estimated evidential quality already ~{deg.quality_now:.0%}; request immediate analysis and inform the FSL of partial-result risk."))
        elif deg.hours_to_risk < 72:
            msg = f"Degrades below usable quality in {_fmt_hours(deg.hours_to_risk)} under {condition_words(deg.condition, deg.profile)}."
            if deg.better_condition and deg.hours_to_risk_if_preserved:
                msg += f" Move to {condition_words(deg.better_condition, deg.profile)} to extend this to {_fmt_hours(deg.hours_to_risk_if_preserved)}."
            out.append(Flag(code="PERISHABLE", severity="critical" if deg.hours_to_risk < PERISHABLE_CRITICAL_H else "high", message=msg))

    static = {
        "MANDATED_EXAMINATION": ("critical", "Examination mandated by statute (BNSS §184 medico-legal samples) — forward without delay."),
        "COLD_CHAIN_REQUIRED": ("high", "Maintain cold chain (2–8 °C) from collection to FSL receipt; record temperatures."),
        "VOLATILE_TOXICANTS": ("high", "Volatile compounds (alcohol, cyanide, phosphine, accelerants) are lost with delay — request headspace/volatile analysis first."),
        "DIGITAL_VOLATILE": ("high", "Isolate from networks (Faraday bag / airplane mode), keep powered; remote wipe and lock-out risk."),
        "TIME_CRITICAL_COLLECTION": ("high", "Collection window is a few hours (e.g. GSR on hands before washing)."),
        "SAFETY_UNLOAD_FIRST": ("high", "Make the weapon safe (unload, record chamber state) before transport."),
    }
    for code in et.flags:
        if code == "DIGITAL_OVERWRITE":
            if collected:
                out.append(Flag(code="DIGITAL_INTEGRITY", severity="medium",
                                message="Record DVR clock offset and hash of exported footage; attach BSA 2023 §63 certificate."))
            else:
                out.append(Flag(code="DIGITAL_OVERWRITE", severity="critical",
                                message="DVR/NVR storage loops and overwrites (often 7–30 days). Seize or export with hash today."))
        elif code in static:
            sev, msg = static[code]
            out.append(Flag(code=code, severity=sev, message=msg))  # type: ignore[arg-type]

    if "DNA" in divisions and "FINGERPRINT" in divisions:
        out.append(Flag(code="SEQUENCE_DNA_BEFORE_PRINTS", severity="medium",
                        message="Needs both DNA and latent-print work: swab handling zones for touch DNA before powder/cyanoacrylate enhancement; route DNA ↔ Fingerprint in the sequence shown."))
    if "burnt" in item.classification.modifiers and et.category in ("biological", "clothing"):
        out.append(Flag(code="HEAT_DAMAGED_DNA", severity="medium",
                        message="Heat-exposed biological material: sample protected areas (seams, folds); expect partial profiles."))

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    out.sort(key=lambda f: order[f.severity])
    return out


def tier_for(epi: float, flags: list[Flag]) -> str:
    if any(f.severity == "critical" for f in flags):
        return "P1"
    for tier, threshold in TIER_THRESHOLDS:
        if epi >= threshold:
            return tier
    return "P4"


def rationale(kb: KnowledgeBase, crime_type: str, item: ClassifiedItem, deg: Degradation, s: ScoreBreakdown) -> str:
    et = item.etype
    label = kb.profile(crime_type)["label"]
    parts = [
        f"{et.name}: relevance {s.relevance:.2f} for {label.lower()} ({et.category} evidence), "
        f"individualizing potential {s.individualizing:.2f}"
    ]
    if item.classification.modifiers:
        parts.append(f"modifiers: {', '.join(item.classification.modifiers)}")
    if item.classification.context_signals or item.classification.distance_m is not None:
        ctx = list(item.classification.context_signals)
        if item.classification.distance_m is not None:
            ctx.append(f"{item.classification.distance_m:g} m from body/point of offence")
        parts.append(f"context: {', '.join(ctx)} (+{s.context_boost:.2f})")
    eff = effective_hours_to_loss(deg)
    if eff is None:
        parts.append("physically stable in storage")
    else:
        parts.append(f"usable quality remaining {_fmt_hours(eff)} under {condition_words(deg.condition, deg.profile)}")
    parts.append(f"irreplaceability {s.irreplaceable:.2f}")
    text = "; ".join(parts) + f". EPI {s.epi:.1f}."
    if s.legal_floor_applied:
        text += " Raised to the statutory floor (mandated examination)."
    return text
