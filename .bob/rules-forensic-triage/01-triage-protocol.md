# PRAMAAN-X triage protocol

Activate the `evidence-triage-workflow` skill for every new scene (or `/triage-scene`).

1. If the crime type is unclear, call `list_crime_profiles` and ask the officer to choose.
2. For a new scene, prefer `analyze_scene_ai` with the officer's description. Supply `image_paths` only when the PRAMAAN server can read those local paths. Keep `run_m5=false` for the normal fast path; use M5 only for a deliberate shadow-scan demo.
3. Because `analyze_scene_ai` persists the case, use the normal MCP approval flow. Do not silently bypass approval.
4. Report `ai_control.final_gate` / GuardRail state before forensic ranking. If BLOCKED, stop and report the issues. If NEEDS_REVIEW, state exactly what requires human confirmation before submission.
5. Treat M2 YOLO-World and M5 Granite Vision results as visual candidates only. Never automatically promote a visual candidate into confirmed evidence. A missing visual detection never means evidence is absent.
6. After a successful triage, answer in this order: **GuardRail state** → **ACT NOW** actions → top exhibits (rank, label, tier, EPI, flags) → gaps → lab-plan summary → integrity hashes.
7. For "why" questions call `explain_item_priority` and cite `points_by_factor` and the caveat.
8. For preservation questions call `simulate_preservation`; for corrections or disagreement use `update_item` with a clear `reason` (overrides need `override_reason`).
9. Record hand-overs with `record_custody_event` using roles (IO, Malkhana, FSL-DNA), never names.
10. Finish with `generate_submission_packet` and write its `markdown` to `case-notes/<case_id>.md`. Tell the officer the dashboard link and PDF path.

Fallback: use `parse_scene_description` + `triage_scene` only when the officer explicitly requests deterministic-only triage or the AI control layer is unavailable.
