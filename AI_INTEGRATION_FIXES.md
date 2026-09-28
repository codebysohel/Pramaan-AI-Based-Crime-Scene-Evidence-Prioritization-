# AI integration fixes in this build

Audit result: the previous build had all five adapter files and Bob's `analyze_scene_ai` path, but the web dashboard still submitted new cases to the legacy deterministic `/api/triage` endpoint. Also, the AI-control envelope was not persisted with the case, so the dashboard could not prove which models had run.

This build fixes that wiring:

1. The dashboard's primary **Run PRAMAAN-X AI triage** action now calls `/api/ai/triage`.
2. M1, M3 and M4 execute on the text path.
3. JPG/PNG attachments execute M2; an explicit checkbox enables M5.
4. The orchestrator records live per-model states: NOT_LOADED, LOADING, LOADED, INFERENCE_OK or ERROR, plus the last inference UTC timestamp.
5. AI-control data is persisted in a separate `case_ai` SQLite table, leaving the deterministic triage-result hash unchanged.
6. Cases created by IBM Bob through `analyze_scene_ai` now expose the same persisted AI data to the web UI.
7. A global **AI control** page shows live M1-M5 backend status.
8. Each AI-created case has an **AI Control · M1-M5** tab showing GuardRail, reconciliation, Digital Twins, M4 contradictions, M2 detections and M5 shadow candidates.
9. M2/M5 errors are visible rather than silently disappearing; visual candidates still require investigator confirmation.
10. `scripts/verify_ai_wiring.py` provides a direct command-line inference check.

The forensic boundary remains unchanged: M1-M5 do not directly set EPI. Final EPI, degradation, examination sequencing and FSL scheduling remain deterministic/auditable.
