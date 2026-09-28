# Knowledge base guide

The forensic reasoning of Pramaan lives in four YAML files in `src/pramaan/knowledge/` — reviewable by forensic scientists without reading Python. The loader (`pramaan/knowledge.py`) validates every cross-reference and refuses to start on an error (fail-closed). Any edit changes the KB SHA-256 recorded on new results, so old results remain reproducible against the old KB.

| File | Contents | Typical calibration |
|---|---|---|
| `laboratory.yaml` | `lab_profile` (bench hours/day), 9 divisions with examiner counts, 27 examinations (division, hours, stage 0–5, destructive, `after`) | Set real examiner counts and average bench hours for your FSL |
| `evidence_types.yaml` | 41 types; modifiers; context signals; staging | Add local terms to `keywords`; adjust `individualizing`, `replaceable`, `field_window_h`; refine caveats |
| `degradation.yaml` | `risk_threshold`, `lab_storage_condition`, 11 profiles × 7 conditions, `preservation_advice` | Replace heuristic half-lives with validated values |
| `crime_profiles.yaml` | default weights, common gaps, 11 crime profiles (relevance, weights, max punishment, key questions, gap rules) | Tune relevance per category and add state-specific gap rules |

## Adding an evidence type

```yaml
- id: ligature_mark_swab
  name: "Ligature mark swab"
  category: biological
  keywords: [ligature mark swab, neck swab]
  exam_plan: [dna_extraction_profiling]
  individualizing: 0.8
  replaceable: 0.0
  degradation: touch_dna
  caveat: "Touch DNA shows contact, not strangulation."
  corroborate_with: ["Post-mortem findings", "Ligature material"]
  handling: "Air-dry swab, paper envelope, refrigerate."
```

Run `pytest` — the KB validation test and scenario ground-truth tests will catch broken references or regressions.
