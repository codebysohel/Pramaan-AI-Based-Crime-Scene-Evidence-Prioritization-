# Law-enforcement module — evidence authenticity & reliability under the Bharatiya Sakshya Adhiniyam, 2023

> Decision support for the investigating team, not legal advice. The court decides admissibility; confirm with the Public Prosecutor / legal cell. A printable version generated from the code is in [`legal/BSA-2023-evidence-authenticity-analysis.pdf`](legal/BSA-2023-evidence-authenticity-analysis.pdf) (`python -m pramaan legal-pdf`).

## 1. Why this matters

The Bharatiya Sakshya Adhiniyam, 2023 (BSA) replaced the Indian Evidence Act, 1872 from **1 July 2024**. A perfectly triaged CCTV clip or phone extraction is worthless in court if it cannot be *proved*. Most failures are procedural and preventable: no hash at seizure, no certificate, the wrong signatory, an unexplained broken seal. Pramaan checks these **before the charge sheet**, while they can still be fixed.

## 2. Statutory basis and how the code implements it

| Provision | What it covers | Implementation (`src/pramaan/bsa.py`) |
|---|---|---|
| **BSA s.61** | An electronic/digital record is not denied admissibility merely because it is electronic; subject to s.63 it has the legal effect of other documents | every exhibit of category *digital* (mobile phone, CCTV/DVR, computer/storage) receives an electronic assessment; check `s61_recognition` |
| **BSA s.62** | Contents of electronic records are proved in accordance with s.63 | check `s62_route`: original device (primary route) vs computer output + certificate |
| **BSA s.63(1)** | A computer output (printed, stored, recorded, copied) is deemed a document if s.63 conditions are satisfied | `acquisition_quality`: original device / forensic image / exported copy with hash = PASS; screen capture / printout = ADVISORY |
| **BSA s.63(2)(a)** | Regular use of the device for an activity regularly carried on by the person in lawful control | `ElectronicRecord.regular_use` → `s63_2_a` |
| **BSA s.63(2)(b)** | Information of that kind regularly fed in the ordinary course | `ordinary_course` → `s63_2_b` |
| **BSA s.63(2)(c)** | Device operating properly, or malfunction did not affect the record/accuracy | `operating_properly` → `s63_2_c`; CCTV clock offset → `clock_sync` |
| **BSA s.63(2)(d)** | Record reproduces / is derived from ordinary-course input | `derived_from_ordinary_course` → `s63_2_d` |
| **BSA s.63(4) + Schedule** | Certificate accompanying the record each time it is submitted: **Part A** by the person in charge of the device, **Part B** by an expert, with hash value(s) | `cert_part_a`, `cert_part_b`, `hash_recorded`; `certificate_pdf()` drafts both parts pre-filled (device source tick-box, make/model, serial/IMEI/MAC, hash, s.63(2) statements) |
| Integrity | Hash recomputed at the FSL must equal the acquisition hash | `hash_verified`; mismatch → `HASH_MISMATCH` flag, status AT RISK |
| **BNSS 2023 s.105** | Search & seizure recorded by audio-video electronic means | `CaseInput.seizure_video_recorded` → `seizure_video` (electronic and physical) |
| **IT Act 2000 s.79A** | Government-notified Examiner of Electronic Evidence | Part B `expert_role` recorded by designation |
| Case law (under IEA s.65B, predecessor of BSA s.63) | *Anvar P.V. v. P.K. Basheer* (2014): certificate is a condition precedent for secondary electronic evidence; *Arjun Panditrao Khotkar v. Kailash Kushanrao Gorantyal* (2020): not required where the original device is produced | original-device route makes certificate checks *recommended*, all other routes *required* |
| *Pune Bar Association v. Union of India* (SC, 2026, as reported) | Any person with special skill in computer science / cyber forensics may sign Part B if the court is satisfied | expert designation is free text with the qualification basis |

## 3. The assessment

Every check returns **PASS**, **ADVISORY** (half credit), **MISSING**, **FAIL** or **NA**, with the provision, the requirement, the recorded detail and a concrete remedy.

* **Score (0–100)** = weighted share of credit over applicable checks — s.63(2)(a)-(d) 7.5 each; Part A 12.5; Part B 12.5; hash recorded 15; hash verified 10; mode of proof 5; acquisition quality 5; write-blocking 5 (storage/mobile); clock offset 3 (CCTV); BNSS s.105 video 5; custody checks from the ledger.
* **Status** — **AT RISK**: an adverse fact is recorded (hash mismatch, a s.63(2) condition stated unmet, a broken seal, a tampered stored result). **CURABLE GAPS**: a required item is missing (e.g. certificate not yet signed, hash not recorded). **READY**: every required statutory fact is recorded.
* **Physical exhibits** get parallel reliability checks: collection within the field window, in-situ photograph, BNSS s.105 video, sealing, every hand-over recorded, seal integrity at each hand-over, preservation in the recommended condition, integrity of the stored triage result.
* **Legal-readiness flags never change forensic priority** — they are added after tiering (`BSA63_DETAILS_MISSING`, `BSA63_CERTIFICATE_PENDING`, `BSA63_CONDITION_NOT_MET`, `HASH_MISMATCH`). A test asserts `tier == engine_tier`.

## 4. Law-enforcement team workflow

| Role | Does | Surface |
|---|---|---|
| Investigating Officer | records acquisition method, device particulars, SHA-256 at seizure, s.63(2) facts, BNSS s.105 video status | dashboard *Authenticity · BSA* tab, or Bob → `record_electronic_evidence` |
| Person in charge of the device (e.g. petrol-pump manager) | signs Part A | certificate draft `bsa63_certificate_<label>.pdf` |
| FSL cyber division / qualified expert | re-computes the hash on receipt (`hash_at_lab`), signs Part B | same draft; mismatch is flagged immediately |
| SHO / Malkhana | records seal and hand-over events | `record_custody_event` |
| Legal cell / Public Prosecutor | reviews READY / CURABLE GAPS / AT RISK before the charge sheet | `authenticity_report.pdf`, Bob mode 🛡️ *Law-Enforcement Legal Cell* (`/bsa-check`) |

## 5. Is the system itself lawful?

* **Data minimisation & victim protection** — the privacy gate rejects names, phone, Aadhaar and e-mail patterns on every input, now including the electronic-record fields (BNS 2023 s.72; DPDP Act 2023). Signatories are stored by designation; names are written by hand on the signed paper certificate.
* **No automated legal determination** — outputs are readiness statuses with remedies; nothing is filed automatically.
* **Auditability** — every recorded fact (`bsa63_facts_recorded`), certificate draft and custody event is appended to the SHA-256 hash-chained ledger; outputs carry KB and result hashes.
* **Transparency** — rules, weights and the statutory map are in source code, this document and the PDF.

## 6. Where to find it

`src/pramaan/bsa.py` (engine, PDFs) · `src/pramaan/models.py` (`ElectronicRecord`, `LegalCheck`, `AuthenticityAssessment`) · `src/pramaan/pipeline.py` (integration after tiering) · `src/pramaan/outputs.py` (`authenticity.json`, `authenticity_report.pdf`, certificate drafts in the case bundle) · API `/api/cases/{id}/authenticity[.pdf]`, `/api/cases/{id}/items/{item}/bsa63-certificate.pdf`, `/api/legal/bsa-analysis.pdf` · MCP `record_electronic_evidence`, `assess_evidence_authenticity`, `generate_bsa63_certificate` · tests `src/tests/test_bsa_network.py`.

Statutory text is summarised, not reproduced; verify against the official BSA text and its Schedule.
