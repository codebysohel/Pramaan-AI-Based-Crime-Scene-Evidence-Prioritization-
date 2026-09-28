"""Examination sequencing for one exhibit.

An exhibit is one physical object: it can only be on one bench at a time, and
some examinations destroy or alter what another needs (cyanoacrylate fuming
before touch-DNA swabbing, ninhydrin before indented-writing analysis, DNA
extraction consuming a stain before serology confirms it).

We build a DAG over the requested examinations with two edge types:
  * stage edges    — every exam of a lower ``stage`` precedes every exam of a
                     higher stage (least-destructive-first principle);
  * explicit edges — ``after:`` lists in laboratory.yaml.
and return a topological order (Kahn's algorithm, ties broken by stage then by
the order in the evidence type's exam plan). A cycle means the knowledge base
contradicts itself, so we fail closed.
"""

from __future__ import annotations

import heapq

from .knowledge import KnowledgeBase
from .models import ExamStep


class SequencingError(ValueError):
    pass


def sequence(kb: KnowledgeBase, exam_ids: list[str], quantity: int = 1) -> list[ExamStep]:
    exams = list(dict.fromkeys(exam_ids))  # dedupe, keep plan order
    index = {e: i for i, e in enumerate(exams)}
    edges: dict[str, set[str]] = {e: set() for e in exams}
    indeg: dict[str, int] = {e: 0 for e in exams}

    def add_edge(a: str, b: str) -> None:
        if b not in edges[a]:
            edges[a].add(b)
            indeg[b] += 1

    for a in exams:
        for b in exams:
            if a != b and kb.exams[a]["stage"] < kb.exams[b]["stage"]:
                add_edge(a, b)
        for dep in kb.exams[a].get("after", []) or []:
            if dep in edges:
                add_edge(dep, a)

    heap = [(kb.exams[e]["stage"], index[e], e) for e in exams if indeg[e] == 0]
    heapq.heapify(heap)
    order: list[str] = []
    while heap:
        _, _, e = heapq.heappop(heap)
        order.append(e)
        for nxt in sorted(edges[e], key=lambda x: index[x]):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                heapq.heappush(heap, (kb.exams[nxt]["stage"], index[nxt], nxt))
    if len(order) != len(exams):
        raise SequencingError(f"Cyclic examination constraints among {sorted(set(exams) - set(order))}")

    # Batches of similar exhibits (e.g. 8 cigarette butts) take longer, sub-linearly.
    factor = 1.0 + 0.5 * (min(max(quantity, 1), 6) - 1)
    return [
        ExamStep(
            exam_id=e, name=kb.exams[e]["name"], division=kb.exams[e]["division"],
            hours=round(float(kb.exams[e]["hours"]) * factor, 1),
            stage=int(kb.exams[e]["stage"]), destructive=bool(kb.exams[e].get("destructive", False)),
        )
        for e in order
    ]
