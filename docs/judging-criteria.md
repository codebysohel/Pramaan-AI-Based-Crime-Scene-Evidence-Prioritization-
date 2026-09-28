# Evaluation criteria → evidence in the source code

## Technical implementation quality — "Was it actually built, and built well? Reads source code, not just the README"

| Claim | Where to read it |
|---|---|
| Deterministic, explainable scoring (EPI) with per-factor points | `src/pramaan/scoring.py`, `explain_item_priority` in `mcp_server.py` |
| Degradation model with preservation what-ifs | `src/pramaan/degradation.py`, `pipeline.simulate_preservation` |
| Examination DAG, least-destructive first (Kahn) | `src/pramaan/sequencing.py` |
| Job-shop scheduling portfolio (FIFO / static / ATC) with measured baselines | `src/pramaan/scheduler.py` |
| FSL network planner with heap timelines, capacity what-if | `src/pramaan/network.py` |
| BSA 2023 ss.61-63 authenticity engine + Schedule certificate drafting | `src/pramaan/bsa.py`, `models.ElectronicRecord` |
| Hash-chained custody ledger, result verification | `src/pramaan/store.py` |
| Privacy gate enforced in code on every surface | `src/pramaan/privacy.py` |
| Knowledge base validated fail-closed, hashed into every result | `src/pramaan/knowledge.py`, `knowledge/*.yaml` |
| Typed MCP server (21 tools) with readable ToolErrors | `src/pramaan/mcp_server.py` |
| REST API + no-CDN dashboard + CLI | `src/pramaan/api.py`, `src/web/`, `src/pramaan/cli.py` |
| IBM Bob integration: AGENTS.md, 7 skills, 4 modes, hooks with contract tests | `AGENTS.md`, `.bob/`, `src/pramaan/bob_hooks.py`, `src/tests/test_bob_config.py` |
| 46 automated tests, CI on every push | `src/tests/`, `.github/workflows/ci.yml` |

## Innovation & differentiation — "Does it solve the problem in a non-obvious way? Anchored in the code"

| Non-obvious idea | Code anchor |
|---|---|
| **Staged testing with a proximity exemption** — the 3 best of each high-volume type go first, but traces ≤ 10 m from the body are never held (keeps the Hyderabad cigarette butt in batch 1) | `pipeline._apply_staging` |
| **Degradation-aware urgency** — urgency is hours to evidential-quality loss, and preservation what-ifs quantify the time bought | `degradation.assess`, `scoring.score` |
| **Scheduling measured, not claimed** — every plan ships with status-quo / FIFO / static baselines | `scheduler.plan` |
| **Custody-deadline-aware due dates** from BNSS s.187(3) | `pipeline.custody_deadline`, `scheduler.build_jobs` |
| **Legal readiness decoupled from forensic priority** — BSA flags added after tiering (tested) | `pipeline.run_triage`, `test_bsa_network.py` |
| **Certificate drafting from structured facts** — Schedule Part A/B pre-filled with device particulars and hashes | `bsa.certificate_pdf` |
| **Network-level scale-out** — exhibit goes to the unit where it completes earliest incl. transport; CFSL referral only for P1/P2 | `network.plan_network` |
| **Reference-sample promotion** — reference samples inherit the tier of the DNA exhibits they unlock | `pipeline._promote_references` |
| **LLM proposes, rules dispose** — optional Granite picks a type from a closed list; a test proves the score is identical | `llm/tasks.py`, `test_engine.py::test_llm_proposes_type_but_rules_dispose` |
| **Agent guard-rails as code** — Bob hooks block personal data, protect the evidence store, audit MCP calls, and enforce a completion gate | `bob_hooks.py` |
