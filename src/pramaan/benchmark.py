"""Reproducible benchmark: a synthetic, Hyderabad-scale scene (≈200 exhibits).

The 2019 case that motivates Pramaan involved 200+ physical items and 3,000+
photographs. We cannot use real case files, so this module generates a
*synthetic* exhibit list with the same shape — many near-duplicate litter items,
a few decisive biological traces, perishable toxicology, digital sources that
overwrite, impressions exposed to weather — from a fixed random seed, then
measures:

* throughput  — time to parse, classify, score and schedule the whole list;
* ranking     — where the "needle" exhibits (e.g. the DNA-bearing cigarette butt
                close to the body) land in the ranked list;
* scheduling  — evidential value retained, late exhibits and P1 time-to-result
                for Pramaan's recommended policy vs FIFO and a static score sort.

Everything is deterministic for a given seed, so the numbers in
``docs/evaluation.md`` can be reproduced with ``python -m pramaan benchmark``.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .models import CaseInput, SceneContext

# (template, weight). {d} = distance in metres, {n} = quantity, {loc} = place.
# Scene model: litter (butts, bottles, wrappers) accumulates where people wait —
# lorry parking, dhaba, bus shelter — 15–220 m from the body; only a handful of
# traces lie within a few metres. That is the Hyderabad pattern the needle tests.
_TEMPLATES: list[tuple[str, int]] = [
    ("cigarette butt {loc}, {d} m from the body", 14),
    ("{n} cigarette butts {loc}, {d} m from the body", 6),
    ("beedi stub {loc}", 5),
    ("empty liquor bottle {loc}, {d} m from the body", 7),
    ("plastic water bottle {loc}", 6),
    ("gutka packet {loc}", 8),
    ("paper cup {loc}", 5),
    ("chocolate wrapper {loc}", 5),
    ("matchbox {loc}", 4),
    ("strand of hair {loc}, {d} m from the body", 4),
    ("bloodstained stone {loc}, {d} m from the body", 3),
    ("blood stain on the culvert wall {loc}", 2),
    ("partly burnt cloth piece {loc}", 4),
    ("ash and fire debris sample {loc}", 2),
    ("empty petrol bottle {loc}, {d} m from the body", 2),
    ("footprints {loc}, not yet collected", 3),
    ("tyre impressions {loc}, not yet collected", 2),
    ("soil sample {loc}", 4),
    ("glass fragments {loc}", 3),
    ("broken tail-light pieces {loc}", 2),
    ("rope piece {loc}", 1),
    ("iron rod {loc}, {d} m from the body", 1),
    ("knife {loc}, {d} m from the body", 1),
    ("mobile phone {loc}", 2),
    ("CCTV of the petrol pump {loc}, not yet seized", 2),
    ("handwritten note {loc}", 2),
    ("footwear (single chappal) {loc}", 3),
    ("dupatta {loc}", 1),
    ("used condom {loc}", 1),
    ("syringe {loc}", 1),
    ("pesticide bottle {loc}", 1),
    ("fibres on the barbed fence {loc}", 2),
    ("paint smear on the lorry bumper {loc}", 1),
]
_LOCATIONS = [
    "near the culvert", "under the service road", "beside the lorry parking area", "near the toll plaza",
    "in the bushes", "on the embankment", "near the drain", "behind the dhaba", "at the bus shelter",
    "on the approach road", "near the transformer", "along the fence line",
]
_FIXED = [
    # The needles: exhibits a good triage must surface regardless of list position.
    ("NEEDLE-1", "half-burnt cigarette butt, 3 m from the body"),
    ("NEEDLE-2", "viscera preserved at autopsy, kept at ambient temperature"),
    ("NEEDLE-3", "CCTV DVR at the toll plaza covering the service road, not yet seized"),
    ("NEEDLE-4", "fingernail scrapings of the deceased collected at autopsy"),
    ("NEEDLE-5", "blood sample of the deceased for DNA reference (FTA card)"),
]


def synthetic_case(n_items: int = 200, seed: int = 2019) -> tuple[CaseInput, dict[str, str]]:
    """Return (case, {label: needle_id}) with ``n_items`` free-text exhibits (needles at random positions)."""
    rng = random.Random(seed)
    weights = [w for _, w in _TEMPLATES]
    lines: list[str] = []
    for _ in range(max(0, n_items - len(_FIXED))):
        tpl = rng.choices([t for t, _ in _TEMPLATES], weights=weights)[0]
        near = any(w in tpl for w in ("stone", "rod", "knife", "hair", "blood stain"))
        dist = rng.choice([2, 4, 6, 9, 12] if near else [15, 25, 40, 60, 90, 150, 220])
        lines.append(tpl.format(loc=rng.choice(_LOCATIONS), d=dist, n=rng.choice(["two", "three", "4", "5"])))
    positions = sorted(rng.sample(range(len(lines) + len(_FIXED)), len(_FIXED)))
    needles: dict[str, str] = {}
    for pos, (nid, text) in zip(positions, _FIXED):
        lines.insert(pos, text)
    labelled = []
    for i, text in enumerate(lines, start=1):
        label = f"Ex-B{i}"
        for nid, ntext in _FIXED:
            if text == ntext:
                needles[label] = nid
        labelled.append(f"{label}: {text}")
    incident = datetime(2026, 9, 25, 16, 0)
    case = CaseInput(
        case_ref="SYNTH-2019-SCALE (synthetic benchmark)", title="Synthetic Hyderabad-scale roadside scene",
        crime_type="homicide", incident_time=incident, reference_time=incident + timedelta(hours=18),
        scene=SceneContext(setting="outdoor", ambient_temp_c=30, weather="dry"),
        accused_in_custody=True, custody_start=incident + timedelta(hours=14),
        description="\n".join(labelled),
    )
    return case, needles


@dataclass
class BenchmarkReport:
    n_items: int
    seed: int
    seconds: float
    items_per_second: float
    needles: list[dict[str, Any]]
    policies: dict[str, dict[str, Any]]
    counts: dict[str, int]
    summary: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def run_benchmark(n_items: int = 200, seed: int = 2019) -> BenchmarkReport:
    from .pipeline import run_triage  # local import: pipeline imports heavy modules

    case, needles = synthetic_case(n_items, seed)
    t0 = time.perf_counter()
    result = run_triage(case, persist=False, use_llm_narrative=False)
    elapsed = time.perf_counter() - t0

    by_label = {i.label: i for i in result.items}
    needle_rows = []
    for label, nid in needles.items():
        it = by_label.get(label)
        if it:
            needle_rows.append({"needle": nid, "label": label, "listed_at": int(label.split("B")[1]),
                                "rank": it.rank, "tier": it.tier, "type": it.classification.type_id})
    needle_rows.sort(key=lambda r: r["needle"])

    def pol(r) -> dict[str, Any]:
        return {"policy": r.policy, "value_retained": r.value_retained,
                "perishable_value_retained": r.perishable_value_retained, "late": r.late_count,
                "p1_mean_days": r.p1_mean_completion_days, "makespan_days": r.makespan_days}

    policies = {"pramaan": pol(result.schedule.recommended)}
    policies.update({k: pol(v) for k, v in result.schedule.baselines.items()})
    return BenchmarkReport(
        n_items=len(result.items), seed=seed, seconds=round(elapsed, 3),
        items_per_second=round(len(result.items) / elapsed, 1) if elapsed else 0.0,
        needles=needle_rows, policies=policies, counts=result.counts, summary=result.schedule.summary,
    )
