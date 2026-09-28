# PRAMAAN-X M1-M5 wiring check

This build connects the AI modules to both **IBM Bob/MCP** and the **web UI**.

## What is connected

| Module | Model | Normal trigger | Visible in UI |
|---|---|---|---|
| M1 | IBM Granite 3.3 2B Instruct | every PRAMAAN-X text triage | AI Control tab/page |
| M2 | YOLO-World | attach JPG/PNG | AI Control visual candidates |
| M3 | MiniLM | every PRAMAAN-X text triage | AI Control model status + Digital Twins |
| M4 | DeBERTa NLI | every PRAMAAN-X text triage | AI Control contradictions/status |
| M5 | IBM Granite Vision | attach image + check M5 | AI Control visual shadow candidates |

Final EPI, degradation, examination sequencing and FSL scheduling remain deterministic.

## Run through the UI

1. From `src`, start `C:\Python314\python.exe -m pramaan serve`.
2. Open `http://127.0.0.1:8000`.
3. Open **AI control** in the left navigation. Initially models can show `NOT_LOADED` because they are lazy-loaded.
4. Choose **+ New triage** and enter scene notes.
5. Attach at least one JPG/PNG to execute M2.
6. Tick **Also run M5 Granite Vision** if you want all five models in the same run.
7. Click **Run PRAMAAN-X AI triage**.
8. The saved case opens on **AI Control · M1-M5**. `INFERENCE_OK` plus a UTC timestamp means the model actually ran.

## Run through IBM Bob

Bob's `analyze_scene_ai` uses the same `run_ai_triage` pipeline. M1/M3/M4 run for text; `image_paths` run M2; `run_m5=true` also runs M5. The AI snapshot is persisted separately and appears in the dashboard case's AI Control tab.

## Direct live verifier

From `src`:

```powershell
C:\Python314\python.exe scripts\verify_ai_wiring.py
```

For all five models:

```powershell
C:\Python314\python.exe scripts\verify_ai_wiring.py --image D:\ibm\test_scene.jpg --run-m5
```

A JSON report is written to `src\runtime\ai_wiring_report.json`.
