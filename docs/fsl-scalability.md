# Scalability for the Forensic Science Laboratory network

Pramaan scales on three axes, all measured in code (`python -m pramaan scale`, `src/pramaan/network.py`).

## 1. Throughput of the engine
Triage is linear in the number of exhibits (keyword classification, closed-form degradation, per-exhibit DAG). Measured: **2000 exhibits from 10 Hyderabad-scale cases triaged in 4.51 s (443 exhibits/s)** on one laptop core, including each case's scheduling portfolio. No GPU, no network, no LLM required.

## 2. From one lab to a state network
A state rarely has one laboratory. Pramaan plans the **State FSL HQ + Regional FSLs + CFSL (referral, P1/P2 only)** as one resource pool (`laboratory.yaml → network:`):

* each exhibit — one physical object, so all its examinations stay together — goes to the unit where it will be **completed earliest, including transport time**;
* exhibits are placed in priority order (tier, due date from degradation and the BNSS s.187(3) report deadline, EPI);
* per-unit, per-division examiner timelines are **min-heaps**: planning is O(J · U · ops · log E).

| 788 stage-1 exhibits from 10 simultaneous cases | Pramaan network plan | Everything to State FSL HQ |
|---|---|---|
| P1 results (mean working days) | **38.39** | 84.85 |
| Queue clears (working days) | **312.0** | 492.0 |
| Exhibits past their quality / report due date | **407** | 613 |
| Planning time | **10 ms** | — |

The numbers are deliberately sobering: ten Hyderabad-scale cases at once overwhelm even a four-unit network (bottleneck: **DNA**). That is exactly what the capacity planner is for.

## 3. Capacity planning (what-if)
`plan_fsl_network(add_division="DNA", add_examiners=2)`, the dashboard *FSL network* page, or `python -m pramaan scale --add-division DNA --add-examiners 2` re-plans with extra examiners at HQ and reports the change in P1 time, makespan and late exhibits — evidence for recruitment and budget requests, per division.

## 4. One queue across cases
`lab_queue` (single lab) and `plan_fsl_network` (network) schedule **all open cases together** instead of case by case, so a perishable exhibit from today's case can overtake a stable exhibit from last week's.

## 5. Operational scaling
Stateless FastAPI + one SQLite (WAL) per deployment; the MCP server runs over stdio for a single officer or streamable HTTP for a team; Docker image, non-root; no CDN (air-gapped district labs). For state-wide deployment the store can move to PostgreSQL behind the same `Store` interface (roadmap).

Illustrative capacities — replace `network:` with your state's units before relying on the numbers.
