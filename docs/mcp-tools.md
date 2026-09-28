# MCP server reference

Server name `pramaan`, version = engine version. Transports: **stdio** (`python -m pramaan.mcp_server`) and **streamable HTTP** at `/mcp` inside `python -m pramaan serve`. Input errors are returned as MCP tool errors with a readable message (e.g. *Unknown case 'PRM-…'*, privacy rejection, missing override reason). State-changing tools write to the hash-chained ledger with actor `PRAMAAN_MCP_ACTOR` (default `mcp-client`).

## Tools (21)

| Tool | Purpose | Key inputs | Writes ledger |
|---|---|---|---|
| `describe_tool_catalog` | Live list of tools + recommended workflow | — | |
| `list_crime_profiles` | Crime types, key questions, weights | — | |
| `lookup_evidence_type` | Search the KB (e.g. "beedi", "DVR") → type ids for `type_hint` | `query`, `limit` | |
| `parse_scene_description` | Split free text into exhibits and preview classification (no save) | `description` | |
| `triage_scene` | Full triage; saves the case | `case_ref`, `crime_type`, `description` and/or `items[]`, times (ISO-8601), `scene_setting`, `weather`, `ambient_temp_c`, `accused_in_custody`, `custody_start`, `photo_captions` | ✓ |
| `list_cases` | Saved cases with counts | — | |
| `get_case` | Case summary or full result | `case_id`, `detail` = summary/full | |
| `explain_item_priority` | Factor points, rationale, degradation, flags, sequence, caveat, corroboration, levers | `case_id`, `item` (label or E-###) | |
| `update_item` | Correct/override one exhibit and re-triage | `case_id`, `item`, `changes`, `reason` | ✓ |
| `simulate_preservation` | What-if storage condition (not saved) | `case_id`, `item`, `condition` | |
| `build_fsl_schedule` | Operations by division/examiner/day + baselines | `case_id`, `max_ops` | |
| `lab_queue` | One schedule across all saved cases | — | |
| `gap_analysis` | Missing evidence and follow-up actions | `case_id` | |
| `generate_submission_packet` | Markdown + PDF packet (files under `PRAMAAN_HOME/cases/<id>/`) | `case_id` | ✓ |
| `export_case_outputs` | Write `state.json`, `audit.jsonl`, `report.html`, `graph.html`, `packet.md`, `packet.pdf` for a case | `case_id` | ✓ |
| `record_electronic_evidence` | Record BSA 2023 s.63 facts (acquisition, hashes, s.63(2)(a)-(d), certificate) for a digital exhibit | `case_id`, `item`, `details`, `reason` | ✓ |
| `assess_evidence_authenticity` | READY / CURABLE_GAPS / AT_RISK per exhibit with open items and remedies | `case_id`, `item` | |
| `generate_bsa63_certificate` | Draft s.63(4) Schedule certificate (Part A + Part B) | `case_id`, `item` | ✓ |
| `plan_fsl_network` | State network plan vs HQ-only + capacity what-if | `add_division`, `add_examiners` | |
| `record_custody_event` | sealed / handed_over / received / opened / resealed / returned / note (roles, not names) | `case_id`, `item`, `event`, `from_party`, `to_party`, `seal_intact`, `note` | ✓ |
| `verify_custody_ledger` | Recompute the hash chain; prove a stored result matches its recorded hash | `case_id` (optional) | |

## Resources

* `pramaan://knowledge/evidence-types` — Markdown table of all types and examinations
* `pramaan://knowledge/crime-profiles` — profiles, weights, gap rules
* `pramaan://case/{case_id}/packet` — the FSL packet for a case

## Prompt

* `triage_new_scene(crime_type, notes)` — guided workflow: parse → confirm → triage → report ACT NOW first, quote numbers exactly.

## Client configuration

IBM Bob: `.bob/mcp.json` is shipped (HTTP); `python -m pramaan mcp-config --client bob --transport stdio --write` switches it to stdio with absolute paths. See [bob-integration.md](bob-integration.md).

Generic clients — 
Project `.mcp.json` (repo root):

```json
{
  "mcpServers": {
    "pramaan": { "type": "stdio", "command": "python", "args": ["-m", "pramaan.mcp_server"], "env": { "PYTHONPATH": "src" } },
    "pramaan-http": { "type": "http", "url": "http://127.0.0.1:8000/mcp" }
  }
}
```

Absolute-path version for desktop clients: `python -m pramaan mcp-config`.

## Example session

`python -m pramaan mcp-demo` runs a real MCP client against the server and prints the transcript — see [`../demo/mcp-session-transcript.md`](../demo/mcp-session-transcript.md): tool listing, `triage_scene`, `explain_item_priority`, `simulate_preservation`, `record_custody_event`, a guard-rail rejection and `verify_custody_ledger`.
