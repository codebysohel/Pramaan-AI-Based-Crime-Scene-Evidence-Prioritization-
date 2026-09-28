# PRAMAAN-X all-five model + UI fix

This build fixes the issues visible in the AI Control screenshot and the gated visual path.

## Fixed

- M2/M5 now run when images are supplied even if M1-vs-rules reconciliation returns `NEEDS_REVIEW`.
- The deterministic EPI/FSL engine still remains held until GuardRail review; visual AI never bypasses the gate.
- M2 memory is released before M5 and M5 memory is released after inference, while inference timestamps remain available as proof.
- Long browser image filenames are converted to short transport filenames and no longer hit the old 180-character validation error.
- M5 without an image is rejected immediately with a clear UI message.
- `NEEDS_REVIEW` is presented as an investigator-review outcome instead of a generic application error.
- AI model-status table header/row overlap has been removed; columns now wrap/scroll cleanly.
- Digital Twin confidence UI now reads the actual `label` field.
- Granite Vision dependency floor updated to `transformers>=4.49` to match the model's supported Transformers generation path.
- The wiring verifier now validates image paths and clearly reports all-five execution requests.

## Run all five

From `src`:

```powershell
C:\Python314\python.exe scripts\verify_ai_wiring.py --image D:\ibm\scene1.jpg --run-m5
```

Or start the dashboard, attach a JPG/PNG, tick **Also run M5 Granite Vision shadow scan**, and run PRAMAAN-X AI triage.

`INFERENCE_OK` plus a non-empty `last_inference_at` is the execution proof. A model may return zero candidates and still have executed successfully.
