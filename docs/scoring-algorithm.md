# Scoring, degradation, staging and scheduling — the algorithms

Everything here is deterministic. Given the same input and the same knowledge-base hash, Pramaan produces the same ranking and schedule (verified by `tests/test_engine.py::test_ranking_is_deterministic`). No language model computes or changes any number on this page.

## 1. Evidentiary Priority Index (EPI)

```
EPI = 100 × ( w_p · P  +  w_u · U  +  w_r · R )          weights per crime profile (default 0.55 / 0.30 / 0.15)

P  probative   = min(1, relevance[crime, category] × (0.35 + 0.65 × individualizing) × (0.8 + context))
U  urgency     = 1 / (1 + h / 24)      h = min(hours until quality < 60 %, field window remaining); stable → 0
R  irreplace.  = 1 − replaceable
```

* **relevance** — from `crime_profiles.yaml` (e.g. homicide: biological 1.0, digital 0.85, soil via *trace* 0.7).
* **individualizing** — from the evidence type, adjusted by modifiers (blood +0.10, semen +0.10, saliva +0.05, burnt −0.10).
* **context** — capped to [−0.10, +0.35]: near body +0.15, recovered from/at the instance of the accused +0.15, point of entry +0.10, weapon context +0.10, victim link +0.05. An explicit distance replaces the generic near-body boost with `0.15·e^(−d/25)`; beyond 10 m the "near body" signal is dropped. The `0.8 + context` form keeps a trace 2 m from the body above the same trace 40 m away (earlier `1 + context` saturated both at 1.0 — found by our benchmark).
* **Statutory floor** — types with `mandatory: BNSS_184` (sexual-assault evidence kit) are floored at EPI 85.

`explain_item_priority` returns the points contributed by each factor; they sum to the EPI.

## 2. Degradation model

```
Q(t) = 0.5 ^ ( Σ Δt_i / half_life[profile][condition_i] )
```

Two exposure phases: at the scene (scene condition: *wet* if raining outdoors, *hot* if ≥ 35 °C, else ambient) until collection, then the current storage condition. From `Q_now`: hours until `Q < 0.60` (the KB `risk_threshold`), the first better condition from `preservation_advice` and the hours it would buy. For items still at the scene, `field_window_h` (CCTV overwrite 168 h, GSR a few hours, impressions…) is reduced ÷ 6 for weather-sensitive evidence in rain.

Half-lives are **conservative planning heuristics** (clearly marked in `degradation.yaml`) chosen to rank relative perishability — wet swab ≪ dried stain ≪ firearm — and must be calibrated per laboratory.

## 3. Flags

| Code | Severity | Trigger |
|---|---|---|
| `COLLECT_NOW` | critical | not collected and field window < 48 h |
| `COLLECTION_WINDOW_PASSED` | high | not collected and window already passed |
| `PERISHABLE` | critical < 48 h, high < 72 h | hours to quality risk |
| `QUALITY_AT_RISK` | high | quality already ≤ threshold |
| `DIGITAL_OVERWRITE` / `DIGITAL_INTEGRITY` | critical / medium | DVR not seized / seized (hash + BSA §63 certificate) |
| `MANDATED_EXAMINATION` | critical | BNSS §184 samples |
| `VOLATILE_TOXICANTS`, `COLD_CHAIN_REQUIRED`, `DIGITAL_VOLATILE`, `TIME_CRITICAL_COLLECTION`, `SAFETY_UNLOAD_FIRST` | high | static per type |
| `SEQUENCE_DNA_BEFORE_PRINTS` | medium | both DNA and fingerprint divisions needed |
| `HEAT_DAMAGED_DNA` | medium | burnt biological/clothing |
| `STAGED_HOLD`, `REFERENCE_FOR_COMPARISON`, `OFFICER_OVERRIDE` | info/medium | post-tier rules (§5) |

## 4. Tiers

`P1` if EPI ≥ 60 **or** any critical flag · `P2` ≥ 45 · `P3` ≥ 30 · `P4` below (hold). Stable, non-perishable exhibits top out near EPI 65 because their urgency term is ~0, so a P1 without a critical flag needs both strong probative value and irreplaceability.

## 5. Post-tier rules (each leaves a visible flag)

1. **Staged testing.** For high-volume types (`staging.types`: cigarette butts, bottles/cups, litter, hair, fibres, glass, soil, paint, fire debris) with more than `first_round = 3` exhibits in a case, the three highest-EPI stay in stage 1 and the rest become **P4 / stage 2** with the reason. **Exemptions:** traces within 10 m of the body (or tagged near the body), officer overrides, and items with critical flags other than `PERISHABLE` (a held perishable exhibit still gets its preservation instruction).
2. **Reference promotion.** Reference samples (blood/buccal/FTA) are raised to the best tier of the P1/P2 DNA exhibits they are needed to interpret.
3. **Officer override.** `override_tier` requires `override_reason` (≥ 5 characters); both the reason and the change go to the ledger; the engine's own tier is kept in `engine_tier`.

## 6. Examination sequencing

Each exam in `laboratory.yaml` has a division, bench hours, a stage (0 documentation … 5 destructive) and optional `after` precedence. The exhibit's exams form a DAG; Kahn's algorithm with a priority queue on (stage, KB order) yields the least-destructive-first order. Hours scale with quantity: `× (1 + 0.5·(min(q, 6) − 1))`.

## 7. FSL scheduling

*Job shop with precedence and due dates.* Time unit: bench hours (8 per working day). Quality due time: when `Q` would cross the threshold in refrigerated lab storage. Report due time: BNSS §187(3) custody deadline (60 days, or 90 when the maximum punishment is ≥ 10 years) minus a 7-day drafting buffer.

At each step the division that can start earliest selects among ready operations using the rule under test:

```
ATC:  I = (w / p) · (ε + exp(−max(slack, 0) / (k · p̄)))      w = EPI/100 × (1.5 if urgent), ε = 0.05
slack = min(quality_due − remaining hours to first destructive step, report_due − remaining hours) − now
```

Portfolio: FIFO, static priority, ATC with k ∈ {0.5, 1, 2, 4}. Objective: `value_retained − 0.02·late − 0.002·P1_mean_days`, where *value retained* is the EPI-weighted evidential quality at the moment each exhibit's first destructive examination starts. Baselines always reported: **status quo** (all exhibits including held ones, listing order), **FIFO** and **static sort** (stage-1 set). Metrics are computed on the stage-1 set for every policy, so ordering and staging effects are separable.

## 8. Gap analysis

Crime-profile rules (`missing_any_type`, `missing_any_category`, `only_if_setting`, `only_if_category_present`) plus common gaps (reference samples, scene-litter sweep, CCTV canvass), one grouped photo-coverage alert for P1/P2 scene exhibits without a linked caption, and batch advice for multi-item DNA exhibits.
