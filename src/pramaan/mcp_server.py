"""Pramaan MCP server — the forensic triage engine as typed tools for any MCP client.

Modelled on the SAVVYDFIR-MCP pattern: a purpose-built MCP server whose *reasoning*
lives in versioned knowledge YAML (not in the model), whose findings carry caveats and
"corroborate with" guidance, and whose actions land in a hash-chained audit trail.

Transports
----------
* stdio            — ``python -m pramaan.mcp_server`` (Claude Desktop / Claude Code /
                     VS Code / any MCP client; see ``.mcp.json`` at the repo root)
* streamable HTTP  — served at ``/mcp`` by the web app (``python -m pramaan serve``), so an
                     MCP client and the dashboard share one live database.

Design rules
------------
* The client model reasons and talks; the engine decides. Every score, tier, flag and
  schedule comes from a deterministic, KB-hashed tool result, never from the model.
* State-changing tools append to the SHA-256 hash-chained ledger (and ``audit.jsonl``).
* A privacy gate in code rejects personal identifiers on every surface.
* Tool results are compact and ranked so they fit an agent's context window;
  ``detail="full"`` returns everything.
"""

from __future__ import annotations

import functools
import os
from datetime import datetime
from typing import Any, Literal, Optional

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import bsa, network, outputs, reports
from . import scheduler as scheduler_mod
from .config import ENGINE_VERSION, get_settings
from .extractor import parse_description
from .classifier import classify
from .knowledge import load_kb
from .llm.client import get_llm
from .models import CaseInput, ItemInput, SceneContext, TriageResult
from . import pipeline as engine
from .pipeline import CaseNotFound, run_triage
from .ai_pipeline import run_ai_triage
from .store import Store

ACTOR = os.getenv("PRAMAAN_MCP_ACTOR", "mcp-client")

INSTRUCTIONS = """\
Pramaan triages crime-scene exhibits for Indian State Forensic Science Laboratories.
Workflow: (1) list_crime_profiles if the crime type is unclear; (2) use analyze_scene_ai for PRAMAAN-X AI-controlled triage (preferred), or parse_scene_description + triage_scene for deterministic-only triage; (3) report GuardRail state before rank, flags and schedule;
(4) explain_item_priority for any exhibit the officer questions; (5) simulate_preservation /
update_item for what-ifs and corrections; (6) generate_submission_packet for the FSL.
For electronic evidence, use the BSA authenticity tools when court-readiness review is requested.
Always report ACT NOW items first. Quote EPI scores, tiers and flags exactly as returned — never
invent or adjust them. Never ask for or record names of victims, witnesses or accused.
"""


mcp = MCPServer(
    name="pramaan",
    title="Pramaan — crime-scene evidence triage",
    version=ENGINE_VERSION,
    instructions=INSTRUCTIONS,
)


TOOL_CATALOG: list[dict[str, str]] = []


def tool(fn):
    """Register an MCP tool whose input errors reach the client as readable ToolErrors."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except (ValueError, KeyError) as exc:  # includes pydantic ValidationError, PrivacyViolation, CaseNotFound
            msg = str(exc).strip('"') or exc.__class__.__name__
            raise ToolError(msg) from exc
    TOOL_CATALOG.append({"name": fn.__name__, "summary": (fn.__doc__ or "").strip().splitlines()[0]})
    return mcp.tool()(wrapper)


def _store() -> Store:
    return Store()


def _dashboard_url(case_id: str | None = None) -> str:
    s = get_settings()
    base = os.getenv("PRAMAAN_PUBLIC_URL", f"http://{s.api_host}:{s.api_port}")
    return f"{base.rstrip('/')}/#/case/{case_id}" if case_id else base


def _load_result(store: Store, case_id: str) -> TriageResult:
    case = store.get_case(case_id)
    if not case:
        raise ToolError(f"Unknown case '{case_id}'. Call list_cases to see available case IDs.")
    return TriageResult(**case["result"])


def _find_item(result: TriageResult, item: str):
    for it in result.items:
        if item in (it.item_id, it.label) or item.lower() == it.label.lower():
            return it
    raise ToolError(f"No exhibit '{item}' in case {result.case_id}. Labels: {', '.join(i.label for i in result.items[:30])}")


def compact_result(result: TriageResult, ledger_entry: dict[str, Any] | None = None, max_items: int = 40) -> dict[str, Any]:
    """Agent-sized view of a triage: act-now list, ranked table, gaps, schedule summary, integrity."""
    rows = []
    for it in result.items[:max_items]:
        rows.append({
            "rank": it.rank, "label": it.label, "type": it.classification.type_name, "tier": it.tier,
            "epi": it.score.epi, "stage": it.stage,
            "flags": [f.code for f in it.flags if f.severity in ("critical", "high", "medium", "info")],
            "divisions": it.divisions,
        })
    return {
        "case_id": result.case_id, "case_ref": result.case_ref, "crime": result.crime_label,
        "counts": result.counts,
        "act_now": [{"label": it.label, "type": it.classification.type_name, "flag": f.code, "action": f.message}
                    for it, f in reports.act_now(result)],
        "ranked": rows, "truncated": max(0, len(result.items) - max_items),
        "gaps": [{"severity": g.severity, "message": g.message, "action": g.action} for g in result.gaps],
        "schedule": result.schedule.summary,
        "custody_deadline": result.custody_deadline.isoformat() if result.custody_deadline else None,
        "parse_warnings": result.parse_warnings,
        "integrity": {"engine_version": result.engine_version, "kb_hash": result.kb_hash,
                      "result_sha256": result.result_sha256, "llm_provider": result.llm_provider,
                      "ledger_seq": ledger_entry.get("seq") if ledger_entry else None,
                      "ledger_hash": ledger_entry.get("hash") if ledger_entry else None},
        "dashboard": _dashboard_url(result.case_id),
    }


# ------------------------------------------------------------------- tools
@tool
def list_crime_profiles() -> dict[str, Any]:
    """List crime types Pramaan can triage, with the key investigative questions and scoring weights for each."""
    kb = load_kb()
    return {"kb_hash": kb.kb_hash, "profiles": [
        {"id": k, "label": v["label"], "max_punishment_years": v.get("max_punishment_years"),
         "key_questions": v.get("key_questions", []), "weights": v.get("weights") or kb.default_weights}
        for k, v in kb.profiles.items()
    ]}


@tool
def lookup_evidence_type(query: str, limit: int = 5) -> dict[str, Any]:
    """Search the forensic knowledge base for evidence types matching a word or phrase (e.g. 'beedi', 'DVR').

    Returns type ids usable as `type_hint`, the examinations each triggers, handling and caveats."""
    kb = load_kb()
    out = []
    for et in kb.search(query, limit=max(1, min(limit, 15))):
        out.append({"id": et.id, "name": et.name, "category": et.category,
                    "examinations": [kb.exams[e]["name"] for e in et.exam_plan],
                    "individualizing": et.individualizing, "degradation_profile": et.degradation,
                    "field_window_h": et.field_window_h, "handling": et.handling, "caveat": et.caveat})
    return {"query": query, "matches": out}


@tool
def parse_scene_description(description: str) -> dict[str, Any]:
    """Split free-text scene notes / a seizure list into exhibits and preview how each would be classified.

    Nothing is saved. Use this to confirm the exhibit list with the officer before triage_scene."""
    kb = load_kb()
    items, warnings = parse_description(kb, description)
    preview = []
    for i, item in enumerate(items, start=1):
        ci = classify(kb, item.description, item.location, item.type_hint)
        preview.append({"n": i, "label": item.label, "description": item.description, "location": item.location,
                        "quantity": item.quantity, "collected": item.collected, "condition": item.condition,
                        "type_id": ci.etype.id, "type": ci.etype.name, "confidence": ci.classification.confidence,
                        "method": ci.classification.method, "modifiers": ci.classification.modifiers,
                        "distance_m": ci.classification.distance_m})
    return {"items": preview, "warnings": warnings,
            "hint": "Correct any mis-classification with items[].type_hint when calling triage_scene."}


@tool
def triage_scene(
    case_ref: str,
    crime_type: str,
    description: Optional[str] = None,
    items: Optional[list[ItemInput]] = None,
    title: Optional[str] = None,
    incident_time: Optional[datetime] = None,
    reference_time: Optional[datetime] = None,
    scene_setting: Literal["outdoor", "indoor", "vehicle", "mixed"] = "outdoor",
    weather: Literal["dry", "rain", "humid"] = "dry",
    ambient_temp_c: Optional[float] = None,
    accused_in_custody: bool = False,
    custody_start: Optional[datetime] = None,
    photo_captions: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Classify, score (EPI), flag, stage and schedule every exhibit of a scene; saves the case and logs it.

    Provide `description` (free text, one exhibit per line) and/or structured `items`.
    `crime_type` is a profile id from list_crime_profiles (e.g. homicide, sexual_assault, burglary).
    Times are ISO-8601. Returns ACT NOW actions, the ranked list, gaps, the lab plan and integrity hashes."""
    case = CaseInput(
        case_ref=case_ref, crime_type=crime_type, title=title, incident_time=incident_time,
        reference_time=reference_time,
        scene=SceneContext(setting=scene_setting, weather=weather, ambient_temp_c=ambient_temp_c),
        accused_in_custody=accused_in_custody, custody_start=custody_start, items=list(items or []),
        description=description, photo_captions=list(photo_captions or []),
    )
    store = _store()
    result = run_triage(case, llm=get_llm(), store=store, actor=ACTOR)
    return compact_result(result, store.head())


@tool
def analyze_scene_ai(
    case_ref: str,
    crime_type: str,
    description: str,
    image_paths: Optional[list[str]] = None,
    title: Optional[str] = None,
    incident_time: Optional[datetime] = None,
    reference_time: Optional[datetime] = None,
    scene_setting: Literal["outdoor", "indoor", "vehicle", "mixed"] = "outdoor",
    weather: Literal["dry", "rain", "humid"] = "dry",
    ambient_temp_c: Optional[float] = None,
    accused_in_custody: bool = False,
    custody_start: Optional[datetime] = None,
    run_m5: bool = False,
) -> dict[str, Any]:
    """Run PRAMAAN-X AI GuardRail triage: M1+rules reconciliation, M3/M4 checks, optional M2/M5 images, then deterministic EPI/FSL scheduling.

    M2/M5 outputs are visual candidates only and never become evidence automatically.
    `image_paths` are local paths visible to the PRAMAAN server. M5 defaults off because it is CPU/RAM heavy.
    If GuardRail blocks the case, deterministic triage is not run.
    """
    case = CaseInput(
        case_ref=case_ref,
        crime_type=crime_type,
        title=title,
        incident_time=incident_time,
        reference_time=reference_time,
        scene=SceneContext(
            setting=scene_setting,
            weather=weather,
            ambient_temp_c=ambient_temp_c,
        ),
        accused_in_custody=accused_in_custody,
        custody_start=custody_start,
        items=[],
        description=description,
        photo_captions=[],
    )

    store = _store()
    envelope = run_ai_triage(
        case,
        image_paths=image_paths or [],
        store=store,
        actor=ACTOR,
        persist=True,
        run_m2=True,
        run_m3=True,
        run_m4=True,
        run_m5=run_m5,
        save_annotated=True,
    )

    ai = envelope.get("ai") or {}
    reconciliation = ai.get("reconciliation") or {}
    final_gate = envelope.get("final_gate") or {}

    control = {
        "status": envelope.get("status"),
        "final_gate": final_gate,
        "ai_summary": ai.get("summary") or {},
        "reconciliation_summary": reconciliation.get("summary") or {},
        "digital_twin_count": len(ai.get("digital_twins") or []),
        "model_runtime": ai.get("model_runtime") or {},
        "human_confirmation_required": final_gate.get("human_confirmation_required", True),
    }

    if not envelope.get("triage"):
        return {
            "case_ref": case_ref,
            "ai_control": control,
            "message": envelope.get("message"),
            "hint": "Resolve GuardRail issues before FSL submission.",
        }

    result = TriageResult(**envelope["triage"])
    return {
        "ai_control": control,
        "triage": compact_result(result, store.head()),
        "message": envelope.get("message"),
    }


@tool
def list_cases() -> dict[str, Any]:
    """List saved cases (newest first) with tier counts and evidential value retained by the lab plan."""
    return {"cases": _store().list_cases(), "dashboard": _dashboard_url()}


@tool
def get_case(case_id: str, detail: Literal["summary", "full"] = "summary") -> dict[str, Any]:
    """Fetch a saved case. `summary` is agent-sized; `full` returns every factor of every exhibit."""
    store = _store()
    result = _load_result(store, case_id)
    if detail == "full":
        return result.model_dump(mode="json")
    return compact_result(result, store.head())


@tool
def explain_item_priority(case_id: str, item: str) -> dict[str, Any]:
    """Explain WHY an exhibit got its tier and EPI: every factor, weight, flag, degradation estimate,
    examination sequence, what it does NOT prove, and what to corroborate it with. `item` = label or E-### id."""
    kb = load_kb()
    result = _load_result(_store(), case_id)
    it = _find_item(result, item)
    s, d = it.score, it.degradation
    contributions = {
        "probative": round(100 * s.weights["probative"] * s.probative, 1),
        "urgency": round(100 * s.weights["urgency"] * s.urgency, 1),
        "irreplaceable": round(100 * s.weights["irreplaceable"] * s.irreplaceable, 1),
    }
    return {
        "label": it.label, "description": it.description, "rank": it.rank, "tier": it.tier,
        "engine_tier": it.engine_tier, "stage": it.stage,
        "classification": it.classification.model_dump(),
        "epi": s.epi, "formula": "EPI = 100 x (w_p*P + w_u*U + w_r*R)", "factors": s.model_dump(),
        "points_by_factor": contributions, "rationale": it.rationale,
        "degradation": d.model_dump(),
        "flags": [f.model_dump() for f in it.flags],
        "exam_sequence": [st.model_dump() for st in it.exam_sequence],
        "caveat": it.caveat, "corroborate_with": it.corroborate_with, "handling": it.handling,
        "notes": it.notes, "kb_hash": kb.kb_hash,
        "what_would_change_it": _levers(it),
    }


def _levers(it) -> list[str]:
    out = []
    d = it.degradation
    if d.better_condition and d.hours_to_risk_if_preserved:
        out.append(f"Preserve as '{d.better_condition}': usable window {d.hours_to_risk} h -> {d.hours_to_risk_if_preserved} h "
                   "(try simulate_preservation).")
    if it.classification.distance_m is None and it.classification.category in ("biological", "trace", "weapon"):
        out.append("State the distance from the body / point of offence (e.g. '3 m from the body'): proximity raises probative value.")
    if it.classification.confidence < 0.6:
        out.append("Classification confidence is low — confirm the type with lookup_evidence_type and set type_hint.")
    if it.stage == 2:
        out.append("Held for stage 2: the officer can override with update_item(override_tier=..., override_reason=...).")
    return out


@tool
def update_item(case_id: str, item: str, changes: dict[str, Any], reason: str) -> dict[str, Any]:
    """Correct or update one exhibit and re-triage the whole case (logged in the ledger with `reason`).

    Allowed keys in `changes`: condition, collected, collected_at, location, quantity, type_hint, description,
    label, override_tier (P1-P4), override_reason. Example: {"condition": "refrigerated"} or
    {"override_tier": "P1", "override_reason": "Complainant states accused smoked here"}."""
    if not reason or len(reason.strip()) < 5:
        raise ToolError("A reason (at least 5 characters) is required; it is written to the chain-of-custody ledger.")
    store = _store()
    try:
        result = engine.update_item(store, case_id, item, changes, actor=ACTOR)
    except CaseNotFound as exc:
        raise ToolError(f"Unknown case '{case_id}'") from exc
    except KeyError as exc:
        raise ToolError(str(exc).strip('"')) from exc
    store.append(ACTOR, "update_reason", {"reason": reason.strip()[:300], "changes": changes}, case_id=case_id, item_id=item)
    return compact_result(result, store.head())


@tool
def simulate_preservation(case_id: str, item: str,
                          condition: Literal["ambient", "hot", "wet", "sunlight", "refrigerated", "frozen", "dry_sealed"]) -> dict[str, Any]:
    """What-if: how many hours of usable quality, EPI points and case-level value does moving one exhibit to
    `condition` buy? Nothing is saved."""
    try:
        return engine.simulate_preservation(_store(), case_id, item, condition)
    except CaseNotFound as exc:
        raise ToolError(f"Unknown case '{case_id}'") from exc
    except KeyError as exc:
        raise ToolError(str(exc).strip('"')) from exc


@tool
def build_fsl_schedule(case_id: str, max_ops: int = 60) -> dict[str, Any]:
    """The examination plan for the FSL: which division examines which exhibit when (bench hours / working days),
    division loads, and measured comparison against first-in-first-out and static-priority baselines."""
    kb = load_kb()
    result = _load_result(_store(), case_id)
    rec = result.schedule.recommended
    per_day = float(kb.lab.get("bench_hours_per_day", 8))
    ops = [{"label": o.label, "exam": o.exam_name, "division": o.division, "examiner": o.examiner,
            "start_day": round(o.start_h / per_day, 2), "end_day": round(o.end_h / per_day, 2),
            "quality_at_start": o.quality_at_start} for o in rec.ops[:max_ops]]
    return {
        "policy": rec.policy, "summary": result.schedule.summary, "ops": ops, "ops_truncated": max(0, len(rec.ops) - max_ops),
        "divisions": [d.model_dump() for d in rec.divisions],
        "comparison": {name: {"value_retained": r.value_retained, "perishable_value_retained": r.perishable_value_retained,
                              "late": r.late_count, "p1_mean_days": r.p1_mean_completion_days, "makespan_days": r.makespan_days}
                       for name, r in [("pramaan", rec)] + list(result.schedule.baselines.items())},
        "held_items": result.schedule.held_items, "bench_hours_held": result.schedule.bench_hours_held,
    }


@tool
def lab_queue() -> dict[str, Any]:
    """Plan ONE FSL queue across all saved cases (the lab's real problem): recommended policy vs handling cases
    in arrival order. Uses each case's stage-1 exhibits and custody deadlines."""
    kb = load_kb()
    store = _store()
    cases = []
    for row in reversed(store.list_cases()):  # oldest first = arrival order
        res = _load_result(store, row["case_id"])
        hours_left = None
        if res.custody_deadline:
            hours_left = (res.custody_deadline - res.reference_time).total_seconds() / 3600.0
        cases.append((res.case_id, res.items, hours_left))
    comp = scheduler_mod.plan_lab(kb, cases)
    rec = comp.recommended
    return {"summary": comp.summary, "policy": rec.policy, "cases": len(cases),
            "first_20": [{"exhibit": i.label, "tier": i.tier, "start_day": round(i.first_start_h / float(kb.lab.get('bench_hours_per_day', 8)), 2)}
                         for i in rec.items[:20]],
            "divisions": [d.model_dump() for d in rec.divisions]}


@tool
def gap_analysis(case_id: str) -> dict[str, Any]:
    """What is MISSING from the exhibit list for this crime type (reference samples, scene-litter sweep, CCTV
    canvass, photo coverage...), with the follow-up action for each gap."""
    result = _load_result(_store(), case_id)
    return {"case_id": case_id, "gaps": [g.model_dump() for g in result.gaps]}


@tool
def generate_submission_packet(case_id: str) -> dict[str, Any]:
    """Build the FSL submission packet AND the full output bundle (state.json, audit.jsonl, report.html, graph.html,
    packet.md, packet.pdf) under the case folder. Returns the packet Markdown so it can be saved to case-notes/<case_id>.md."""
    store = _store()
    result = _load_result(store, case_id)
    files = outputs.export_case(store, case_id)
    head = store.head()
    store.append(ACTOR, "packet_generated", {"result_sha256": result.result_sha256,
                                            "ledger_head": head["hash"] if head else None}, case_id=case_id)
    base = _dashboard_url().rstrip("/")
    return {"case_id": case_id, "markdown": reports.packet_markdown(result, store.head()), "files": files,
            "pdf_path": files["packet.pdf"], "markdown_path": files["packet.md"],
            "suggested_case_note": f"case-notes/{case_id}.md",
            "urls": {k: f"{base}/api/cases/{case_id}/{k}" for k in ("packet.pdf", "report.html", "graph.html", "state.json", "audit.jsonl")}}


@tool
def export_case_outputs(case_id: str) -> dict[str, Any]:
    """Write the case output bundle (state.json, audit.jsonl, report.html, graph.html, packet.md, packet.pdf) — the
    artefacts a reviewer or court receives. Deterministic; safe to call repeatedly."""
    store = _store()
    _load_result(store, case_id)
    files = outputs.export_case(store, case_id)
    store.append(ACTOR, "outputs_exported", {"files": sorted(files)}, case_id=case_id)
    base = _dashboard_url().rstrip("/")
    return {"case_id": case_id, "files": files,
            "urls": {k: f"{base}/api/cases/{case_id}/{k}" for k in ("report.html", "graph.html", "state.json", "audit.jsonl")}}


@tool
def record_custody_event(case_id: str, item: str,
                         event: Literal["sealed", "handed_over", "received", "opened_for_examination", "resealed", "returned", "note"],
                         from_party: Optional[str] = None, to_party: Optional[str] = None,
                         seal_intact: Optional[bool] = None, note: Optional[str] = None) -> dict[str, Any]:
    """Append a chain-of-custody event for one exhibit to the tamper-evident ledger. Parties are ROLES or
    designations (e.g. 'IO', 'Malkhana', 'FSL-Serology'), never personal names."""
    result = _load_result(_store(), case_id)
    it = _find_item(result, item)
    entry = _store().append(ACTOR, f"custody:{event}", {
        "label": it.label, "from": from_party, "to": to_party, "seal_intact": seal_intact, "note": (note or "")[:300],
    }, case_id=case_id, item_id=it.item_id)
    return {"recorded": True, "seq": entry["seq"], "hash": entry["hash"], "prev_hash": entry["prev_hash"]}


@tool
def verify_custody_ledger(case_id: Optional[str] = None) -> dict[str, Any]:
    """Recompute the SHA-256 hash chain of the whole ledger (detects edited/deleted/reordered entries) and, if a
    case is given, prove its stored triage result still matches the hash recorded when it was produced."""
    store = _store()
    out: dict[str, Any] = {"ledger": store.verify()}
    if case_id:
        out["case"] = store.verify_case(case_id)
    return out


@tool
def record_electronic_evidence(case_id: str, item: str, details: dict[str, Any], reason: str) -> dict[str, Any]:
    """Record BSA 2023 s.63 facts for an electronic exhibit (CCTV/DVR, phone, computer) and re-triage.

    `details` keys: acquisition (original_device|forensic_image|exported_copy|screen_capture|printout), source_kind, device,
    device_id, record_description, hash_algorithm, hash_at_acquisition, hash_at_lab, acquired_at, regular_use,
    ordinary_course, operating_properly, derived_from_ordinary_course (s.63(2)(a)-(d)), clock_offset_s, write_blocker_used,
    certificate_part_a, part_a_signatory_role, certificate_part_b, expert_role. Roles/designations only — never names."""
    if not reason or len(reason.strip()) < 5:
        raise ToolError("A reason (at least 5 characters) is required; it is written to the chain-of-custody ledger.")
    store = _store()
    case = store.get_case(case_id)
    if not case:
        raise ToolError(f"Unknown case '{case_id}'")
    result = TriageResult(**case["result"])
    it = _find_item(result, item)
    if not bsa.is_electronic(it):
        raise ToolError(f"{it.label} is a {it.classification.type_name}, not an electronic record (BSA s.63 applies to digital exhibits).")
    current = outputs.electronic_input(case, it.item_id)
    merged = {**(current.model_dump(mode="json") if current else {}), **details}
    new = engine.update_item(store, case_id, it.item_id, {"electronic": merged}, actor=ACTOR)
    store.append(ACTOR, "bsa63_facts_recorded", {"reason": reason.strip()[:300], "fields": sorted(details)}, case_id=case_id, item_id=it.item_id)
    after = next(i for i in new.items if i.item_id == it.item_id)
    return {"case_id": case_id, "item": after.label, "authenticity": after.authenticity.model_dump() if after.authenticity else None,
            "flags": [f.code for f in after.flags]}


@tool
def assess_evidence_authenticity(case_id: str, item: Optional[str] = None) -> dict[str, Any]:
    """Authenticity & reliability readiness of every exhibit under BSA 2023 ss.61-63 (electronic records: route, s.63(2)
    conditions, s.63(4) certificate Part A/B, hash recorded/verified) and BNSS s.105 / chain-of-custody facts for all
    exhibits. Status READY | CURABLE_GAPS | AT_RISK with remedies. Decision support — the court decides admissibility."""
    store = _store()
    _load_result(store, case_id)
    rep = outputs.authenticity(store, case_id)
    if item:
        rep["items"] = [r for r in rep["items"] if item in (r["label"], r["item_id"])]
    for r in rep["items"]:
        a = r["assessment"]
        r["open_items"] = [{"id": c["id"], "law": c["law"], "status": c["status"], "remedy": c["remedy"]}
                           for c in a["checks"] if c["status"] in ("FAIL", "MISSING")]
        if r["assessment"]["kind"] == "physical":
            r["assessment"] = {k: a[k] for k in ("kind", "status", "score", "summary")}
    rep.pop("law", None)
    return rep


@tool
def generate_bsa63_certificate(case_id: str, item: str) -> dict[str, Any]:
    """Draft the BSA 2023 s.63(4) Schedule certificate (Part A for the person in charge of the device, Part B for the expert)
    for an electronic exhibit, pre-filled with device particulars, s.63(2) statements and hash values; blanks for signatures."""
    store = _store()
    case = store.get_case(case_id)
    if not case:
        raise ToolError(f"Unknown case '{case_id}'")
    result = TriageResult(**case["result"])
    it = _find_item(result, item)
    if not bsa.is_electronic(it):
        raise ToolError(f"{it.label} is not an electronic record.")
    folder = get_settings().cases_dir / case_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"bsa63_certificate_{reports.safe_filename(it.label)}.pdf"
    path.write_bytes(bsa.certificate_pdf(result, it, outputs.electronic_input(case, it.item_id)))
    store.append(ACTOR, "bsa63_certificate_drafted", {"label": it.label}, case_id=case_id, item_id=it.item_id)
    return {"case_id": case_id, "item": it.label, "pdf_path": str(path),
            "url": f"{_dashboard_url().rstrip('/')}/api/cases/{case_id}/items/{it.item_id}/bsa63-certificate.pdf",
            "note": "Draft — to be signed: Part A by the person in charge of the device, Part B by an expert."}


@tool
def plan_fsl_network(add_division: Optional[str] = None, add_examiners: int = 0) -> dict[str, Any]:
    """Scale-out plan: assign every open stage-1 exhibit to the State FSL HQ, Regional FSLs or CFSL (referral) where it
    completes earliest (incl. transport), compared with sending everything to HQ. Optional capacity what-if: add examiners
    to one HQ division (e.g. add_division='DNA', add_examiners=2)."""
    kb = load_kb()
    store = _store()
    cases = []
    for row in reversed(store.list_cases()):
        res = _load_result(store, row["case_id"])
        left = None if not res.custody_deadline else (res.custody_deadline - res.reference_time).total_seconds() / 3600
        cases.append((res.case_id, res.items, left))
    extra = {add_division.upper(): add_examiners} if add_division and add_examiners else None
    comp = network.compare(kb, cases, extra)
    for k in ("hq_only", "network"):
        comp[k].pop("assignments", None)
    return comp


@tool
def describe_tool_catalog() -> dict[str, Any]:
    """List every Pramaan tool with a one-line summary (call this instead of hard-coding the tool list)."""
    kb = load_kb()
    return {"server": "pramaan", "engine_version": ENGINE_VERSION, "kb_hash": kb.kb_hash,
            "tool_count": len(TOOL_CATALOG), "tools": TOOL_CATALOG,
            "workflow": ["list_crime_profiles", "analyze_scene_ai", "parse_scene_description", "triage_scene", "explain_item_priority",
                         "simulate_preservation / update_item", "build_fsl_schedule", "generate_submission_packet",
                         "export_case_outputs", "record_electronic_evidence / assess_evidence_authenticity",
                         "generate_bsa63_certificate", "plan_fsl_network",
                         "record_custody_event", "verify_custody_ledger"]}


# --------------------------------------------------------------- resources
@mcp.resource("pramaan://knowledge/evidence-types", mime_type="text/markdown",
              description="All evidence types in the knowledge base with category and examinations.")
def evidence_types_resource() -> str:
    kb = load_kb()
    lines = [f"# Evidence types (KB {kb.kb_hash[:12]})", "", "| id | name | category | examinations |", "|---|---|---|---|"]
    for et in kb.types.values():
        lines.append(f"| {et.id} | {et.name} | {et.category} | {', '.join(kb.exams[e]['name'] for e in et.exam_plan)} |")
    return "\n".join(lines)


@mcp.resource("pramaan://knowledge/crime-profiles", mime_type="text/markdown",
              description="Crime profiles: relevance by category, weights and expected-evidence gap rules.")
def crime_profiles_resource() -> str:
    kb = load_kb()
    lines = [f"# Crime profiles (KB {kb.kb_hash[:12]})", ""]
    for k, v in kb.profiles.items():
        w = v.get("weights") or kb.default_weights
        lines.append(f"## {k} — {v['label']}")
        lines.append(f"weights {w}; relevance {v.get('relevance', {})}")
        for g in v.get("gaps", []) or []:
            lines.append(f"- gap `{g['id']}`: {g['message']}")
        lines.append("")
    return "\n".join(lines)


@mcp.resource("pramaan://case/{case_id}/packet", mime_type="text/markdown",
              description="FSL submission packet (Markdown) for a saved case.")
def case_packet_resource(case_id: str) -> str:
    store = _store()
    return reports.packet_markdown(_load_result(store, case_id), store.head())


# ----------------------------------------------------------------- prompts
@mcp.prompt(title="Triage a new crime scene")
def triage_new_scene(crime_type: str, notes: str) -> str:
    """Guided triage of a new scene from the officer's notes."""
    return (
        f"Triage this {crime_type} scene with the Pramaan tools. First call parse_scene_description on the notes "
        "and show me the exhibit list as a table so I can confirm it. Then call triage_scene. Report ACT NOW items "
        "first, then the top 10 ranked exhibits with tier, EPI and flags exactly as returned, then the gaps, then the "
        "lab-plan summary. Do not invent scores. Do not include any personal names.\n\nNotes:\n" + notes
    )


def main() -> None:
    """Entry point for the stdio transport (what an MCP client launches)."""
    import sys
    get_settings().ensure_dirs()
    if "--http" in sys.argv:  # standalone HTTP MCP (the web app also serves /mcp)
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
