# Solution Overview

**Pramaan** (प्रमाण — "proof") is an explainable crime-scene evidence triage system for Indian forensic laboratories. It follows the pattern of [SAVVYDFIR-MCP](https://github.com/kismatkunwar89/SAVVYDFIR-MCP): a purpose-built **MCP server** whose forensic *reasoning* lives in versioned **knowledge YAML** rather than in a language model, whose findings carry **caveats** and **"corroborate with"** guidance, and whose actions land in a **hash-chained audit trail**. Around that engine we built a REST API, a web dashboard, a CLI and a printable FSL submission packet.

## What it does — end to end

1. **Intake.** The IO pastes the seizure list as written (`Ex-A2: half-burnt cigarette butt, 3 m from the body`) plus scene context (setting, weather, temperature, incident time, custody start). A deterministic parser splits lines, bullets and multi-object sentences, and extracts labels, quantities, storage conditions, distances and "not yet collected" status.
2. **Classification.** Each exhibit is mapped to one of **41 evidence types** in a closed vocabulary, plus modifiers (blood, semen, saliva, burnt, visible prints) and context signals (near the body, point of entry, recovered from the accused).
3. **Degradation.** Evidential quality is modelled as `Q = 0.5^(Σ Δt / half-life[condition])` across the scene and storage phases, giving *hours until quality falls below 60 %*, the best preservation condition and the time it would buy, and the remaining field window for evidence still at the scene.
4. **Evidentiary Priority Index (EPI, 0–100).** `EPI = 100 × (w_p·P + w_u·U + w_r·R)` — probative value (crime-type relevance × individualizing potential × contextual linkage), urgency (from the degradation model) and irreplaceability — with weights per crime profile and a statutory floor for mandated examinations (BNSS §184).
5. **Urgent-testing flags.** `COLLECT_NOW`, `DIGITAL_OVERWRITE`, `PERISHABLE`, `VOLATILE_TOXICANTS`, `COLD_CHAIN_REQUIRED`, `MANDATED_EXAMINATION`, `SEQUENCE_DNA_BEFORE_PRINTS`, `HEAT_DAMAGED_DNA`… Critical field actions are pulled into an **ACT NOW** list.
6. **Examination sequencing.** Each exhibit's examinations form a DAG (knowledge-base precedence + non-destructive-first stages) resolved with Kahn's algorithm — e.g. touch-DNA swabbing before powdering, headspace GC before toxicology screening.
7. **Tiers and staged testing.** P1 ≥ 60 or any critical flag, P2 ≥ 45, P3 ≥ 30, P4 hold. For high-volume types (butts, bottles, wrappers, fire debris…) only the three most promising go in the first submission; traces within 10 m of the body are never held. Reference samples are promoted to the tier of the DNA exhibits they enable. Officers can override any tier — with a mandatory reason written to the ledger.
8. **FSL schedule.** A job-shop simulation over the laboratory's divisions and examiners dispatches operations with a portfolio of rules (FIFO, static priority, Apparent Tardiness Cost with several look-ahead constants), is aware of quality due-dates and the BNSS §187(3) report deadline, and keeps the best plan — **always reported next to status-quo, FIFO and static-sort baselines**. A lab-wide view schedules one queue across all open cases.
9. **Gap analysis.** Compares the list with what the crime profile expects (reference samples, fingernail scrapings, scene-litter sweep, CCTV canvass) and with scene-photo captions.
10. **Outputs.** Dashboard, MCP tool results, and an **FSL submission packet** (PDF/Markdown): forwarding note, ACT NOW, ranked schedule, handling & caveats, held items, gaps, lab plan, method statement and integrity hashes, signature blocks.
11. **Integrity.** Every triage, re-triage, override, custody hand-over and packet is appended to a **SHA-256 hash-chained ledger** (SQLite + `audit.jsonl` mirror). The result hash and knowledge-base hash make every run verifiable and reproducible.

## Three surfaces, one engine

| Surface | For | How |
|---|---|---|
| **IBM Bob** (agent front-end) | Officers who prefer to talk to an assistant | `.bob/` modes, rules, hooks → MCP at `/mcp` ([guide](bob-integration.md)) |
| **MCP server** (21 tools, stdio + streamable HTTP) | IBM Bob or any MCP client | `python -m pramaan.mcp_server`, or `http://127.0.0.1:8000/mcp` |
| **Web dashboard + REST API** | IOs, FSL staff, supervisors | `python -m pramaan serve` → `http://127.0.0.1:8000` |
| **CLI** | Scripting, CI, air-gapped machines | `python -m pramaan triage <case.json> --packet out.pdf` |

Because the HTTP MCP endpoint and the dashboard run in one process over one database, a case triaged by an agent appears in the dashboard immediately, and the ledger shows both actors.

## Where AI fits — and where it must not

* The **ranking engine is deterministic and rule-based** by design: evidence may be contested in court, so the same inputs and knowledge-base hash must give the same answer, and every point must be explainable.
* The **optional IBM watsonx.ai (Granite 4)** layer follows *"the model proposes, the rules dispose"*: it may segment messy prose, choose an evidence type **from the closed vocabulary** when keyword rules are unsure (output validated; anything out of vocabulary is discarded), and draft the forwarding-note paragraph. It never produces or alters a score, tier or schedule; the provider used is stamped on every result. A test proves the score is identical whether the type came from the model or the rules.
* **IBM Bob** (or another MCP client) orchestrates tools and explains results in natural language, but quotes numbers only from tool results.

## Measured results (reproducible: `python -m pramaan benchmark`)

On a synthetic 200-exhibit scene with the shape of the Hyderabad case (seed 2019):

| Metric | Pramaan (atc(k=4)) | Status quo (everything, listing order) |
|---|---|---|
| Evidential value retained | **93.2%** | 85.5% |
| …of perishable exhibits | **90.9%** | 80.5% |
| Exhibits analysed after quality/report due date | **0** | 13 |
| P1 results, mean working days | **6.6** | 29.3 |
| Stage-1 work complete (working days) | **35** | 125 |
| Hidden "needle" exhibits surfaced as P1 | **5 / 5** (worst rank 36 of 200) | — |

124 low-value duplicates are held for stage 2 instead of queuing ahead of other cases. Triage of all 200 exhibits takes 0.42 s on a laptop. Details and honest caveats: [`evaluation.md`](evaluation.md).

## Innovation in one line each

* **Degradation-aware urgency** with quantified preservation what-ifs ("refrigerate: 42 h → 17 days").
* **Staged testing with a proximity exemption** — the rule that keeps the Hyderabad butt in the first batch.
* **Scheduling measured, not claimed** — every plan ships with its baselines.
* **Custody-deadline-aware** due dates from BNSS §187(3).
* **Explainability as a data structure** — factor points, rationale, caveat, corroboration, levers.
* **Integrity by construction** — knowledge-base hash, result hash, hash-chained ledger, privacy gate in code.
