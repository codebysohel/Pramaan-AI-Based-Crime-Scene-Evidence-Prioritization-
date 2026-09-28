"""FSL network planning — how Pramaan scales from one laboratory to a state's whole forensic network.

Problem: one State FSL headquarters receives every exhibit while Regional FSLs sit under-used and the Central
FSL accepts referrals. Pramaan plans the network as one resource pool:

* each exhibit (all its examinations stay on one physical object) goes to the unit where it will be *completed*
  earliest, including transport time — list scheduling in priority order (tier, due date, EPI);
* per-unit, per-division examiner timelines are min-heaps, so planning is O(J · U · ops · log E):
  thousands of exhibits across dozens of cases plan in well under a second;
* the same planner answers capacity questions ("+2 DNA examiners at HQ") for budgeting and recruitment;
* every plan is reported next to the "everything to HQ" baseline.

Units, capacities and transport times live in knowledge/laboratory.yaml (`network:`) and are illustrative.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import Any

from .knowledge import KnowledgeBase
from .models import TriagedItem
from .scheduler import Job, _bench, build_jobs

TIER_RANK = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}


@dataclass
class Unit:
    id: str
    name: str
    kind: str
    transport_h: float
    examiners: dict[str, int]
    accepts: tuple[str, ...] = ("P1", "P2", "P3", "P4")

    def can_take(self, job: Job) -> bool:
        return job.tier in self.accepts and all(self.examiners.get(op.division, 0) > 0 for op in job.ops)


@dataclass
class Assignment:
    job: Job
    case_id: str
    unit: str
    completion_h: float
    due_h: float | None
    ops: list[tuple[str, int, float, float]] = field(default_factory=list)  # (division, examiner, start, end)

    @property
    def late(self) -> bool:
        return self.due_h is not None and self.completion_h > self.due_h


def load_units(kb: KnowledgeBase, add_examiners: dict[str, int] | None = None, hq_only: bool = False) -> list[Unit]:
    raw = kb.network or [{"id": "SFSL-HQ", "name": kb.lab.get("name", "State FSL"), "kind": "SFSL", "transport_h": 0,
                   "examiners": {d: int(v.get("examiners", 1)) for d, v in kb.divisions.items()}}]
    units = [Unit(id=u["id"], name=u["name"], kind=u.get("kind", "FSL"), transport_h=float(u.get("transport_h", 0)),
                  examiners={k: int(v) for k, v in u["examiners"].items()}, accepts=tuple(u.get("accepts", ("P1", "P2", "P3", "P4"))))
             for u in raw]
    if add_examiners:
        hq = units[0]
        for div, n in add_examiners.items():
            hq.examiners[div] = max(0, hq.examiners.get(div, 0) + int(n))
    return units[:1] if hq_only else units


def _due(job: Job) -> float | None:
    ds = [d for d in (job.quality_due, job.report_due) if d is not None]
    return min(ds) if ds else None


def _simulate(kb: KnowledgeBase, unit: Unit, heaps: dict[str, list[tuple[float, int]]], job: Job, commit: bool):
    t = _bench(kb, unit.transport_h)
    ops = []
    for op in job.ops:
        heap = heaps[op.division]
        if commit:
            free, ex = heapq.heappop(heap)
            start = max(t, free)
            end = start + op.hours
            heapq.heappush(heap, (end, ex))
        else:
            free, ex = heap[0]
            # later ops in the same division on this job cannot reuse the examiner before `end`; approximate with max
            start = max(t, free)
            end = start + op.hours
        ops.append((op.division, ex, start, end))
        t = end
    return t, ops


def plan_network(kb: KnowledgeBase, cases: list[tuple[str, list[TriagedItem], float | None]], *,
                 hq_only: bool = False, add_examiners: dict[str, int] | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    units = load_units(kb, add_examiners, hq_only)
    heaps: dict[str, dict[str, list[tuple[float, int]]]] = {
        u.id: {d: [(0.0, i) for i in range(n)] for d, n in u.examiners.items() if n > 0} for u in units}
    jobs: list[tuple[str, Job]] = []
    for case_id, items, hours_left in cases:
        for j in build_jobs(kb, [i for i in items if i.stage == 1], hours_left):
            jobs.append((case_id, j))
    jobs.sort(key=lambda cj: (TIER_RANK.get(cj[1].tier, 9), _due(cj[1]) if _due(cj[1]) is not None else 1e12, -cj[1].epi))
    out: list[Assignment] = []
    unplaced: list[str] = []
    for case_id, job in jobs:
        best = None
        for u in units:
            if not u.can_take(job):
                continue
            done, _ = _simulate(kb, u, heaps[u.id], job, commit=False)
            if best is None or done < best[0] - 1e-9:
                best = (done, u)
        if best is None:
            unplaced.append(f"{case_id}/{job.label}")
            continue
        done, ops = _simulate(kb, best[1], heaps[best[1].id], job, commit=True)
        out.append(Assignment(job=job, case_id=case_id, unit=best[1].id, completion_h=done, due_h=_due(job), ops=ops))
    per_day = float(kb.lab.get("bench_hours_per_day", 8))
    makespan = max((a.completion_h for a in out), default=0.0)
    p1 = [a.completion_h for a in out if a.job.tier == "P1"]
    units_out = []
    for u in units:
        mine = [a for a in out if a.unit == u.id]
        busy = {}
        for a in mine:
            for div, _, s, e in a.ops:
                busy[div] = busy.get(div, 0.0) + (e - s)
        span = max((a.completion_h for a in mine), default=0.0)
        cap = sum(u.examiners.values()) * span
        bott = max(((d, h / (u.examiners[d] * span)) for d, h in busy.items() if span and u.examiners.get(d)),
                   key=lambda x: x[1], default=(None, 0.0))
        units_out.append({"id": u.id, "name": u.name, "kind": u.kind, "transport_h": u.transport_h, "examiners": u.examiners,
                          "exhibits": len(mine), "p1": sum(a.job.tier == "P1" for a in mine),
                          "busy_hours": round(sum(busy.values()), 1), "busy_days": round(span / per_day, 1),
                          "utilisation": round(sum(busy.values()) / cap, 3) if cap else 0.0,
                          "bottleneck": bott[0], "bottleneck_utilisation": round(bott[1], 3),
                          "division_hours": {k: round(v, 1) for k, v in sorted(busy.items())}})
    return {
        "mode": "hq_only" if hq_only else "network", "add_examiners": add_examiners or {},
        "exhibits": len(out), "cases": len(cases), "unplaced": unplaced,
        "makespan_days": round(makespan / per_day, 1),
        "p1_mean_days": round(sum(p1) / len(p1) / per_day, 2) if p1 else None,
        "late": sum(a.late for a in out), "units": units_out,
        "plan_seconds": round(time.perf_counter() - t0, 4),
        "assignments": [{"case_id": a.case_id, "exhibit": a.job.label, "tier": a.job.tier, "unit": a.unit,
                         "completion_day": round(a.completion_h / per_day, 2), "late": a.late} for a in out[:400]],
    }


def compare(kb: KnowledgeBase, cases, add_examiners: dict[str, int] | None = None) -> dict[str, Any]:
    hq = plan_network(kb, cases, hq_only=True, add_examiners=add_examiners)
    net = plan_network(kb, cases, add_examiners=add_examiners)
    summary = (f"{net['exhibits']} stage-1 exhibits from {net['cases']} case(s). Network plan: P1 results in "
               f"{net['p1_mean_days']} working days vs {hq['p1_mean_days']} with everything at HQ; queue clears in "
               f"{net['makespan_days']} vs {hq['makespan_days']} days; late exhibits {net['late']} vs {hq['late']}. "
               f"Planned in {net['plan_seconds'] * 1000:.0f} ms. Bottleneck at HQ: "
               f"{next((u['bottleneck'] for u in net['units'] if u['id'] == net['units'][0]['id']), '-')}.")
    return {"summary": summary, "hq_only": hq, "network": net}


def scale_benchmark(n_cases: int = 10, items_per_case: int = 200, seed: int = 2019,
                    add_examiners: dict[str, int] | None = None) -> dict[str, Any]:
    """Many Hyderabad-scale cases at once: engine throughput + network plan vs HQ-only."""
    from .benchmark import synthetic_case
    from .knowledge import load_kb
    from .pipeline import run_triage
    kb = load_kb()
    t0 = time.perf_counter()
    cases = []
    for k in range(n_cases):
        case, _ = synthetic_case(items_per_case, seed + k)
        r = run_triage(case, persist=False, use_llm_narrative=False)
        left = None if not r.custody_deadline else (r.custody_deadline - r.reference_time).total_seconds() / 3600
        cases.append((f"SYN-{k + 1:03d}", r.items, left))
    triage_s = time.perf_counter() - t0
    total = n_cases * items_per_case
    comp = compare(kb, cases, add_examiners)
    return {"cases": n_cases, "exhibits": total, "triage_seconds": round(triage_s, 2),
            "exhibits_per_second": round(total / triage_s, 1) if triage_s else None, **comp}
