# Result pipeline fix

This build fixes the case where AI model inference completed but the Evidence Queue, Lab Plan, Gaps, Packet and other deterministic results did not appear.

## Behaviour
- `READY`: deterministic triage + final submission allowed.
- `NEEDS_REVIEW`: **provisional deterministic triage now runs** so EPI, preservation flags, examination order, FSL schedule, gaps, reports and case tabs remain available; final submission remains blocked until investigator review.
- `BLOCKED`: deterministic triage remains blocked for critical failures (for example, no reconciliation/no evidence).
- Unmatched but classified candidates from either parser are conservatively included in provisional triage instead of silently disappearing.
- M1-M5 remain perception/control signals; deterministic EPI and scheduling remain separate.

## Validation
- Python compileall passed.
- JavaScript syntax check passed.
- Engine + new GuardRail regression tests: 24 passed.
