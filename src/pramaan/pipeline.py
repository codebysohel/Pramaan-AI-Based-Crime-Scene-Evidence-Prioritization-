"""End-to-end triage pipeline — the single entry point used by the MCP server,
REST API and CLI, so an MCP client, the dashboard and the command line always produce
identical results for identical inputs.

    parse text -> classify -> degradation -> EPI score -> flags -> sequence
    -> rank & tier -> gap analysis -> schedule portfolio -> narrative
    -> SHA-256 of result -> persist + chain-of-custody ledger entry
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from . import degradation as deg_mod
from . import gaps as gaps_mod
from . import bsa, privacy, scheduler, scoring
from .classifier import NEAR_BODY_MAX_M, classify
from .config import ENGINE_VERSION
from .extractor import parse_description
from .knowledge import KnowledgeBase, load_kb
from .llm.client import LLMClient, NullLLM
from .llm.tasks import llm_classify, llm_extract_items, llm_narrative
from .models import CaseInput, Flag, ItemInput, TriagedItem, TriageResult
from .sequencing import sequence
from .store import Store, canonical, sha256_text

TIER_ORDER = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
_TIERS = ("P1", "P2", "P3", "P4")
LLM_CONFIDENCE_GATE = 0.55


class CaseNotFound(KeyError):
    pass


def _norm(dt: datetime | None) -> datetime | None:
    """Timezone-aware -> naive UTC; naive values are taken as UTC."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_case_id(case_ref: str, when: datetime) -> str:
    digest = hashlib.sha256(f"{case_ref}|{when.isoformat()}".encode()).hexdigest()[:5].upper()
    return f"PRM-{when:%Y%m%d}-{digest}"


def custody_deadline(kb: KnowledgeBase, case: CaseInput) -> datetime | None:
    if not (case.accused_in_custody and case.custody_start):
        return None
    years = case.max_punishment_years or int(kb.profile(case.crime_type).get("max_punishment_years", 7))
    days = 90 if years >= 10 else 60  # BNSS §187(3)
    return _norm(case.custody_start) + timedelta(days=days)  # type: ignore[operator]


def _resolve_items(kb: KnowledgeBase, case: CaseInput, llm: LLMClient) -> tuple[list[tuple[ItemInput, str | None]], list[str]]:
    resolved: list[tuple[ItemInput, str | None]] = [(i, None) for i in case.items]
    warnings: list[str] = []
    if case.description and case.description.strip():
        llm_items = None if isinstance(llm, NullLLM) else llm_extract_items(llm, kb, case.description)
        if llm_items:
            resolved.extend(llm_items)
        else:
            parsed, warnings = parse_description(kb, case.description)
            resolved.extend((p, None) for p in parsed)
    return resolved, warnings


def _narrative_template(result: TriageResult) -> str:
    c = result.counts
    urgent = [i for i in result.items if i.urgent][:4]
    lines = [
        f"The exhibits listed in the enclosed schedule, seized in connection with {result.case_ref} "
        f"({result.crime_label.lower()}), are forwarded for scientific examination.",
        f"Of {c.get('total', 0)} exhibits, {c.get('P1', 0)} are marked Critical (P1) and {c.get('P2', 0)} High (P2); "
        f"{c.get('urgent', 0)} carry urgent-testing flags.",
    ]
    if urgent:
        parts = [f"{i.label} ({i.classification.type_name.lower()}: {i.flags[0].code.replace('_', ' ').lower()})" for i in urgent]
        lines.append("Exhibits requiring immediate attention: " + "; ".join(parts) + ".")
    if result.custody_deadline:
        lines.append(
            f"An accused is in judicial/police custody; reports are requested before {result.custody_deadline:%d %b %Y} "
            "to enable filing of the final report within the statutory period."
        )
    lines.append(
        f"Priorities were computed by the Pramaan engine v{result.engine_version} (knowledge base "
        f"{result.kb_hash[:12]}) and are submitted for the Investigating Officer's review; the FSL may re-order "
        "examinations on scientific grounds."
    )
    return " ".join(lines)


# ------------------------------------------------------------ post-tier rules
def _apply_staging(kb: KnowledgeBase, triaged: list[TriagedItem], overridden: set[str]) -> None:
    """Keep the `first_round` best exhibits of each high-volume type; hold the rest for stage 2."""
    k = int(kb.staging.get("first_round", 3))
    staged_types = set(kb.staging.get("types", []) or [])
    groups: dict[str, list[TriagedItem]] = {}
    for t in triaged:
        near = (t.classification.distance_m is not None and t.classification.distance_m <= NEAR_BODY_MAX_M) or (
            t.classification.distance_m is None and "near_body" in t.classification.context_signals)
        # Proximity trumps volume: traces close to the body/point of offence are never held back.
        if (t.classification.type_id in staged_types and t.collected and t.item_id not in overridden and not near
                and t.tier != "P4" and not any(f.severity == "critical" and f.code != "PERISHABLE" for f in t.flags)):
            groups.setdefault(t.classification.type_id, []).append(t)
    for members in groups.values():
        if len(members) <= k:
            continue
        members.sort(key=lambda t: (-t.score.epi, t.classification.distance_m if t.classification.distance_m is not None else 1e9, t.item_id))
        first = ", ".join(m.label for m in members[:k])
        for t in members[k:]:
            t.tier = "P4"
            t.flags.append(Flag(code="STAGED_HOLD", severity="info", message=(
                f"Held for stage-2 testing: {len(members)} {t.classification.type_name.lower()} exhibits in this case; "
                f"the {k} most promising ({first}) go first. Submit this one only if they are uninformative."
                + (" Preserve it now as instructed above — holding the examination is not holding the preservation."
                   if any(f.code == "PERISHABLE" for f in t.flags) else "")
            )))


def _promote_references(triaged: list[TriagedItem]) -> None:
    """Reference samples are useless alone but block every DNA comparison: give them the tier of what they enable."""
    dna = [t for t in triaged if "DNA" in t.divisions and t.classification.category != "reference" and t.tier in ("P1", "P2")]
    if not dna:
        return
    best = min((t.tier for t in dna), key=lambda x: TIER_ORDER[x])
    for t in triaged:
        if t.classification.category == "reference" and TIER_ORDER[t.tier] > TIER_ORDER[best]:
            t.tier = best  # type: ignore[assignment]
            t.flags.append(Flag(code="REFERENCE_FOR_COMPARISON", severity="medium", message=(
                f"Reference sample needed to interpret {len(dna)} priority DNA exhibit(s) — profile it in the same "
                f"batch (raised to {best})."
            )))


def _apply_overrides(resolved_items: list[ItemInput], triaged_by_id: dict[str, TriagedItem]) -> set[str]:
    done: set[str] = set()
    for n, item in enumerate(resolved_items, start=1):
        if not item.override_tier:
            continue
        t = triaged_by_id[f"E-{n:03d}"]
        before = t.tier
        t.tier = item.override_tier
        t.flags = [f for f in t.flags if f.code != "STAGED_HOLD"]
        t.flags.append(Flag(code="OFFICER_OVERRIDE", severity="info", message=(
            f"Tier set to {item.override_tier} by the investigating officer (engine: {before}). Reason: {item.override_reason}"
        )))
        done.add(t.item_id)
    return done


def run_triage(
    case: CaseInput,
    *,
    llm: LLMClient | None = None,
    store: Store | None = None,
    actor: str = "investigator",
    case_id: str | None = None,
    persist: bool = True,
    action: str = "triage",
    use_llm_narrative: bool = True,
) -> TriageResult:
    kinds = privacy.scan(privacy.case_texts(case))
    if kinds:
        if persist:
            (store or Store()).append(actor, "privacy_block", {"kinds": kinds, "case_ref_sha256": sha256_text(case.case_ref)})
        raise privacy.PrivacyViolation(kinds)
    kb = load_kb()
    llm = llm or NullLLM()
    profile = kb.profile(case.crime_type)
    crime_key = next(k for k, v in kb.profiles.items() if v is profile)
    ref_time = _norm(case.reference_time) or _now()
    incident = _norm(case.incident_time)

    resolved, warnings = _resolve_items(kb, case, llm)
    if not resolved:
        raise ValueError("No exhibits supplied. Provide `items` or a `description` listing the exhibits.")

    triaged: list[TriagedItem] = []
    used_labels: set[str] = set()
    for n, (item, llm_type) in enumerate(resolved, start=1):
        item_id = f"E-{n:03d}"
        ci = classify(kb, item.description, item.location, item.type_hint)
        if ci.classification.method == "fallback" or (
            ci.classification.method == "rules" and ci.classification.confidence < LLM_CONFIDENCE_GATE
        ):
            proposal = llm_type or (None if isinstance(llm, NullLLM) else llm_classify(llm, kb, item.description))
            if proposal and proposal != ci.etype.id:
                ci = classify(kb, item.description, item.location, proposal)
                ci.classification.method = "llm"
                ci.classification.confidence = 0.6
        if ci.classification.method == "fallback":
            warnings.append(f"{item.label or item_id}: could not classify '{item.description[:60]}' — review manually.")

        d = deg_mod.assess(
            kb, ci.etype, ci.degradation_profile, scene=case.scene, condition=item.condition,
            collected=item.collected, incident_time=incident, collected_at=_norm(item.collected_at), reference_time=ref_time,
        )
        s = scoring.score(kb, crime_key, ci, d)
        steps = sequence(kb, ci.exams, item.quantity)
        divisions = list(dict.fromkeys(st.division for st in steps))
        fl = scoring.flags_for(kb, ci, d, divisions, item.collected)
        label = (item.label or item_id).strip()
        if label in used_labels:
            label = f"{label}#{item_id}"
        used_labels.add(label)
        triaged.append(TriagedItem(
            item_id=item_id, label=label, description=item.description, location=item.location,
            quantity=item.quantity, collected=item.collected, tier=scoring.tier_for(s.epi, fl),  # type: ignore[arg-type]
            classification=ci.classification, degradation=d, score=s, flags=fl, exam_sequence=steps,
            divisions=divisions, caveat=ci.etype.caveat, corroborate_with=ci.etype.corroborate_with,
            handling=ci.etype.handling, rationale=scoring.rationale(kb, crime_key, ci, d, s), notes=ci.notes,
        ))

    # BSA 2023 ss.61-63: admissibility readiness of electronic records. Added AFTER tiering on purpose —
    # legal-readiness actions must not change forensic priority.
    inputs_by_id = {f"E-{n:03d}": item for n, (item, _) in enumerate(resolved, start=1)}
    for t in triaged:
        if bsa.is_electronic(t):
            er = inputs_by_id[t.item_id].electronic if t.item_id in inputs_by_id else None
            t.authenticity = bsa.assess_electronic(er, t, seizure_video=case.seizure_video_recorded)
            t.flags.extend(bsa.electronic_flags(t.authenticity, er))
    for t in triaged:
        t.engine_tier = t.tier
    overridden = {f"E-{n:03d}" for n, (item, _) in enumerate(resolved, start=1) if item.override_tier}
    _apply_staging(kb, triaged, overridden)
    _promote_references(triaged)
    _apply_overrides([i for i, _ in resolved], {t.item_id: t for t in triaged})
    for t in triaged:
        t.stage = 2 if t.tier == "P4" else 1

    triaged.sort(key=lambda t: (TIER_ORDER[t.tier], -t.score.epi, t.item_id))
    for rank, t in enumerate(triaged, start=1):
        t.rank = rank

    deadline = custody_deadline(kb, case)
    hours_left = None if deadline is None else (deadline - ref_time).total_seconds() / 3600.0
    comparison = scheduler.plan(kb, triaged, hours_left)
    gap_alerts = gaps_mod.analyse(kb, crime_key, triaged, case.scene, case.photo_captions)

    counts = {"total": len(triaged), "urgent": sum(t.urgent for t in triaged), "gaps": len(gap_alerts),
              "at_risk": sum(t.degradation.at_risk for t in triaged), "stage1": sum(t.stage == 1 for t in triaged),
              "held": sum(t.stage == 2 for t in triaged)}
    for tier in TIER_ORDER:
        counts[tier] = sum(t.tier == tier for t in triaged)

    created = _now()
    cid = case_id or make_case_id(case.case_ref, created)
    result = TriageResult(
        case_id=cid, case_ref=case.case_ref, title=case.title, crime_type=crime_key, crime_label=profile["label"],
        created_at=created, reference_time=ref_time, engine_version=ENGINE_VERSION, kb_hash=kb.kb_hash,
        llm_provider=llm.name, items=triaged, gaps=gap_alerts, schedule=comparison, custody_deadline=deadline,
        parse_warnings=warnings, counts=counts,
    )
    result.narrative = _narrative_template(result)
    if use_llm_narrative and not isinstance(llm, NullLLM):
        facts = result.narrative + "\nUrgent flags: " + "; ".join(
            f"{i.label}: {f.message}" for i in triaged for f in i.flags if f.urgent
        )[:3000]
        drafted = llm_narrative(llm, facts)
        if drafted:
            result.narrative = drafted

    body = result.model_dump(mode="json")
    body.pop("result_sha256", None)
    result.result_sha256 = sha256_text(canonical(body))

    if persist:
        store = store or Store()
        stored_input = case.model_dump(mode="json")
        stored_input["original_description"] = stored_input.pop("description", None)
        stored_input["items"] = [i.model_dump(mode="json") for i, _ in resolved]
        stored_input["description"] = None
        stored_input["reference_time"] = ref_time.isoformat()
        store.save_case(cid, case.case_ref, crime_key, case.title, kb.kb_hash, stored_input,
                        result.model_dump(mode="json"), result.result_sha256)
        store.append(actor, action, {
            "result_sha256": result.result_sha256, "kb_hash": kb.kb_hash, "engine_version": ENGINE_VERSION,
            "llm_provider": llm.name, "counts": counts, "policy": comparison.recommended.policy,
        }, case_id=cid)
    return result


# --------------------------------------------------------------- case ops
def load_case_input(store: Store, case_id: str) -> tuple[CaseInput, dict[str, Any]]:
    case = store.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    return CaseInput(**case["input"]), case


def _item_index(result: dict[str, Any], item_ref: str) -> int:
    for it in result["items"]:
        if item_ref in (it["item_id"], it["label"]):
            return int(it["item_id"].split("-")[1]) - 1
    raise KeyError(f"No exhibit '{item_ref}' in this case")


def update_item(store: Store, case_id: str, item_ref: str, changes: dict[str, Any], actor: str = "investigator",
                llm: LLMClient | None = None) -> TriageResult:
    """Apply changes to one exhibit (e.g. condition='refrigerated', collected=True) and re-triage."""
    case_in, stored = load_case_input(store, case_id)
    idx = _item_index(stored["result"], item_ref)
    allowed = {"condition", "collected", "collected_at", "location", "quantity", "type_hint", "description", "label",
               "override_tier", "override_reason", "electronic"}
    bad = set(changes) - allowed
    if bad:
        raise ValueError(f"Cannot change {sorted(bad)}; allowed: {sorted(allowed)}")
    items = list(case_in.items)
    items[idx] = ItemInput(**{**items[idx].model_dump(), **changes})  # re-validate (e.g. override needs a reason)
    new_case = case_in.model_copy(update={"items": items})
    result = run_triage(new_case, llm=llm, store=store, actor=actor, case_id=case_id, action="retriage",
                        use_llm_narrative=False)
    store.append(actor, "item_updated", {"changes": changes}, case_id=case_id, item_id=item_ref)
    return result


def simulate_preservation(store: Store, case_id: str, item_ref: str, condition: str) -> dict[str, Any]:
    """What-if: how much time/priority/value does moving one exhibit to `condition` buy? (not persisted)"""
    case_in, stored = load_case_input(store, case_id)
    idx = _item_index(stored["result"], item_ref)
    before = TriageResult(**stored["result"])
    items = list(case_in.items)
    items[idx] = items[idx].model_copy(update={"condition": condition})
    after = run_triage(case_in.model_copy(update={"items": items}), persist=False, case_id=case_id, use_llm_narrative=False)

    def pick(r: TriageResult) -> TriagedItem:
        return next(i for i in r.items if i.item_id == f"E-{idx + 1:03d}")

    b, a = pick(before), pick(after)
    return {
        "item": b.label, "type": b.classification.type_name, "condition": {"from": b.degradation.condition, "to": condition},
        "hours_to_risk": {"from": b.degradation.hours_to_risk, "to": a.degradation.hours_to_risk},
        "epi": {"from": b.score.epi, "to": a.score.epi}, "tier": {"from": b.tier, "to": a.tier},
        "case_value_retained": {"from": before.schedule.recommended.value_retained, "to": after.schedule.recommended.value_retained},
        "flags_after": [f.code for f in a.flags],
    }
