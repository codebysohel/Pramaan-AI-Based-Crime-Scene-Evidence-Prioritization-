---
name: tools-reference
description: Reference for the 21 Pramaan MCP tools — inputs, outputs, and which ones write to the custody ledger. Use when unsure how to call a Pramaan tool or how to interpret its result fields.
user-invocable: true
---

# Pramaan MCP tools (server `pramaan`)

| Tool | Inputs | Key outputs | Ledger |
|---|---|---|---|
| `describe_tool_catalog` | — | tools, workflow | |
| `list_crime_profiles` | — | id, label, key_questions, weights | |
| `lookup_evidence_type` | query, limit | id, examinations, handling, caveat | |
| `parse_scene_description` | description | items[] with type, confidence, method | |
| `triage_scene` | case_ref, crime_type, description and/or items[], incident_time, reference_time, scene_setting, weather, ambient_temp_c, accused_in_custody, custody_start, photo_captions, title | case_id, counts, act_now[], ranked[], gaps[], schedule, integrity, dashboard | ✓ |
| `list_cases` / `get_case` | case_id, detail | summary or full result | |
| `explain_item_priority` | case_id, item | factors, points_by_factor, rationale, degradation, flags, exam_sequence, caveat, what_would_change_it | |
| `update_item` | case_id, item, changes, reason | re-triaged summary | ✓ |
| `simulate_preservation` | case_id, item, condition | hours_to_risk / epi / tier / value from→to | |
| `build_fsl_schedule` | case_id, max_ops | ops by day, divisions, comparison | |
| `lab_queue` | — | cross-case plan | |
| `gap_analysis` | case_id | gaps[] | |
| `generate_submission_packet` | case_id | markdown, files, urls | ✓ |
| `export_case_outputs` | case_id | files, urls | ✓ |
| `record_electronic_evidence` | case_id, item, details (BSA s.63 facts), reason | authenticity, flags | ✓ |
| `assess_evidence_authenticity` | case_id, item? | counts, per-exhibit status/score/open_items | |
| `generate_bsa63_certificate` | case_id, item | pdf_path, url | ✓ |
| `plan_fsl_network` | add_division?, add_examiners? | network vs HQ-only plan, units, bottlenecks | |
| `record_custody_event` | case_id, item, event, from_party, to_party, seal_intact, note | seq, hash, prev_hash | ✓ |
| `verify_custody_ledger` | case_id (optional) | ledger.ok, case.ok | |

Items: label or `E-###`. Times: ISO-8601 with `+05:30`. Conditions: ambient, hot, wet, sunlight, refrigerated, frozen, dry_sealed. Errors return as tool errors with a readable reason — fix the input, do not retry blindly.
