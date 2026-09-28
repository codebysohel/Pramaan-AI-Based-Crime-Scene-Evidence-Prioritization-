"""Per-case output bundle — the Pramaan equivalent of SAVVYDFIR's case outputs.

    <PRAMAAN_HOME>/cases/<case_id>/
        state.json    full case state: input, result, integrity verification, ledger head
        audit.jsonl   this case's chain-of-custody ledger entries, oldest first (hash-linked)
        report.html   self-contained, printable triage report (no CDN)
        graph.html    interactive evidence graph: case -> exhibits -> examinations -> FSL divisions
        packet.md     FSL submission packet (Markdown)
        packet.pdf    FSL submission packet (PDF)

Every file is generated deterministically from the stored result, so it can be regenerated
and re-verified at any time (``verify_custody_ledger`` / ``state.json.verify``).
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from . import bsa, reports
from .config import get_settings
from .models import TIER_LABELS, TriageResult, TriagedItem
from .store import Store, canonical

TIER_COLOR = {"P1": "#b3261e", "P2": "#b86e00", "P3": "#1f6f78", "P4": "#6b7280"}
E = html.escape


def _load(store: Store, case_id: str) -> tuple[dict[str, Any], TriageResult]:
    case = store.get_case(case_id)
    if not case:
        raise KeyError(f"Unknown case '{case_id}'")
    return case, TriageResult(**case["result"])


def state_dict(store: Store, case_id: str) -> dict[str, Any]:
    case, result = _load(store, case_id)
    return {
        "schema": "pramaan.case_state/1", "case_id": case_id, "case_ref": case["case_ref"],
        "crime_type": case["crime_type"], "created_at": case["created_at"], "updated_at": case["updated_at"],
        "engine_version": result.engine_version, "kb_hash": case["kb_hash"], "result_sha256": case["result_sha256"],
        "verify": store.verify_case(case_id), "ledger_head": store.head(), "counts": result.counts,
        "input": case["input"], "result": case["result"],
    }


def audit_lines(store: Store, case_id: str) -> str:
    _load(store, case_id)
    entries = list(reversed(store.ledger(case_id, limit=100000)))
    return "".join(canonical(e) + "\n" for e in entries)


def _ttl(it: TriagedItem) -> str:
    c = [h for h in (it.degradation.hours_to_risk, it.degradation.field_window_remaining_h) if h is not None]
    if not c:
        return "stable"
    h = max(0.0, min(c))
    return "lost" if h <= 0 else (f"{h:.0f} h" if h < 48 else f"{h / 24:.0f} d")


def _epi_bar(it: TriagedItem) -> str:
    s = it.score
    p, u, r = (100 * s.weights[k] * v for k, v in (("probative", s.probative), ("urgency", s.urgency), ("irreplaceable", s.irreplaceable)))
    floor = max(0.0, s.epi - (p + u + r))
    segs = f'<i style="width:{p:.1f}%;background:#2b4c7e"></i><i style="width:{u:.1f}%;background:#c2410c"></i><i style="width:{r:.1f}%;background:#b8893f"></i>'
    if floor > 0.5:
        segs += f'<i style="width:{floor:.1f}%;background:#7a1f5c"></i>'
    return f'<span class="bar">{segs}</span> <b>{s.epi:.1f}</b>'


_CSS = """
:root{--ink:#16181d;--paper:#f4f1ea;--card:#fffdf8;--line:#e0d8c8;--muted:#6b6557;--kraft:#b8893f}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
header{background:var(--ink);color:#f4f1ea;padding:18px 32px}header .k{color:#d9a441;font-size:11px;letter-spacing:.2em;font-weight:700}
header h1{margin:4px 0 2px;font-size:22px}header .s{color:#b9b3a6;font-size:13px}
main{padding:20px 32px 40px;max-width:1280px}h2{font-size:16px;margin:22px 0 8px;border-bottom:1.5px solid var(--ink);padding-bottom:4px}
.tiles{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}.tile{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:10px 12px}
.tile .k{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}.tile .v{font-size:22px;font-weight:750}
table{width:100%;border-collapse:collapse;background:var(--card)}th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);text-align:left;padding:7px;border-bottom:1.5px solid var(--ink);background:#f6f2e9}
td{padding:7px;border-bottom:1px solid var(--line);vertical-align:top}.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}
.tier{color:#fff;border-radius:5px;padding:1px 7px;font:700 11.5px ui-monospace,Menlo,monospace}.lab{font:600 12px ui-monospace,Menlo,monospace;background:#f1e3c6;border:1px dashed var(--kraft);border-radius:5px;padding:1px 6px}
.bar{display:inline-flex;width:120px;height:9px;background:#ece5d6;border-radius:3px;overflow:hidden;vertical-align:middle}.bar i{display:block;height:100%}
.act{border:1.5px solid #b3261e;background:#fbeeea;border-radius:9px;padding:10px 14px}.act li{margin:4px 0}.code{font:700 11px ui-monospace,monospace;color:#b3261e}
.flag{display:inline-block;font:600 10px ui-monospace,monospace;border:1px solid #d5d7dc;border-radius:4px;padding:0 4px;margin:1px 2px 1px 0}
.gap{border-left:4px solid #b86e00;background:var(--card);padding:8px 12px;margin:6px 0}.muted{color:var(--muted)}
footer{font:11px ui-monospace,monospace;color:var(--muted);padding:0 32px 30px}
@media print{header{background:#fff;color:#000}.tile,table{break-inside:avoid}}
"""


def report_html(result: TriageResult, ledger_head: dict[str, Any] | None = None, verify: dict[str, Any] | None = None) -> str:
    r, c = result, result.counts
    rec = r.schedule.recommended
    acts = reports.act_now(r)
    rows = []
    for it in r.items:
        flags = "".join(f'<span class="flag" title="{E(f.message)}">{E(f.code)}</span>' for f in it.flags
                        if f.severity in ("critical", "high", "medium", "info"))
        rows.append(f'<tr><td class="mono">{it.rank}</td><td><span class="lab">{E(it.label)}</span></td><td>{E(it.description)}</td>'
                    f'<td>{E(it.classification.type_name)}</td><td><span class="tier" style="background:{TIER_COLOR[it.tier]}">{it.tier}</span></td>'
                    f'<td class="mono">{_epi_bar(it)}</td><td class="mono">{_ttl(it)}</td><td>{flags}</td></tr>')
    p1 = "".join(f"<tr><td><span class='lab'>{E(i.label)}</span></td><td>{E(i.rationale)}</td><td>{E(i.caveat)}</td>"
                 f"<td>{E('; '.join(i.corroborate_with))}</td></tr>" for i in r.items if i.tier == "P1")
    pol = "".join(f"<tr><td>{E(n)}</td><td class='mono'>{s.value_retained:.1%}</td><td class='mono'>"
                  f"{'-' if s.perishable_value_retained is None else f'{s.perishable_value_retained:.1%}'}</td><td class='mono'>{s.late_count}</td>"
                  f"<td class='mono'>{s.p1_mean_completion_days if s.p1_mean_completion_days is not None else '-'}</td><td class='mono'>{s.makespan_days}</td></tr>"
                  for n, s in [(f"Pramaan {rec.policy}", rec)] + list(r.schedule.baselines.items()))
    verdict = "" if verify is None else (" · <b style='color:#2f7d32'>result hash matches ledger</b>" if verify.get("ok") else " · <b style='color:#b3261e'>INTEGRITY CHECK FAILED</b>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Triage report {E(r.case_id)}</title><style>{_CSS}</style></head><body>
<header><div class="k">PRAMAAN · EVIDENCE TRIAGE REPORT</div><h1>{E(r.case_ref)}</h1>
<div class="s">{E(r.crime_label)} · case {E(r.case_id)} · generated {r.created_at:%d %b %Y %H:%M} UTC · {E(r.title or '')}</div></header><main>
<div class="tiles"><div class="tile"><div class="k">Exhibits</div><div class="v">{c.get('total', 0)}</div></div>
<div class="tile"><div class="k">P1 critical</div><div class="v" style="color:#b3261e">{c.get('P1', 0)}</div></div>
<div class="tile"><div class="k">P2 high</div><div class="v" style="color:#b86e00">{c.get('P2', 0)}</div></div>
<div class="tile"><div class="k">Held (stage 2)</div><div class="v">{c.get('held', 0)}</div></div>
<div class="tile"><div class="k">Custody deadline</div><div class="v" style="font-size:16px">{r.custody_deadline.strftime('%d %b %Y') if r.custody_deadline else '—'}</div></div>
<div class="tile"><div class="k">Value retained</div><div class="v">{rec.value_retained:.1%}</div></div></div>
<h2>1 · Forwarding note</h2><p>{E(r.narrative)}</p>
<h2>2 · ACT NOW</h2>{'<ul class="act">' + ''.join(f'<li><span class="lab">{E(i.label)}</span> <span class="code">{E(f.code)}</span> {E(f.message)}</li>' for i, f in acts) + '</ul>' if acts else '<p class="muted">No critical field actions.</p>'}
<h2>3 · Ranked exhibits</h2><table><thead><tr><th>#</th><th>Exhibit</th><th>Description</th><th>Type</th><th>Tier</th><th>EPI</th><th>Time to loss</th><th>Flags</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<p class="muted">Tiers: {'; '.join(f'{k} {v}' for k, v in TIER_LABELS.items())}. EPI bar: probative (blue) · urgency (orange) · irreplaceability (tan) · statutory floor (purple).</p>
<h2>4 · P1 reasoning, caveats and corroboration</h2><table><thead><tr><th>Exhibit</th><th>Why</th><th>Does not prove</th><th>Corroborate with</th></tr></thead><tbody>{p1}</tbody></table>
<h2>5 · Gaps</h2>{''.join(f'<div class="gap"><b>[{E(g.severity.upper())}] {E(g.message)}</b><br>→ {E(g.action)}</div>' for g in r.gaps) or '<p class="muted">None.</p>'}
<h2>6 · Laboratory plan</h2><p>{E(r.schedule.summary)}</p><table><thead><tr><th>Policy</th><th>Value retained</th><th>Perishable</th><th>Late</th><th>P1 mean days</th><th>Makespan days</th></tr></thead><tbody>{pol}</tbody></table>
<h2>7 · Method and integrity</h2><p>{E(reports.METHOD_STATEMENT)}</p>
<p class="mono">engine v{E(r.engine_version)} · KB {E(r.kb_hash)}<br>result sha-256 {E(r.result_sha256)}{verdict}<br>
ledger head {E(str(ledger_head.get('seq')) + ' · ' + ledger_head.get('hash', '')) if ledger_head else '—'} · LLM layer {E(r.llm_provider)}</p>
</main><footer>Decision support only — the Investigating Officer decides; the FSL may re-order on scientific grounds. No personal identifiers are processed.</footer></body></html>"""


def graph_html(result: TriageResult) -> str:
    """Case -> exhibits -> examinations -> divisions, as a static SVG with hover highlighting (no libraries)."""
    r = result
    exhibits = list(r.items)
    exams: dict[str, tuple[str, int, bool, str]] = {}
    for it in exhibits:
        for st in it.exam_sequence:
            exams.setdefault(st.exam_id, (st.name, st.stage, st.destructive, st.division))
    exam_ids = sorted(exams, key=lambda e: (exams[e][1], exams[e][0]))
    divisions = sorted({v[3] for v in exams.values()})
    cols = {0: ["case"], 1: [f"x:{i.item_id}" for i in exhibits], 2: [f"e:{e}" for e in exam_ids], 3: [f"d:{d}" for d in divisions]}
    row_h, top = 30, 70
    height = top + max(len(v) for v in cols.values()) * row_h + 40
    xs = {0: 40, 1: 300, 2: 660, 3: 1030}
    widths = {0: 190, 1: 250, 2: 250, 3: 170}
    pos: dict[str, tuple[float, float]] = {}
    for col, ids in cols.items():
        span = height - top - 40
        for k, nid in enumerate(ids):
            y = top + (k + 0.5) * span / len(ids) if col in (0, 3) or len(ids) < 4 else top + k * row_h + 12
            pos[nid] = (xs[col], y)
    edges: list[tuple[str, str, str]] = []
    for it in exhibits:
        edges.append(("case", f"x:{it.item_id}", TIER_COLOR[it.tier]))
        for st in it.exam_sequence:
            edges.append((f"x:{it.item_id}", f"e:{st.exam_id}", "#b3261e" if st.destructive else "#9aa3b2"))
    for e, (_, _, _, div) in exams.items():
        edges.append((f"e:{e}", f"d:{div}", "#b8893f"))
    paths = []
    for a, b, colr in edges:
        (xa, ya), (xb, yb) = pos[a], pos[b]
        col_a = next(k for k, v in cols.items() if a in v)
        x1 = xa + widths[col_a]
        mid = (x1 + xb) / 2
        paths.append(f'<path d="M{x1:.0f},{ya:.0f} C{mid:.0f},{ya:.0f} {mid:.0f},{yb:.0f} {xb:.0f},{yb:.0f}" stroke="{colr}" '
                     f'data-a="{E(a)}" data-b="{E(b)}"/>')
    nodes = []

    def node(nid: str, text: str, sub: str, fill: str, stroke: str, title: str, col: int) -> None:
        x, y = pos[nid]
        nodes.append(f'<g class="n" data-id="{E(nid)}"><title>{E(title)}</title><rect x="{x}" y="{y - 11}" width="{widths[col]}" height="22" rx="5" '
                     f'fill="{fill}" stroke="{stroke}"/><text x="{x + 8}" y="{y + 4}">{E(text)}</text>'
                     f'<text class="s" x="{x + widths[col] - 6}" y="{y + 4}" text-anchor="end">{E(sub)}</text></g>')

    node("case", r.case_id, r.crime_type, "#16181d", "#16181d", f"{r.case_ref} — {r.crime_label}", 0)
    for it in exhibits:
        node(f"x:{it.item_id}", f"{it.label} · {it.classification.type_name[:22]}", f"{it.tier} {it.score.epi:.0f}",
             TIER_COLOR[it.tier], TIER_COLOR[it.tier], f"{it.label}: {it.description} | {', '.join(f.code for f in it.flags)}", 1)
    for e in exam_ids:
        name, stage, destr, div = exams[e]
        node(f"e:{e}", name[:30], f"s{stage}{' ✕' if destr else ''}", "#fffdf8", "#b3261e" if destr else "#9aa3b2",
             f"{name} — stage {stage}{', DESTRUCTIVE' if destr else ''} — {div}", 2)
    for d in divisions:
        node(f"d:{d}", d.title(), "", "#f1e3c6", "#b8893f", f"FSL division {d}", 3)
    svg = (f'<svg id="g" width="1240" height="{height}" viewBox="0 0 1240 {height}">'
           f'<text class="h" x="40" y="40">CASE</text><text class="h" x="300" y="40">EXHIBITS (rank order, tier colour)</text>'
           f'<text class="h" x="660" y="40">EXAMINATIONS (stage · ✕ destructive)</text><text class="h" x="1030" y="40">FSL DIVISIONS</text>'
           f'<g class="edges">{"".join(paths)}</g>{"".join(nodes)}</svg>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Evidence graph {E(r.case_id)}</title>
<style>body{{margin:0;background:#f4f1ea;font:13px system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:#16181d}}
header{{background:#16181d;color:#f4f1ea;padding:14px 28px}}header b{{color:#d9a441;letter-spacing:.2em;font-size:11px}}header h1{{margin:4px 0 0;font-size:19px}}
.wrap{{padding:14px 20px;overflow:auto}}path{{fill:none;stroke-width:1.3;opacity:.55;transition:opacity .15s}}
text{{font-size:11.5px;fill:#fff;pointer-events:none}}text.s{{font:10px ui-monospace,monospace;fill:#fff;opacity:.9}}
g.n rect[fill="#fffdf8"]+text,g.n rect[fill="#fffdf8"]+text+text,g.n rect[fill="#f1e3c6"]+text{{fill:#16181d}}
text.h{{font:700 11px ui-monospace,monospace;fill:#6b6557;letter-spacing:.06em}}g.n{{cursor:pointer}}
svg.focus path{{opacity:.06}}svg.focus path.hi{{opacity:1;stroke-width:2.2}}svg.focus g.n{{opacity:.3}}svg.focus g.n.hi{{opacity:1}}
p{{color:#6b6557;margin:6px 20px}}</style></head><body>
<header><b>PRAMAAN · EVIDENCE GRAPH</b><h1>{E(r.case_ref)} — {E(r.crime_label)}</h1></header>
<p>Hover an exhibit, examination or division to trace its connections. Red edges lead to destructive examinations, which the engine schedules last. KB {E(r.kb_hash[:12])} · result {E(r.result_sha256[:12])}</p>
<div class="wrap">{svg}</div>
<script>
const svg=document.getElementById('g');
function linked(id){{const s=new Set([id]);let grow=true;const P=[...svg.querySelectorAll('path')];
  // walk downstream and upstream one hop each way from the focus node
  P.forEach(p=>{{if(p.dataset.a===id)s.add(p.dataset.b);if(p.dataset.b===id)s.add(p.dataset.a);}});return s;}}
svg.querySelectorAll('g.n').forEach(g=>{{g.addEventListener('mouseenter',()=>{{const id=g.dataset.id,s=linked(id);svg.classList.add('focus');
  svg.querySelectorAll('path').forEach(p=>p.classList.toggle('hi',p.dataset.a===id||p.dataset.b===id));
  svg.querySelectorAll('g.n').forEach(n=>n.classList.toggle('hi',s.has(n.dataset.id)));}});
  g.addEventListener('mouseleave',()=>svg.classList.remove('focus'));}});
</script></body></html>"""


def electronic_input(case: dict[str, Any], item_id: str):
    from .models import CaseInput
    ci = CaseInput(**case["input"])
    n = int(item_id.split("-")[1]) - 1
    return ci.items[n].electronic if 0 <= n < len(ci.items) else None


def authenticity(store: Store, case_id: str) -> dict[str, Any]:
    """Case-level BSA/BNSS authenticity & reliability assessment (electronic + physical), incl. custody ledger facts."""
    from .models import CaseInput
    case, result = _load(store, case_id)
    return bsa.assess_case(result, CaseInput(**case["input"]), store.ledger(case_id, limit=100000),
                           store.verify_case(case_id).get("ok"))


def export_case(store: Store, case_id: str) -> dict[str, str]:
    """Write the full output bundle for one case and return the file paths."""
    case, result = _load(store, case_id)
    folder = get_settings().cases_dir / case_id
    folder.mkdir(parents=True, exist_ok=True)
    head, verify = store.head(), store.verify_case(case_id)
    files = {
        "state.json": json.dumps(state_dict(store, case_id), indent=2, ensure_ascii=False, default=str),
        "audit.jsonl": audit_lines(store, case_id),
        "report.html": report_html(result, head, verify),
        "graph.html": graph_html(result),
        "packet.md": reports.packet_markdown(result, head),
    }
    auth = authenticity(store, case_id)
    files["authenticity.json"] = json.dumps(auth, indent=2, ensure_ascii=False, default=str)
    out: dict[str, str] = {}
    (folder / "authenticity_report.pdf").write_bytes(bsa.authenticity_report_pdf(auth, result))
    out["authenticity_report.pdf"] = str(folder / "authenticity_report.pdf")
    for it in result.items:
        if bsa.is_electronic(it):
            name = f"bsa63_certificate_{reports.safe_filename(it.label)}.pdf"
            (folder / name).write_bytes(bsa.certificate_pdf(result, it, electronic_input(case, it.item_id)))
            out[name] = str(folder / name)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
        out[name] = str(folder / name)
    (folder / "packet.pdf").write_bytes(reports.packet_pdf(result, head))
    out["packet.pdf"] = str(folder / "packet.pdf")
    return out
