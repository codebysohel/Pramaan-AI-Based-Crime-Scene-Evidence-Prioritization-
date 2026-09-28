---
name: evidence-triage-workflow
description: REQUIRED when the user asks to triage a crime scene, prioritise exhibits or seized items, decide what to send to the FSL first, pastes a seizure list or scene notes, or references a Pramaan case id (PRM-...). Defines the 7-phase Pramaan triage methodology with mandatory tools, decision points and the completion gate.
user-invocable: true
---

# Evidence Triage Workflow — 7 phases

This is an investigation loop, not a checklist. The Pramaan MCP engine owns every score; you own the conversation, the corrections and the case note.

## Mandatory tools (the Stop hook and the completion promises check these)

| Tool | When | Rejected shortcut |
|---|---|---|
| `parse_scene_description` | before every new triage | triaging unconfirmed text |
| `triage_scene` | once per case (then `update_item` for changes) | "estimating" tiers yourself |
| `verify_custody_ledger` | before packet generation | skipping integrity |
| `generate_submission_packet` | after the last triage/retriage | ending the session without outputs |

## Phase 1 — Intake (one question round max)
Collect: crime type (map via `list_crime_profiles`), incident time (IST), triage reference time (default now), setting/weather/temperature, accused in custody + custody start. If something is unknown, proceed and say what it would change (e.g. no custody start → no report deadline).

## Phase 2 — Parse & confirm
Call `parse_scene_description(description)` and present:

| # | Label | Description | Type | Confidence |
|---|---|---|---|---|

Rows with confidence < 0.60 or method `fallback` → use skill `exhibit-classification`. Ask the officer to confirm the list once.

## Phase 3 — Triage
Call `triage_scene` with the confirmed description (plus `items[]` with `type_hint` for corrected rows). Answer in this order:
1. **ACT NOW** — numbered; exhibit label first; action + time window.
2. Top 10 ranked exhibits: rank, label, type, tier, EPI, flags — copied verbatim.
3. Gaps — severity, finding, action.
4. Lab-plan summary sentence **including** its baseline comparison.
5. Integrity line `KB <12> · result <12> · ledger seq <n>` and the dashboard link.

## Phase 4 — Explain & correct
- "Why is X P1/P4?" → `explain_item_priority` → cite `points_by_factor`, rationale, caveat, `what_would_change_it`.
- Officer disagrees → `update_item` with the corrected field, or `override_tier` + `override_reason`; always pass `reason`.
- Preservation question → skill `preservation-and-custody`.

## Phase 5 — Lab plan
Skill `fsl-scheduling`. Quote the recommended policy next to status quo / FIFO / static sort.

## Phase 6 — Custody
`record_custody_event` for seals and hand-overs (roles only), then `verify_custody_ledger(case_id)`; if not ok, STOP and report.

## Phase 7 — Outputs
Skill `court-ready-outputs`: `generate_submission_packet` → write `markdown` to `case-notes/<case_id>.md` → list the output URLs (report.html, graph.html, state.json, audit.jsonl, packet.pdf).

## Decision points
- Many near-identical items (butts, bottles, wrappers) → explain staged testing; do not try to promote them all.
- Accused in custody → state the custody deadline and whether P1 results fit before it.
- Outdoor impressions not collected in rain → ACT NOW is time-critical; say it first.

Reference: `references/flag-playbook.md` (what to tell the officer for each flag).
