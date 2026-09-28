"""Deterministic evidence classifier.

Maps an investigator's free-text description of ONE exhibit to a knowledge-base
evidence type, plus:
  * modifiers  — facts that add examinations (e.g. "bloodstained", "burnt")
  * context    — where/with whom it was found (near body, from accused, ...)
  * distance   — "3 m from the body" -> proximity boost

Resolution rules (in order):
  1. an explicit ``type_hint`` wins (confidence 1.0);
  2. the most specific keyword wins (longest phrase, then number of distinct hits);
  3. a ``kind: stain`` type yields to an object type found in the same text and
     is converted into its modifier ("bloodstained stone" = blunt_weapon + blood);
  4. nothing matched -> ``other_object`` with low confidence (the LLM layer, when
     enabled, may then propose a type from the closed KB vocabulary).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .knowledge import EvidenceType, KnowledgeBase
from .models import Classification

_DISTANCE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:m|mtr|mtrs|metre|metres|meter|meters)\b", re.IGNORECASE
)
NEAR_BODY_MAX_M = 10.0
_ANCHOR = re.compile(r"\b(body|deceased|victim|survivor|dead\s+body|point\s+of\s+(?:entry|offence|impact))\b", re.I)


@dataclass
class ClassifiedItem:
    classification: Classification
    etype: EvidenceType
    individualizing: float
    exams: list[str]
    degradation_profile: str
    context_boost: float
    notes: list[str] = field(default_factory=list)


def _type_score(et: EvidenceType, text: str) -> tuple[float, list[str], list[tuple[int, int]]]:
    hits: list[str] = []
    spans: list[tuple[int, int]] = []
    best_len = 0
    for kw, pat in et.patterns:
        m = pat.search(text)
        if m:
            hits.append(kw)
            spans.append(m.span())
            best_len = max(best_len, len(kw))
    if not hits:
        return 0.0, [], []
    return best_len + 2.0 * (len(hits) - 1), hits, spans


def detect_modifiers(kb: KnowledgeBase, text: str) -> list[str]:
    return [m for m, pats in kb.modifier_patterns.items() if any(p.search(text) for _, p in pats)]


def detect_signals(kb: KnowledgeBase, text: str) -> list[str]:
    return [s for s, pats in kb.signal_patterns.items() if any(p.search(text) for _, p in pats)]


def detect_distance(text: str) -> float | None:
    """Distance to the body / point of offence, if the text states one."""
    if not _ANCHOR.search(text):
        return None
    m = _DISTANCE.search(text)
    return float(m.group(1)) if m else None


def rank_types(kb: KnowledgeBase, text: str) -> list[tuple[float, EvidenceType, list[str]]]:
    ranked = []
    for et in kb.types.values():
        score, hits, _ = _type_score(et, text)
        if score > 0:
            ranked.append((score, et, hits))
    ranked.sort(key=lambda r: (-r[0], r[1].kind == "stain", r[1].id))
    return ranked


def classify(
    kb: KnowledgeBase,
    description: str,
    location: str | None = None,
    type_hint: str | None = None,
) -> ClassifiedItem:
    text = f"{description} {location or ''}".strip()
    modifiers = detect_modifiers(kb, text)
    signals = detect_signals(kb, text)
    distance = detect_distance(text)
    matched: list[str] = []
    method = "rules"

    if type_hint:
        if type_hint not in kb.types:
            raise ValueError(f"Unknown evidence type '{type_hint}'. Use lookup_evidence_type to find valid ids.")
        et, confidence, method = kb.types[type_hint], 1.0, "hint"
    else:
        ranked = rank_types(kb, description) or rank_types(kb, text)
        if not ranked:
            et, confidence, method = kb.types["other_object"], 0.15, "fallback"
        else:
            score, et, matched = ranked[0]
            if et.kind == "stain":
                objects = [r for r in ranked if r[1].kind != "stain"]
                if objects:
                    stain = et
                    _, et, obj_hits = objects[0]
                    matched = obj_hits + matched
                    if stain.as_modifier and stain.as_modifier not in modifiers:
                        modifiers.append(stain.as_modifier)
            confidence = min(0.95, 0.5 + score / 40.0)

    # Modifiers add examinations and may make the item more perishable.
    exams = list(et.exam_plan)
    individualizing = et.individualizing
    profile = et.degradation
    notes: list[str] = []
    for m in modifiers:
        spec = kb.modifiers[m]
        for ex in spec.get("add_exams", []) or []:
            if ex not in exams:
                exams.append(ex)
        individualizing += float(spec.get("individualizing_boost", 0.0))
        alt = spec.get("degradation")
        if alt and kb.half_life(alt, "ambient") < kb.half_life(profile, "ambient"):
            profile = alt
        if spec.get("note"):
            notes.append(spec["note"])
    individualizing = max(0.05, min(0.97, individualizing))

    # Context: capped additive boost; explicit distance replaces the generic near-body boost.
    boost = sum(float(kb.context_signals[s]["boost"]) for s in signals)
    if distance is not None:
        proximity = 0.15 * math.exp(-distance / 25.0)
        if "near_body" in signals:
            boost -= float(kb.context_signals["near_body"]["boost"])
            if distance > NEAR_BODY_MAX_M:  # "40 m from the body" is not "near the body"
                signals.remove("near_body")
        boost += proximity
    boost = max(-0.1, min(0.35, boost))

    return ClassifiedItem(
        classification=Classification(
            type_id=et.id, type_name=et.name, category=et.category,
            confidence=round(confidence, 2), method=method, matched_keywords=matched[:6],
            modifiers=modifiers, context_signals=signals, distance_m=distance,
        ),
        etype=et, individualizing=individualizing, exams=exams,
        degradation_profile=profile, context_boost=round(boost, 3), notes=notes,
    )
