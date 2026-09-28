---
name: court-ready-outputs
description: Use when the user asks for the FSL packet, forwarding letter, report, evidence graph, case export, or to finish/close a triage case. Produces and verifies the output bundle (state.json, audit.jsonl, report.html, graph.html, packet.md, packet.pdf) and writes the case note.
user-invocable: true
---

# Court-ready outputs

1. `verify_custody_ledger(case_id)` — both the ledger chain and the stored result hash must be ok; otherwise stop and report.
2. `generate_submission_packet(case_id)` — writes the whole bundle and logs `packet_generated` (this satisfies the Stop-hook completion gate).
3. Write the returned `markdown` verbatim to `case-notes/<case_id>.md` — your only writable location.
4. Reply with: the file URLs (`packet.pdf`, `report.html`, `graph.html`, `state.json`, `audit.jsonl`); one line per P1 exhibit with its caveat; the integrity line `KB <12> · result <12> · ledger seq <n>`.
5. Regenerate any time with `export_case_outputs(case_id)` — outputs are deterministic from the stored result.
