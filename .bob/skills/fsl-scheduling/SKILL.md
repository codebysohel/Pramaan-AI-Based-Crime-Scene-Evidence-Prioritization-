---
name: fsl-scheduling
description: Use for questions about the forensic laboratory plan — which exhibits are examined first, division workload, when P1 results arrive, custody-deadline risk, staged testing, or planning one queue across all open cases.
user-invocable: true
---

# FSL scheduling

- One case: `build_fsl_schedule(case_id)`. All open cases: `lab_queue()`.
- Always present the recommended policy **with its baselines** (status quo = everything in listing order; FIFO and static sort on the stage-1 set):

| Policy | Value retained | Perishable value | Late | P1 mean days | Makespan days |
|---|---|---|---|---|---|

- Staging: the 3 most promising exhibits of a high-volume type go first; traces within 10 m of the body are never held; held items are examined only if stage 1 is uninformative.
- Custody: if `custody_deadline` exists, compare it with P1 completion and the makespan; flag divisions whose busy time exceeds the deadline minus 7 days.
- Never reorder exhibits yourself; if the officer wants a different order, use `update_item` overrides with reasons and re-quote the plan.
