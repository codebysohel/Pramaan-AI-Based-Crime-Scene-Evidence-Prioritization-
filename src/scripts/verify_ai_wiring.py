"""Live PRAMAAN-X M1-M5 wiring verifier.

Examples (from src):
    python scripts/verify_ai_wiring.py
    python scripts/verify_ai_wiring.py --image D:\\ibm\\test_scene.jpg --run-m5

The first command proves the text path M1/M3/M4. The second also executes M2
and M5 on a real image. Results are written to runtime/ai_wiring_report.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pramaan.ai_orchestrator import PRAMAANAIOrchestrator, get_ai_runtime_status

TEXT = (
    "A wet blood-stained shirt was recovered beside the victim's body. "
    "Three half-burnt cigarette butts were found 3 metres from the body. "
    "A kitchen knife was recovered underneath the bed."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", action="append", default=[], help="JPG/PNG path; repeat for multiple images")
    parser.add_argument("--run-m5", action="store_true", help="also execute Granite Vision M5")
    args = parser.parse_args()

    image_paths = [Path(x).expanduser().resolve() for x in args.image]
    missing = [str(x) for x in image_paths if not x.is_file()]
    if missing:
        parser.error("Image file not found: " + "; ".join(missing))
    if args.run_m5 and not image_paths:
        parser.error("--run-m5 requires at least one --image JPG/PNG path")

    orch = PRAMAANAIOrchestrator()
    print("\n[1/2] Running text path: M1 -> reconciliation -> M3 -> M4")
    text_result = orch.analyze_text(TEXT, run_m3=True, run_m4=True)

    visual = {"m2": [], "m5": [], "unlinked_visual_candidates": []}
    if image_paths:
        print("\n[2/2] Running image path: M2" + (" + M5 (all five requested)" if args.run_m5 else ""))
        for image_path in image_paths:
            print(f"      image: {image_path}")
        visual = orch.analyze_images(
            image_paths,
            twins=text_result["digital_twins"],
            run_m2=True,
            run_m5=args.run_m5,
            save_annotated=True,
        )
    else:
        print("\n[2/2] No --image supplied; M2/M5 intentionally not executed.")

    status = get_ai_runtime_status()
    print("\nPRAMAAN-X MODEL STATUS")
    print("=" * 78)
    for key in ("m1", "m2", "m3", "m4", "m5"):
        row = status[key]
        print(f"{key.upper():<3} | {row['name']:<22} | {row['status']:<18} | last={row['last_inference_at'] or '-'}")
        if row.get("error"):
            print(f"    ERROR: {row['error']}")

    report = {
        "model_runtime": status,
        "guardrail": text_result.get("guardrail"),
        "reconciliation_counts": (text_result.get("reconciliation") or {}).get("counts"),
        "m3": text_result.get("m3"),
        "m4": text_result.get("m4"),
        "visual": visual,
    }
    out = Path("runtime/ai_wiring_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nReport: {out.resolve()}")

    required = ["m1", "m3", "m4"] + (["m2"] if args.image else []) + (["m5"] if args.image and args.run_m5 else [])
    failed = [m for m in required if status[m]["status"] == "ERROR" or not status[m]["last_inference_at"]]
    if failed:
        print("FAILED/NOT EXECUTED:", ", ".join(x.upper() for x in failed))
        return 1
    print("PASS: requested models completed inference.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
