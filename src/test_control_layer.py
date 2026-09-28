import json
from pathlib import Path

from pramaan.reconciliation import reconcile_scene
from pramaan.guardrail import evaluate_guardrail
from pramaan.digital_twin import build_digital_twins


SCENE = """
Suspected homicide scene.

A wet blood-stained shirt was recovered beside the victim's body.
Three half-burnt cigarette butts were found 3 metres from the body.
A kitchen knife was recovered from underneath the bed.
""".strip()


M1_FILE = Path(r"D:\ibm\m1_scene_output.json")
if M1_FILE.is_file():
    m1 = json.loads(M1_FILE.read_text(encoding="utf-8"))
else:
    # Portable fallback matching the known M1 demo output. This keeps pytest
    # collection from depending on one developer's D:\ibm folder.
    m1 = {
        "crime_type": "homicide",
        "items": [
            {"description": "blood-stained shirt", "quantity": 1, "location": "beside the victim's body", "condition": "wet", "source_text": "A wet blood-stained shirt was recovered beside the victim's body.", "source_verified": True},
            {"description": "cigarette butts", "quantity": 3, "distance_m": 3, "condition": "half-burnt", "source_text": "Three half-burnt cigarette butts were found 3 metres from the body.", "source_verified": True},
            {"description": "kitchen knife", "quantity": 1, "location": "underneath the bed", "source_text": "A kitchen knife was recovered from underneath the bed.", "source_verified": True},
        ],
    }


reconciliation = reconcile_scene(
    SCENE,
    m1,
)


guardrail = evaluate_guardrail(
    reconciliation,
    m1,
)


twins = build_digital_twins(
    reconciliation,
    guardrail=guardrail.to_dict(),
)


print("\n========== RECONCILIATION ==========")

print(
    json.dumps(
        reconciliation["counts"],
        indent=2,
    )
)


print("\n========== GUARDRAIL ==========")

print(
    json.dumps(
        guardrail.to_dict(),
        indent=2,
    )
)


print("\n========== DIGITAL TWINS ==========")

print(
    json.dumps(
        twins,
        indent=2,
    )
)