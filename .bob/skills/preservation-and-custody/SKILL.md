---
name: preservation-and-custody
description: Use when the user asks how to preserve, package, store, refrigerate or seal an exhibit, what happens if storage changes, or wants to record a seal, hand-over, receipt or opening of an exhibit in the chain of custody.
user-invocable: true
---

# Preservation & custody

## Preservation what-if
1. `simulate_preservation(case_id, item, condition)` for `refrigerated`, `frozen` or `dry_sealed` (airtight can for volatiles) — nothing is saved.
2. Report usable window from → to, EPI and tier change, case value retained change. A tier *drop* after preservation is good news: the urgency is gone.
3. If the officer actually moved the exhibit, persist it: `update_item(..., changes={"condition": "<condition>"}, reason="moved to <condition> at <IST time>")`.

## Custody events
- `record_custody_event(case_id, item, event, from_party, to_party, seal_intact, note)`; events: sealed, handed_over, received, opened_for_examination, resealed, returned, note.
- Parties are ROLES (IO, SHO, Malkhana, FSL-DNA, FSL-Toxicology) — never names.
- Quote the returned `seq` and `hash`, then run `verify_custody_ledger(case_id)`.
- A seal recorded as not intact must be highlighted and mentioned in the case note.
