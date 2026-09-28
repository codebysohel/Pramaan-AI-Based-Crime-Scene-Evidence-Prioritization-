# Flag playbook — what to tell the officer

| Flag | Severity | Say / do |
|---|---|---|
| `COLLECT_NOW` | critical | Still at the scene; collect within the stated hours (cast impressions, lift prints). |
| `COLLECTION_WINDOW_PASSED` | high | Collect anyway and record the delay; value may be reduced. |
| `DIGITAL_OVERWRITE` | critical | Seize the DVR/NVR or export footage with hash today; note clock offset. |
| `DIGITAL_INTEGRITY` | medium | Hash exported footage; attach the BSA 2023 §63 certificate. |
| `DIGITAL_VOLATILE` | high | Faraday bag / airplane mode; keep powered. |
| `PERISHABLE` | critical/high | Quote hours to risk and the better condition; offer `simulate_preservation`. |
| `QUALITY_AT_RISK` | high | Request immediate analysis; warn the FSL of partial results. |
| `VOLATILE_TOXICANTS` | high | Airtight container; headspace analysis first. |
| `COLD_CHAIN_REQUIRED` | high | 2–8 °C with a temperature log. |
| `MANDATED_EXAMINATION` | critical | BNSS §184 — forward without delay. |
| `SEQUENCE_DNA_BEFORE_PRINTS` | medium | Swab handling zones before powdering. |
| `HEAT_DAMAGED_DNA` | medium | Sample protected areas; expect partial profiles. |
| `STAGED_HOLD` | info | Held for stage 2; preserve anyway; an override needs a reason. |
| `REFERENCE_FOR_COMPARISON` | medium | Needed to interpret DNA results; send in the first batch. |
| `OFFICER_OVERRIDE` | info | Logged with its reason; the engine tier is shown alongside. |
