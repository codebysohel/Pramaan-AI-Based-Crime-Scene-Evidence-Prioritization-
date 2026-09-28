# Security, legal and ethical design

## Legal anchors (India)

| Provision | How Pramaan uses it |
|---|---|
| **BNSS 2023 §176(3)** — forensic expert scene visit for offences punishable ≥ 7 years | Motivation: more scenes and exhibits for the same labs; the triage supports that visit. |
| **BNSS §184** — medical examination of a rape survivor, incl. DNA samples | `sexual_assault_kit` is `MANDATED_EXAMINATION`, statutory EPI floor 85, cold-chain flag. |
| **BNSS §187(3)** — 60/90-day custody limit before default bail | Custody deadline computed from `custody_start` and maximum punishment; reports due 7 days earlier drive scheduling. |
| **BSA 2023 §63** — certificate for electronic records | `DIGITAL_INTEGRITY` flag: hash exported CCTV and attach the certificate. |
| **BNS 2023 §72** — identity of sexual-offence victims | No names are accepted anywhere; privacy gate; synthetic scenarios never name anyone. |
| **DPDP Act 2023** — data minimisation | Only exhibit descriptions are processed; identifiers are rejected, not stored; privacy blocks log only the *kind* of identifier. |

## Controls in code (not in prompts)

* **Privacy gate** (`privacy.py`) on every surface: Aadhaar-format numbers, Indian mobile numbers, e-mail addresses, and optional case-specific protected terms supplied only as SHA-256 hashes (`PRAMAAN_PROTECTED_TERMS`).
* **Determinism & reproducibility:** rule-based scoring; KB SHA-256 and result SHA-256 on every run and on every packet page.
* **Tamper evidence:** SHA-256 hash-chained ledger (`hash = SHA-256(canonical{seq, ts, case_id, item_id, actor, action, payload, prev_hash})`), `verify()` pinpoints the first bad entry; `verify_case()` proves a stored result matches the hash recorded when it was produced; `audit.jsonl` mirror.
* **Human in the loop:** officer overrides require a reason and are logged; the FSL may re-order on scientific grounds (stated in every packet).
* **LLM containment:** optional; closed vocabulary; validated output; never scores; provider stamped on results.
* **MCP hardening:** stdio by default; HTTP endpoint with DNS-rebinding protection and host allow-list; tool errors never leak stack traces.
* **Supply chain & ops:** 7 runtime dependencies, no CDN in the dashboard (air-gap ready), Docker image runs as non-root, `.env` git-ignored.

## Known gaps before real deployment

Authentication/role-based access for the web app (put it behind the department's SSO/reverse proxy), encryption at rest for the database, signed timestamps (e.g. RFC 3161) anchoring the ledger head, and formal validation of the knowledge base with an FSL.
