"""Knowledge-base loader.

The forensic reasoning of Pramaan lives in four YAML files under
``pramaan/knowledge/`` — not in code — so FSL experts can review and calibrate it
without touching Python. This module loads them, validates every cross-reference
(fail-closed: a typo in the KB stops the engine instead of silently mis-scoring),
compiles keyword patterns, and computes a content hash that is stamped on every
triage result and chain-of-custody entry.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .config import PACKAGE_DIR

KB_DIR = PACKAGE_DIR / "knowledge"
KB_FILES = ("laboratory.yaml", "evidence_types.yaml", "degradation.yaml", "crime_profiles.yaml")
CONDITIONS = ("ambient", "hot", "wet", "sunlight", "refrigerated", "frozen", "dry_sealed")
CATEGORIES = (
    "biological", "reference", "clothing", "trace", "impression", "weapon", "firearm",
    "toxicology", "chemical", "digital", "document", "vehicle", "other",
)


class KnowledgeBaseError(ValueError):
    """Raised when the knowledge base is internally inconsistent."""


def phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Whole-phrase, case-insensitive pattern; spaces/hyphens are interchangeable."""
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", phrase.strip()) if p]
    body = r"[\s\-]+".join(parts)
    return re.compile(rf"(?<![\w]){body}(?![\w])", re.IGNORECASE)


@dataclass
class EvidenceType:
    id: str
    name: str
    category: str
    keywords: list[str]
    exam_plan: list[str]
    individualizing: float
    replaceable: float
    degradation: str
    kind: str = "object"
    as_modifier: str | None = None
    field_window_h: float | None = None
    weather_sensitive: bool = False
    mandatory: str | None = None
    flags: list[str] = field(default_factory=list)
    caveat: str = ""
    corroborate_with: list[str] = field(default_factory=list)
    handling: str = ""
    patterns: list[tuple[str, re.Pattern[str]]] = field(default_factory=list, repr=False)


@dataclass
class KnowledgeBase:
    lab: dict[str, Any]
    divisions: dict[str, dict[str, Any]]
    exams: dict[str, dict[str, Any]]
    types: dict[str, EvidenceType]
    modifiers: dict[str, dict[str, Any]]
    context_signals: dict[str, dict[str, Any]]
    risk_threshold: float
    lab_storage_condition: str
    degradation_profiles: dict[str, dict[str, float]]
    preservation_advice: dict[str, list[str]]
    default_weights: dict[str, float]
    common_gaps: list[dict[str, Any]]
    profiles: dict[str, dict[str, Any]]
    kb_hash: str
    staging: dict[str, Any] = field(default_factory=dict)
    network: list[dict[str, Any]] = field(default_factory=list)
    modifier_patterns: dict[str, list[tuple[str, re.Pattern[str]]]] = field(default_factory=dict, repr=False)
    signal_patterns: dict[str, list[tuple[str, re.Pattern[str]]]] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------ lookups
    def profile(self, crime_type: str) -> dict[str, Any]:
        key = crime_type.strip().lower().replace(" ", "_").replace("-", "_")
        if key not in self.profiles:
            raise KnowledgeBaseError(
                f"Unknown crime type '{crime_type}'. Known: {', '.join(sorted(self.profiles))}"
            )
        return self.profiles[key]

    def weights_for(self, crime_type: str) -> dict[str, float]:
        return dict(self.profile(crime_type).get("weights") or self.default_weights)

    def relevance(self, crime_type: str, category: str) -> float:
        return float(self.profile(crime_type).get("relevance", {}).get(category, 0.4))

    def half_life(self, profile: str, condition: str) -> float:
        return float(self.degradation_profiles[profile][condition])

    def search(self, query: str, limit: int = 5) -> list[EvidenceType]:
        """Rank evidence types by keyword hits and name overlap (used by the MCP lookup tool)."""
        q = query.lower().strip()
        scored: list[tuple[float, EvidenceType]] = []
        for et in self.types.values():
            score = 0.0
            if q == et.id or q in et.name.lower():
                score += 10
            for kw, pat in et.patterns:
                if pat.search(q):
                    score += 2 + len(kw) / 10
            words = set(re.findall(r"\w+", q))
            score += 0.5 * len(words & set(re.findall(r"\w+", et.name.lower())))
            if score > 0:
                scored.append((score, et))
        scored.sort(key=lambda s: -s[0])
        return [et for _, et in scored[:limit]]


def _read_yaml(name: str) -> tuple[dict[str, Any], bytes]:
    raw = (KB_DIR / name).read_bytes()
    return yaml.safe_load(raw) or {}, raw


def _validate(kb: KnowledgeBase) -> None:
    errors: list[str] = []
    for ex_id, ex in kb.exams.items():
        if ex.get("division") not in kb.divisions:
            errors.append(f"exam {ex_id}: unknown division {ex.get('division')}")
        for dep in ex.get("after", []) or []:
            if dep not in kb.exams:
                errors.append(f"exam {ex_id}: 'after' references unknown exam {dep}")
    for p_id, prof in kb.degradation_profiles.items():
        missing = [c for c in CONDITIONS if c not in prof]
        if missing:
            errors.append(f"degradation profile {p_id}: missing conditions {missing}")
    for t in kb.types.values():
        if t.category not in CATEGORIES:
            errors.append(f"type {t.id}: unknown category {t.category}")
        if t.degradation not in kb.degradation_profiles:
            errors.append(f"type {t.id}: unknown degradation profile {t.degradation}")
        for ex in t.exam_plan:
            if ex not in kb.exams:
                errors.append(f"type {t.id}: unknown exam {ex}")
        if t.as_modifier and t.as_modifier not in kb.modifiers:
            errors.append(f"type {t.id}: unknown as_modifier {t.as_modifier}")
        if not 0 <= t.individualizing <= 1 or not 0 <= t.replaceable <= 1:
            errors.append(f"type {t.id}: individualizing/replaceable must be within 0..1")
    for unit in kb.network:
        for div in unit.get("examiners", {}):
            if div not in kb.divisions:
                errors.append(f"network unit {unit.get('id')}: unknown division {div}")
    for t_id in kb.staging.get("types", []) or []:
        if t_id not in kb.types:
            errors.append(f"staging: unknown type {t_id}")
    if int(kb.staging.get("first_round", 3)) < 1:
        errors.append("staging.first_round must be >= 1")
    for m_id, mod in kb.modifiers.items():
        for ex in mod.get("add_exams", []) or []:
            if ex not in kb.exams:
                errors.append(f"modifier {m_id}: unknown exam {ex}")
    all_gaps = list(kb.common_gaps) + [g for p in kb.profiles.values() for g in p.get("gaps", []) or []]
    for g in all_gaps:
        for t in g.get("missing_any_type", []) or []:
            if t not in kb.types:
                errors.append(f"gap {g.get('id')}: unknown type {t}")
        for c in (g.get("missing_any_category", []) or []) + (g.get("only_if_category_present", []) or []):
            if c not in CATEGORIES:
                errors.append(f"gap {g.get('id')}: unknown category {c}")
    for p_id, prof in kb.profiles.items():
        w = prof.get("weights") or kb.default_weights
        if abs(sum(w.values()) - 1.0) > 1e-6:
            errors.append(f"profile {p_id}: weights must sum to 1 (got {sum(w.values())})")
        for cat in (prof.get("relevance") or {}):
            if cat not in CATEGORIES:
                errors.append(f"profile {p_id}: unknown relevance category {cat}")
    if errors:
        raise KnowledgeBaseError("Knowledge base validation failed:\n  - " + "\n  - ".join(errors))


@lru_cache(maxsize=1)
def load_kb() -> KnowledgeBase:
    docs: dict[str, dict[str, Any]] = {}
    digest = hashlib.sha256()
    for name in KB_FILES:
        data, raw = _read_yaml(name)
        docs[name] = data
        digest.update(name.encode() + b"\0" + raw + b"\0")

    lab_doc, et_doc = docs["laboratory.yaml"], docs["evidence_types.yaml"]
    deg_doc, crime_doc = docs["degradation.yaml"], docs["crime_profiles.yaml"]

    types: dict[str, EvidenceType] = {}
    for raw in et_doc.get("types", []):
        et = EvidenceType(
            id=raw["id"], name=raw["name"], category=raw["category"],
            keywords=list(raw.get("keywords") or []), exam_plan=list(raw.get("exam_plan") or []),
            individualizing=float(raw["individualizing"]), replaceable=float(raw["replaceable"]),
            degradation=raw["degradation"], kind=raw.get("kind", "object"),
            as_modifier=raw.get("as_modifier"), field_window_h=raw.get("field_window_h"),
            weather_sensitive=bool(raw.get("weather_sensitive", False)), mandatory=raw.get("mandatory"),
            flags=list(raw.get("flags") or []), caveat=raw.get("caveat", ""),
            corroborate_with=list(raw.get("corroborate_with") or []), handling=raw.get("handling", ""),
        )
        if et.id in types:
            raise KnowledgeBaseError(f"duplicate evidence type id {et.id}")
        et.patterns = [(kw, phrase_pattern(kw)) for kw in et.keywords]
        types[et.id] = et

    kb = KnowledgeBase(
        lab=lab_doc.get("lab_profile", {}),
        divisions=lab_doc.get("divisions", {}),
        exams=lab_doc.get("examinations", {}),
        types=types,
        modifiers=et_doc.get("modifiers", {}),
        context_signals=et_doc.get("context_signals", {}),
        risk_threshold=float(deg_doc.get("risk_threshold", 0.6)),
        lab_storage_condition=deg_doc.get("lab_storage_condition", "refrigerated"),
        degradation_profiles=deg_doc.get("profiles", {}),
        preservation_advice=deg_doc.get("preservation_advice", {}),
        default_weights=crime_doc.get("default_weights", {"probative": 0.55, "urgency": 0.3, "irreplaceable": 0.15}),
        common_gaps=crime_doc.get("common_gaps", []),
        profiles=crime_doc.get("profiles", {}),
        kb_hash=digest.hexdigest(),
        staging=et_doc.get("staging") or {"first_round": 3, "types": []},
        network=lab_doc.get("network") or [],
    )
    kb.modifier_patterns = {
        m: [(p, phrase_pattern(p)) for p in spec.get("patterns", [])] for m, spec in kb.modifiers.items()
    }
    kb.signal_patterns = {
        s: [(p, phrase_pattern(p)) for p in spec.get("patterns", [])] for s, spec in kb.context_signals.items()
    }
    _validate(kb)
    return kb
