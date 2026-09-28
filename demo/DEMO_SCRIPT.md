# Demo script (≈4 minutes)

Record at 1440×900. Start the app with `python -m pramaan seed && python -m pramaan serve` (from `src/`).

| Time | Screen | Say |
|---|---|---|
| 0:00 | Title slide / README | "In the 2019 Hyderabad case, a DNA-bearing cigarette butt among 200+ exhibits was nearly missed while the FSL queue ran first-come-first-served. Pramaan makes triage explainable and measurable." |
| 0:20 | **New triage** → load *Roadside homicide* → Run | "The officer pastes the seizure list exactly as written. No names — the privacy gate rejects phone and Aadhaar numbers." |
| 0:45 | **Evidence queue** | "18 exhibits ranked. Six ACT NOW actions: impressions still at the scene, CCTV that overwrites, viscera at room temperature. Each bar shows *why*: probative value, urgency, irreplaceability." |
| 1:20 | Click **Ex-A17** → *refrigerated* | "Refrigerating the viscera buys 17 days — the engine quantifies the preservation instruction. Every factor, caveat and the examination sequence are here." |
| 1:50 | Click **Ex-A2** | "The half-burnt butt 3 m from the body is P1; six butts 40 m away are P2. Distance and linkage matter; the caveat reminds that DNA on a butt proves presence, not the act." |
| 2:15 | **Lab plan** | "The FSL schedule: degradation-aware and custody-deadline aware (BNSS §187(3)). Compared, not claimed: P1 results 2.1 vs 2.4 working days here." |
| 2:40 | **Benchmark** (200 exhibits) | "At Hyderabad scale, staged testing plus scheduling: 93% vs 85% evidential value, 0 vs 13 late exhibits, P1 results in ~7 instead of ~29 working days. All five hidden needles surface as P1." |
| 3:10 | **IBM Bob** in *🔬 Forensic Triage Officer* mode | "The officer can simply talk to IBM Bob. Bob calls the 16 Pramaan MCP tools — it never invents a score — and the case appears in the dashboard live. Type a phone number: the lifecycle hook blocks it." |
| 3:35 | **Custody ledger** → Verify | "Every triage, override and hand-over is SHA-256 hash-chained. Edit one row and verification pinpoints it." |
| 3:50 | **FSL packet** → Open PDF | "The packet the lab receives: ACT NOW, ranked schedule, handling, caveats, gaps, method statement and integrity hashes." |
