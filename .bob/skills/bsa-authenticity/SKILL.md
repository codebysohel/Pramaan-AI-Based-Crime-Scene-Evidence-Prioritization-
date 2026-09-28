---
name: bsa-authenticity
description: Use when the user asks whether evidence is authentic, reliable or admissible, about BSA 2023 sections 61, 62 or 63, a section 63(4) / 65B certificate, hash values, CCTV/DVR or mobile-phone records as evidence, chain of custody for court, or wants the law-enforcement legal-cell review before the charge sheet.
user-invocable: true
---

# Evidence authenticity & admissibility readiness (BSA 2023)

Legal frame (summarise, do not over-state): BSA s.61 — an electronic record is not refused merely for being electronic; s.62 — its contents are proved under s.63; s.63(2)(a)-(d) — regular use, ordinary course, proper operation, derivation; s.63(4) + Schedule — certificate Part A (person in charge of the device) and Part B (expert) with hash value, attached every time the record is submitted. BNSS s.105 — audio-video recording of search & seizure. Pramaan reports readiness; **the court decides admissibility** and the Public Prosecutor advises.

## Workflow
1. `assess_evidence_authenticity(case_id)` → report counts (READY / CURABLE_GAPS / AT_RISK) and, for each electronic record, its route, score and `open_items`.
2. For each electronic exhibit with gaps, ask the officer for the missing facts (acquisition method, device make/model and serial/IMEI, SHA-256 at seizure, s.63(2) facts, clock offset for CCTV, write blocker, certificate status, signatory **designations**). Record them with `record_electronic_evidence(case_id, item, details, reason)`.
3. When the FSL re-computes the hash, record `hash_at_lab`. A mismatch (`HASH_MISMATCH`) makes the record AT RISK — say so plainly and recommend re-acquisition/expert explanation.
4. `generate_bsa63_certificate(case_id, item)` → give the officer the draft (Part A + Part B pre-filled; signatures by hand).
5. Physical exhibits: point out missing custody events (sealed, hand-overs, seal integrity) and in-situ photos; record with `record_custody_event`.
6. Finish with the authenticity report URL `/api/cases/<case_id>/authenticity.pdf` and the list of remaining actions by role (IO, person in charge, FSL expert, legal cell).

## Never
- Never write personal names into tool inputs — designations only; names go on the signed paper certificate.
- Never tell the officer a record "is admissible"; say "ready / curable gaps / at risk" and cite the check ids.
- Original-device route: the certificate is recommended, not required (Arjun Panditrao Khotkar, 2020, under the predecessor IEA s.65B) — still advise obtaining it.
