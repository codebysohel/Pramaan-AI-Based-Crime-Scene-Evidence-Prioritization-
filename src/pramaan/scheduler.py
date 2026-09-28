"""Degradation-aware FSL examination scheduler.

Problem (a job shop with precedence and deadlines):
  * each exhibit is a job = its sequenced chain of examinations; one physical
    object, so its operations run strictly one after another;
  * each operation needs one examiner of one FSL division (limited capacity);
  * each exhibit has a *quality due time* (when its evidential quality drops
    below the KB risk threshold in lab storage) and optionally a *report due
    time* (BNSS §187(3) custody window minus a drafting buffer);
  * objective: maximise EPI-weighted evidential quality at the moment each
    exhibit is analysed, while minimising late exhibits.

Method: non-delay schedule generation with priority dispatching. At every
decision point the division that can start work earliest picks one ready
operation using a dispatching rule:
  * ``fifo``      — order of listing on the forwarding letter (status quo);
  * ``priority``  — static EPI order (what a naive "sort by score" gives you);
  * ``atc(k)``    — Apparent Tardiness Cost (Vepsalainen & Morton, 1987):
                      I = (w / p) * (eps + exp(-max(slack, 0) / (k * p_bar)))
                    which balances importance per bench-hour against how close
                    an exhibit is to losing quality.
We run a small portfolio (FIFO, priority, ATC for several k), keep the schedule with
the best objective, and ALWAYS report baselines next to it so the gain is
measured, not claimed:
  * ``status_quo`` — every exhibit, in listing order (what happens today);
  * ``fifo``       — the stage-1 exhibits only, in listing order;
  * ``priority``   — the stage-1 exhibits, static EPI order.
Quality/late/P1 metrics are computed over the stage-1 exhibits for every policy,
so the comparison is like-for-like; the status-quo makespan shows what staged
testing saves on top.

``plan_lab`` applies the same machinery to ALL open cases at once — the FSL's
real problem is one queue shared by many investigations.

Time unit: FSL bench hours from submission. Degradation happens in wall-clock
time, so bench hours are converted using ``bench_hours_per_day``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .degradation import lab_due_hours, quality_after
from .knowledge import KnowledgeBase
from .models import (
    DivisionLoad, ExamStep, ItemSchedule, ScheduledOp, ScheduleComparison, ScheduleResult, TriagedItem,
)

EPS = 0.05
ATC_KS = (0.5, 1.0, 2.0, 4.0)
REPORT_BUFFER_DAYS = 7.0


@dataclass
class Job:
    item_id: str
    label: str
    tier: str
    epi: float
    urgent: bool
    order: int
    ops: list[ExamStep]
    profile: str
    q0: float
    quality_due: float | None = None   # bench hours
    report_due: float | None = None    # bench hours
    first_destructive: int = 0
    results: list[ScheduledOp] = field(default_factory=list)


def _wall(kb: KnowledgeBase, bench_h: float) -> float:
    return bench_h * 24.0 / float(kb.lab.get("bench_hours_per_day", 8))


def _bench(kb: KnowledgeBase, wall_h: float) -> float:
    return wall_h * float(kb.lab.get("bench_hours_per_day", 8)) / 24.0


def build_jobs(kb: KnowledgeBase, items: list[TriagedItem], custody_hours_from_now: float | None) -> list[Job]:
    jobs: list[Job] = []
    for idx, it in enumerate(sorted(items, key=lambda i: i.item_id)):
        if not it.exam_sequence:
            continue
        due_wall = lab_due_hours(kb, it.degradation.profile, it.degradation.quality_now)
        report_due = None
        if custody_hours_from_now is not None:
            report_due = _bench(kb, max(0.0, custody_hours_from_now - REPORT_BUFFER_DAYS * 24.0))
        fd = next((i for i, op in enumerate(it.exam_sequence) if op.destructive), 0)
        jobs.append(Job(
            item_id=it.item_id, label=it.label, tier=it.tier, epi=it.score.epi, urgent=it.urgent,
            order=idx, ops=it.exam_sequence, profile=it.degradation.profile, q0=it.degradation.quality_now,
            quality_due=None if due_wall is None else _bench(kb, due_wall), report_due=report_due,
            first_destructive=fd,
        ))
    return jobs


def _priority_fn(rule: str, k: float):
    def fifo(job: Job, op_i: int, t: float, p_bar: float) -> float:
        return -job.order

    def static(job: Job, op_i: int, t: float, p_bar: float) -> float:
        return job.epi * 1000 - job.order

    def atc(job: Job, op_i: int, t: float, p_bar: float) -> float:
        w = (job.epi / 100.0) * (1.5 if job.urgent else 1.0)
        p = max(job.ops[op_i].hours, 0.1)
        slacks = []
        if job.quality_due is not None and op_i <= job.first_destructive:
            until = sum(o.hours for o in job.ops[op_i: job.first_destructive])
            slacks.append(job.quality_due - until - t)
        if job.report_due is not None:
            slacks.append(job.report_due - sum(o.hours for o in job.ops[op_i:]) - t)
        urgency = EPS if not slacks else EPS + math.exp(-max(min(slacks), 0.0) / (k * p_bar))
        return (w / p) * urgency

    return {"fifo": fifo, "priority": static, "atc": atc}[rule]


def simulate(kb: KnowledgeBase, jobs_in: list[Job], rule: str, k: float = 2.0,
             focus: set[str] | None = None, name: str | None = None) -> ScheduleResult:
    jobs = [Job(**{**j.__dict__, "results": []}) for j in jobs_in]
    intake = float(kb.lab.get("intake_hours", 2))
    free = {d: [0.0] * int(spec.get("examiners", 1)) for d, spec in kb.divisions.items()}
    ready = {j.item_id: intake for j in jobs}
    nxt = {j.item_id: 0 for j in jobs}
    prio = _priority_fn(rule, k)
    remaining = sum(len(j.ops) for j in jobs)

    while remaining:
        by_div: dict[str, list[Job]] = {}
        for j in jobs:
            if nxt[j.item_id] < len(j.ops):
                by_div.setdefault(j.ops[nxt[j.item_id]].division, []).append(j)
        best_div, best_t = None, math.inf
        for d, cands in by_div.items():
            t_d = max(min(free[d]), min(ready[c.item_id] for c in cands))
            if t_d < best_t:
                best_div, best_t = d, t_d
        assert best_div is not None
        conflict = [c for c in by_div[best_div] if ready[c.item_id] <= best_t + 1e-9]
        p_bar = sum(c.ops[nxt[c.item_id]].hours for c in conflict) / len(conflict)
        chosen = max(conflict, key=lambda c: (prio(c, nxt[c.item_id], best_t, p_bar), -c.order))
        op = chosen.ops[nxt[chosen.item_id]]
        ex = min(range(len(free[best_div])), key=lambda i: free[best_div][i])
        start = max(best_t, free[best_div][ex])
        end = start + op.hours
        free[best_div][ex] = end
        ready[chosen.item_id] = end
        chosen.results.append(ScheduledOp(
            item_id=chosen.item_id, label=chosen.label, exam_id=op.exam_id, exam_name=op.name,
            division=best_div, examiner=ex + 1, start_h=round(start, 2), end_h=round(end, 2),
            quality_at_start=round(quality_after(kb, chosen.profile, chosen.q0, _wall(kb, start)), 3),
        ))
        nxt[chosen.item_id] += 1
        remaining -= 1

    return _summarise(kb, jobs, free, name or (rule if rule != "atc" else f"atc(k={k:g})"), focus)


def _summarise(kb: KnowledgeBase, jobs: list[Job], free: dict[str, list[float]], policy: str,
               focus: set[str] | None = None) -> ScheduleResult:
    bench_per_day = float(kb.lab.get("bench_hours_per_day", 8))
    items: list[ItemSchedule] = []
    ops: list[ScheduledOp] = []
    num = den = pnum = pden = 0.0
    late = 0
    for j in jobs:
        ops.extend(j.results)
        analysis = j.results[min(j.first_destructive, len(j.results) - 1)]
        completion = j.results[-1].end_h
        q = analysis.quality_at_start
        is_late = bool(
            (j.quality_due is not None and analysis.start_h > j.quality_due)
            or (j.report_due is not None and completion > j.report_due)
        )
        due = [d for d in (j.quality_due, j.report_due) if d is not None]
        items.append(ItemSchedule(
            item_id=j.item_id, label=j.label, tier=j.tier, epi=j.epi,  # type: ignore[arg-type]
            first_start_h=j.results[0].start_h, completion_h=round(completion, 2),
            due_h=round(min(due), 2) if due else None, late=is_late, quality_at_analysis=q,
        ))
        if focus is not None and j.item_id not in focus:
            continue
        late += is_late
        w = j.epi / 100.0
        num += w * q
        den += w
        if j.quality_due is not None:
            pnum += w * q
            pden += w
    items.sort(key=lambda i: (i.first_start_h, i.item_id))
    ops.sort(key=lambda o: (o.start_h, o.division, o.examiner))
    loads = []
    for d, spec in kb.divisions.items():
        total = sum(o.end_h - o.start_h for o in ops if o.division == d)
        if total <= 0:
            continue
        busy = max(free[d])
        loads.append(DivisionLoad(
            division=d, name=spec.get("name", d), examiners=int(spec.get("examiners", 1)),
            total_hours=round(total, 1), busy_until_h=round(busy, 1), working_days=round(busy / bench_per_day, 1),
        ))
    loads.sort(key=lambda l: -l.busy_until_h)
    makespan = max((o.end_h for o in ops), default=0.0)
    p1 = [i.completion_h for i in items if i.tier == "P1" and (focus is None or i.item_id in focus)]
    return ScheduleResult(
        policy=policy, ops=ops, items=items, divisions=loads, makespan_h=round(makespan, 1),
        makespan_days=round(makespan / bench_per_day, 1),
        value_retained=round(num / den, 4) if den else 1.0, late_count=late,
        perishable_value_retained=round(pnum / pden, 4) if pden else None,
        p1_mean_completion_days=round(sum(p1) / len(p1) / bench_per_day, 2) if p1 else None,
    )


def _objective(r: ScheduleResult) -> float:
    """Evidential value first; each late exhibit costs 2 points; each P1 working day 0.2 points."""
    return r.value_retained - 0.02 * r.late_count - 0.002 * (r.p1_mean_completion_days or 0.0)


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _portfolio(kb: KnowledgeBase, jobs: list[Job]) -> tuple[ScheduleResult, ScheduleResult, ScheduleResult]:
    fifo = simulate(kb, jobs, "fifo")
    static = simulate(kb, jobs, "priority")
    # FIFO is in the portfolio too: if listing order is already best, the engine says so.
    portfolio = [static, fifo] + [simulate(kb, jobs, "atc", k) for k in ATC_KS]
    return max(portfolio, key=_objective), fifo, static


def _empty(summary: str) -> ScheduleComparison:
    empty = ScheduleResult(policy="none", ops=[], items=[], divisions=[], makespan_h=0, makespan_days=0,
                           value_retained=1.0, late_count=0, p1_mean_completion_days=None)
    return ScheduleComparison(recommended=empty, baselines={}, summary=summary)


def plan(kb: KnowledgeBase, items: list[TriagedItem], custody_hours_from_now: float | None) -> ScheduleComparison:
    all_jobs = build_jobs(kb, items, custody_hours_from_now)
    stage1_ids = {i.item_id for i in items if i.stage == 1}
    jobs = [j for j in all_jobs if j.item_id in stage1_ids]
    if not jobs:
        return _empty("No stage-1 examinations to schedule.")
    best, fifo, static = _portfolio(kb, jobs)
    held = [j for j in all_jobs if j.item_id not in stage1_ids]
    held_hours = round(sum(op.hours for j in held for op in j.ops), 1)
    baselines = {"fifo": fifo, "priority": static}
    status_quo = None
    if held:
        status_quo = simulate(kb, all_jobs, "fifo", focus=stage1_ids, name="status_quo")
        baselines = {"status_quo": status_quo, **baselines}

    ref = status_quo if status_quo is not None else fifo
    ref_name = "examining everything in listing order" if status_quo is not None else "first-in-first-out"
    summary = (
        f"Recommended policy {best.policy}: evidential value retained {_pct(best.value_retained)} "
        f"(perishable exhibits {_pct(best.perishable_value_retained)}) vs {_pct(ref.value_retained)} "
        f"({_pct(ref.perishable_value_retained)}) {ref_name} and {_pct(static.value_retained)} for a static score sort; "
        f"late exhibits {best.late_count} vs {ref.late_count}. "
    )
    if best.p1_mean_completion_days is not None and ref.p1_mean_completion_days is not None:
        summary += f"P1 results in {best.p1_mean_completion_days} working days on average vs {ref.p1_mean_completion_days}. "
    summary += f"Stage-1 examinations complete in {best.makespan_days} working days"
    if status_quo is not None:
        noun = "exhibit is" if len(held) == 1 else "exhibits are"
        summary += f"; {len(held)} {noun} held for stage 2 ({held_hours:g} bench-hours not queued ahead of other cases)"
        if status_quo.makespan_days > best.makespan_days + 0.5:
            summary += f" — examining everything now would take {status_quo.makespan_days} working days"
    summary += "."
    return ScheduleComparison(recommended=best, baselines=baselines, summary=summary,
                              held_items=len(held), bench_hours_held=held_hours)


def plan_lab(kb: KnowledgeBase, cases: list[tuple[str, list[TriagedItem], float | None]]) -> ScheduleComparison:
    """One FSL queue for many open cases. ``cases`` = [(case_id, items, custody_hours_left)] oldest first."""
    jobs: list[Job] = []
    order = 0
    for case_id, items, hours_left in cases:
        stage1 = [i for i in items if i.stage == 1]
        for j in build_jobs(kb, stage1, hours_left):
            j.item_id = f"{case_id}/{j.item_id}"
            j.label = f"{case_id}/{j.label}"
            j.order = order
            order += 1
            jobs.append(j)
    if not jobs:
        return _empty("No open stage-1 examinations across cases.")
    best, fifo, static = _portfolio(kb, jobs)
    summary = (
        f"Lab-wide queue across {len(cases)} case(s), {len(jobs)} stage-1 exhibits. Recommended {best.policy}: value "
        f"retained {_pct(best.value_retained)} vs {_pct(fifo.value_retained)} (cases handled in arrival order) and "
        f"{_pct(static.value_retained)} (static score sort); late exhibits {best.late_count} vs {fifo.late_count}; "
        f"queue clears in {best.makespan_days} working days."
    )
    return ScheduleComparison(recommended=best, baselines={"fifo": fifo, "priority": static}, summary=summary)
