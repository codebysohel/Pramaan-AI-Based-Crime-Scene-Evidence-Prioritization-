"""PRAMAAN-X AI-to-deterministic triage bridge.

This module keeps the existing audited ``run_triage`` engine intact and places
M1-M5 in front of it as a control layer:

scene notes -> M1 + rules -> reconciliation -> GuardRail -> deterministic triage
scene photos -> M2/M5 visual candidates -> human review signals
M3/M4 enrich the Evidence Digital Twins but never change EPI or priority.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from . import privacy
from .ai_orchestrator import PRAMAANAIOrchestrator
from .llm.client import NullLLM
from .models import CaseInput, ItemInput
from .pipeline import run_triage
from .store import Store

_ALLOWED_CONDITIONS = {
    "ambient",
    "hot",
    "wet",
    "sunlight",
    "refrigerated",
    "frozen",
    "dry_sealed",
}


def _norm_text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _safe_condition(value: Any) -> str | None:
    """Return only conditions accepted by ItemInput.

    M1 intentionally extracts free-text conditions (for example "half-burnt").
    Those remain in the Digital Twin, but must not be forced into the deterministic
    degradation model unless they match its controlled condition vocabulary.
    """
    value = _norm_text(value).replace(" ", "_")
    return value if value in _ALLOWED_CONDITIONS else None


def _items_from_twins(twins: list[dict[str, Any]]) -> list[ItemInput]:
    items: list[ItemInput] = []
    for twin in twins:
        description = str(twin.get("description") or "").strip()
        if not description:
            continue

        scene = twin.get("scene") or {}
        condition = twin.get("condition") or {}
        quantity = twin.get("quantity") or 1
        try:
            quantity = max(1, int(quantity))
        except (TypeError, ValueError):
            quantity = 1

        items.append(
            ItemInput(
                description=description,
                location=scene.get("location"),
                quantity=quantity,
                condition=_safe_condition(condition.get("state")),
            )
        )
    return items


def _items_from_reconciliation_union(reconciliation: dict[str, Any]) -> list[ItemInput]:
    """Build a conservative union of parser candidates for provisional triage.

    Matched exhibits normally come from Digital Twins.  When GuardRail is
    NEEDS_REVIEW, unmatched but classified candidates must not disappear from
    the result simply because one parser missed them.  We therefore include
    both missing_from_m1 and missing_from_rules as review-marked provisional
    exhibits.  Fallback/unclassified narrative text is intentionally excluded.
    """
    out: list[ItemInput] = []
    seen: set[tuple[str, str]] = set()
    for key in ("missing_from_m1", "missing_from_rules"):
        for raw in reconciliation.get(key) or []:
            description = str(raw.get("description") or "").strip()
            if not description:
                continue
            location = raw.get("location")
            dedupe = (_norm_text(description), _norm_text(location))
            if dedupe in seen:
                continue
            seen.add(dedupe)
            try:
                quantity = max(1, int(raw.get("quantity") or 1))
            except (TypeError, ValueError):
                quantity = 1
            out.append(ItemInput(
                description=description,
                location=location,
                quantity=quantity,
                condition=_safe_condition(raw.get("condition")),
            ))
    return out


def _merge_items(explicit: list[ItemInput], ai_items: list[ItemInput]) -> list[ItemInput]:
    """Preserve explicit investigator items and add non-duplicate reconciled items."""
    merged = list(explicit)
    seen = {
        (_norm_text(i.description), _norm_text(i.location))
        for i in explicit
    }
    for item in ai_items:
        key = (_norm_text(item.description), _norm_text(item.location))
        if key not in seen:
            merged.append(item)
            seen.add(key)
    return merged


def _attach_triage_to_twins(
    twins: list[dict[str, Any]],
    triage_result: dict[str, Any],
) -> None:
    """Attach deterministic outputs to the already-enriched Digital Twins."""
    by_description: dict[str, list[dict[str, Any]]] = {}
    for item in triage_result.get("items") or []:
        by_description.setdefault(_norm_text(item.get("description")), []).append(item)

    for twin in twins:
        candidates = by_description.get(_norm_text(twin.get("description"))) or []
        if len(candidates) != 1:
            continue
        item = candidates[0]
        twin["triage"] = {
            "item_id": item.get("item_id"),
            "rank": item.get("rank"),
            "tier": item.get("tier"),
            "engine_tier": item.get("engine_tier"),
            "stage": item.get("stage"),
            "epi": (item.get("score") or {}).get("epi"),
            "flags": item.get("flags") or [],
            "divisions": item.get("divisions") or [],
            "exam_sequence": item.get("exam_sequence") or [],
        }


def _final_gate(
    text_guardrail: dict[str, Any],
    visual: dict[str, Any],
) -> dict[str, Any]:
    """Combine text GuardRail with visual-review signals.

    Visual candidates never become evidence automatically. An unlinked candidate
    therefore blocks *submission*, not deterministic triage, until an investigator
    confirms or rejects it.
    """
    issues = list(text_guardrail.get("issues") or [])
    unlinked = visual.get("unlinked_visual_candidates") or []

    if unlinked:
        issues.append(
            {
                "code": "UNLINKED_VISUAL_CANDIDATES",
                "severity": "high",
                "message": (
                    f"{len(unlinked)} visual candidate(s) are not linked to a "
                    "reconciled exhibit and require investigator review."
                ),
                "item_id": None,
            }
        )

    text_state = str(text_guardrail.get("state") or "BLOCKED")
    if text_state == "BLOCKED":
        state = "BLOCKED"
    elif text_state == "NEEDS_REVIEW" or unlinked:
        state = "NEEDS_REVIEW"
    else:
        state = "READY"

    return {
        "state": state,
        "triage_allowed": bool(text_guardrail.get("triage_allowed")),
        "submission_allowed": state == "READY",
        "human_confirmation_required": state != "READY",
        "issues": issues,
        "summary": (
            "PRAMAAN-X final gate passed."
            if state == "READY"
            else f"PRAMAAN-X final gate {state}: investigator review required."
        ),
    }


def run_ai_triage(
    case: CaseInput,
    *,
    image_paths: Iterable[str | Path] | None = None,
    m1_result: dict[str, Any] | None = None,
    orchestrator: PRAMAANAIOrchestrator | None = None,
    store: Store | None = None,
    actor: str = "investigator",
    persist: bool = True,
    run_m2: bool = True,
    run_m3: bool = True,
    run_m4: bool = True,
    run_m5: bool = False,
    save_annotated: bool = True,
) -> dict[str, Any]:
    """Run PRAMAAN-X AI control layer followed by deterministic triage.

    Returns an envelope rather than changing ``TriageResult`` so existing REST,
    CLI and MCP consumers of the deterministic engine remain backwards compatible.
    """
    kinds = privacy.scan(privacy.case_texts(case))
    if kinds:
        raise privacy.PrivacyViolation(kinds)

    scene_text = (case.description or "").strip()
    if not scene_text:
        raise ValueError(
            "AI triage requires case.description so M1 and the deterministic "
            "parser can independently reconcile the same investigator notes."
        )

    orch = orchestrator or PRAMAANAIOrchestrator()

    ai = orch.analyze_text(
        scene_text,
        m1_result=m1_result,
        run_m3=run_m3,
        run_m4=run_m4,
    )

    text_guardrail = ai["guardrail"]
    twins = ai["digital_twins"]

    # The visual branch is independent of the text GuardRail.  Earlier builds
    # returned here when the text parsers disagreed, which meant a perfectly
    # valid uploaded image never reached M2/M5.  Run requested visual models
    # first so a NEEDS_REVIEW text state does not masquerade as "M2/M5 did not
    # run".  Visual outputs remain candidate-only and never bypass GuardRail.
    visual = {"m2": [], "m5": [], "unlinked_visual_candidates": []}
    paths = list(image_paths or [])
    if paths:
        visual = orch.analyze_images(
            paths,
            twins=twins,
            run_m2=run_m2,
            run_m5=run_m5,
            save_annotated=save_annotated,
        )

    ai["visual"] = visual
    if visual.get("model_runtime"):
        ai["model_runtime"] = visual["model_runtime"]
    ai["summary"] = {
        "guardrail_state": text_guardrail.get("state"),
        "reconciled_exhibits": len(twins),
        "m2_detections": sum(x.get("detection_count", 0) for x in visual.get("m2") or []),
        "m4_contradictions": len((ai.get("m4") or {}).get("contradictions") or []),
        "m5_shadow_candidates": sum(len(x.get("candidates") or []) for x in visual.get("m5") or []),
        "unlinked_visual_candidates": len(visual.get("unlinked_visual_candidates") or []),
        "images_received": len(paths),
        "m2_requested": bool(paths and run_m2),
        "m5_requested": bool(paths and run_m5),
    }
    final_gate = _final_gate(text_guardrail, visual)

    # Never feed unresolved parser disagreements into EPI/scheduling.  The AI
    # control layer (including requested M2/M5) still completes and is returned
    # so investigators can review every available signal.
    if not text_guardrail.get("triage_allowed"):
        return {
            "status": final_gate.get("state", "NEEDS_REVIEW"),
            "case_ref": case.case_ref,
            "case_id": None,
            "ai": ai,
            "final_gate": final_gate,
            "triage": None,
            "message": (
                "AI control layer completed, including requested visual models. "
                "Deterministic EPI/FSL triage is held until the GuardRail issues are reviewed."
            ),
        }

    ai_items = _items_from_twins(twins)
    # Preserve unmatched classified candidates during NEEDS_REVIEW so the
    # investigator receives a complete provisional evidence queue instead of
    # an empty/no-result screen. GuardRail still prevents final submission.
    provisional_items = _items_from_reconciliation_union(ai.get("reconciliation") or {})
    merged_items = _merge_items(case.items, ai_items + provisional_items)
    if not merged_items:
        raise ValueError("Reconciliation passed but produced no triageable exhibits.")

    # Critical design point: clear description so the legacy _resolve_items path
    # cannot run a second LLM extraction and silently bypass reconciliation.
    deterministic_case = case.model_copy(
        deep=True,
        update={
            "items": merged_items,
            "description": None,
        },
    )

    triage = run_triage(
        deterministic_case,
        llm=NullLLM(),
        store=store,
        actor=actor,
        persist=persist,
        action="ai_guarded_triage",
        use_llm_narrative=False,
    )
    triage_dict = triage.model_dump(mode="json")
    _attach_triage_to_twins(twins, triage_dict)

    # Visual AI already ran above, before the text GuardRail gate.
    message = (
        "AI-controlled deterministic triage completed."
        if final_gate["state"] == "READY"
        else "Provisional triage completed. EPI, preservation, sequencing and FSL results are available, but final submission requires investigator review."
    )

    envelope = {
        "status": final_gate["state"],
        "case_ref": case.case_ref,
        "case_id": triage.case_id,
        "ai": ai,
        "final_gate": final_gate,
        "triage": triage_dict,
        "message": message,
    }

    # Persist only the AI-control/provenance layer separately. The deterministic
    # TriageResult remains unchanged and keeps its existing SHA-256 integrity path.
    if persist and store is not None:
        store.save_ai(
            triage.case_id,
            {
                "status": envelope["status"],
                "case_ref": case.case_ref,
                "final_gate": final_gate,
                "ai": ai,
                "message": message,
            },
        )
        store.append(
            actor,
            "ai_control_completed",
            {
                "status": final_gate["state"],
                "guardrail": text_guardrail.get("state"),
                "m1": (ai.get("model_runtime") or {}).get("m1", {}).get("status"),
                "m2": (ai.get("model_runtime") or {}).get("m2", {}).get("status"),
                "m3": (ai.get("model_runtime") or {}).get("m3", {}).get("status"),
                "m4": (ai.get("model_runtime") or {}).get("m4", {}).get("status"),
                "m5": (ai.get("model_runtime") or {}).get("m5", {}).get("status"),
                "visual_candidates": len(visual.get("unlinked_visual_candidates") or []),
            },
            case_id=triage.case_id,
        )

    return envelope
