"""Command line: ``python -m pramaan <command>`` (run from the ``src/`` directory)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import ENGINE_VERSION, REPO_DIR, SCENARIOS_DIR, SRC_DIR, get_settings

TIER_COLOUR = {"P1": "\033[91m", "P2": "\033[93m", "P3": "\033[96m", "P4": "\033[90m"}
RESET = "\033[0m"


def _c(tier: str, text: str) -> str:
    return f"{TIER_COLOUR.get(tier, '')}{text}{RESET}" if sys.stdout.isatty() else text


def _load_case(path: str):
    from .models import CaseInput
    p = Path(path)
    if not p.is_file():
        p = SCENARIOS_DIR / (path if path.endswith(".json") else f"{path}.json")
    data = json.loads(sys.stdin.read() if path == "-" else p.read_text(encoding="utf-8"))
    return CaseInput(**data)


def cmd_triage(a: argparse.Namespace) -> int:
    from . import reports
    from .llm.client import get_llm
    from .pipeline import run_triage
    from .store import Store

    store = Store() if a.persist else None
    r = run_triage(_load_case(a.case), llm=get_llm(), store=store, persist=a.persist, actor="cli")
    if a.json:
        print(json.dumps(r.model_dump(mode="json"), indent=2, default=str))
    else:
        print(f"\n{r.case_ref} — {r.crime_label}   case {r.case_id}   KB {r.kb_hash[:12]}")
        print("counts:", r.counts)
        acts = reports.act_now(r)
        if acts:
            print("\nACT NOW")
            for it, f in acts:
                print(f"  ! {it.label:<8} {f.code:<20} {f.message}")
        print(f"\n{'#':>3} {'EXHIBIT':<9} {'TIER':<4} {'EPI':>5}  {'TYPE':<34} FLAGS")
        for it in r.items:
            flags = ",".join(f.code for f in it.flags if f.severity in ("critical", "high", "info"))
            print(f"{it.rank:>3} {it.label:<9} {_c(it.tier, it.tier):<4} {it.score.epi:>5.1f}  "
                  f"{it.classification.type_name[:34]:<34} {flags}")
        if r.gaps:
            print("\nGAPS")
            for g in r.gaps:
                print(f"  [{g.severity}] {g.message}")
        print("\nLAB PLAN\n  " + r.schedule.summary)
        print(f"\nresult sha256 {r.result_sha256}")
    if a.packet:
        head = store.head() if store else None
        out = Path(a.packet)
        out.write_bytes(reports.packet_pdf(r, head)) if out.suffix == ".pdf" else out.write_text(reports.packet_markdown(r, head))
        print(f"packet written to {out}")
    return 0


def cmd_seed(a: argparse.Namespace) -> int:
    from .pipeline import run_triage
    from .store import Store
    store = Store()
    for f in sorted(SCENARIOS_DIR.glob("*.json")):
        r = run_triage(_load_case(str(f)), store=store, actor="seed")
        print(f"{r.case_id}  {f.stem:<32} {r.counts}")
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    import os
    import uvicorn
    os.environ.setdefault("APP_PORT", str(a.port))
    from .api import create_app
    print(f"Pramaan {ENGINE_VERSION}: dashboard http://{a.host}:{a.port}/   MCP http://{a.host}:{a.port}/mcp")
    uvicorn.run(create_app(), host=a.host, port=a.port, log_level="info")
    return 0


def cmd_mcp(a: argparse.Namespace) -> int:
    from .mcp_server import main
    if a.http:
        sys.argv.append("--http")
    main()
    return 0


def cmd_mcp_config(a: argparse.Namespace) -> int:
    stdio = {"command": sys.executable, "args": ["-m", "pramaan.mcp_server"],
             "env": {"PYTHONPATH": str(SRC_DIR), "PRAMAAN_HOME": str(get_settings().home)}}
    if a.client == "bob":
        stdio["env"]["PRAMAAN_MCP_ACTOR"] = "ibm-bob"
        cfg = {"mcpServers": {"pramaan": {"type": "streamable-http", "url": f"http://127.0.0.1:{get_settings().api_port}/mcp",
                                          "disabled": a.transport != "http"},
                              "pramaan-stdio": {**stdio, "disabled": a.transport != "stdio"}}}
        if a.write:
            target = REPO_DIR / ".bob" / "mcp.json"
            target.parent.mkdir(exist_ok=True)
            target.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {target} ({a.transport} enabled)")
            return 0
    else:
        cfg = {"mcpServers": {"pramaan": stdio}}
    print(json.dumps(cfg, indent=2))
    print("\n# Paste into your MCP client config (claude_desktop_config.json, VS Code mcp.json, ~/.bob/settings/mcp.json). "
          "HTTP clients can use http://127.0.0.1:8000/mcp while `python -m pramaan serve` runs.", file=sys.stderr)
    return 0


def cmd_mcp_demo(a: argparse.Namespace) -> int:
    """Drive the MCP server through a real client session and print a transcript (used for demo/)."""
    from mcp import Client
    from .mcp_server import mcp

    case = json.loads((SCENARIOS_DIR / "01_roadside_homicide.json").read_text(encoding="utf-8"))
    lines: list[str] = []

    def log(title: str, payload) -> None:
        lines.append(f"\n### {title}\n```json\n{json.dumps(payload, indent=2, default=str)[:a.max_chars]}\n```")

    async def run() -> None:
        async with Client(mcp) as c:
            tools = await c.list_tools()
            log("tools/list", [t.name for t in tools.tools])
            r = await c.call_tool("triage_scene", {k: case[k] for k in ("case_ref", "crime_type", "description", "incident_time",
                                                                      "reference_time", "accused_in_custody", "custody_start",
                                                                      "photo_captions", "title")} | {"ambient_temp_c": 31})
            res = r.structured_content
            log("triage_scene → act_now + top 5", {"case_id": res["case_id"], "counts": res["counts"],
                                                   "act_now": res["act_now"], "top5": res["ranked"][:5]})
            cid = res["case_id"]
            r = await c.call_tool("explain_item_priority", {"case_id": cid, "item": "Ex-A2"})
            e = r.structured_content
            log("explain_item_priority(Ex-A2)", {k: e[k] for k in ("tier", "epi", "points_by_factor", "rationale", "caveat", "what_would_change_it")})
            r = await c.call_tool("simulate_preservation", {"case_id": cid, "item": "Ex-A17", "condition": "refrigerated"})
            log("simulate_preservation(Ex-A17 → refrigerated)", r.structured_content)
            r = await c.call_tool("record_custody_event", {"case_id": cid, "item": "Ex-A2", "event": "handed_over",
                                                          "from_party": "IO", "to_party": "Malkhana", "seal_intact": True})
            log("record_custody_event", r.structured_content)
            r = await c.call_tool("update_item", {"case_id": cid, "item": "Ex-A9", "changes": {"override_tier": "P1"}, "reason": "x"})
            log("guardrail: update_item without a proper reason", {"is_error": r.is_error, "message": r.content[0].text})
            r = await c.call_tool("verify_custody_ledger", {"case_id": cid})
            log("verify_custody_ledger", r.structured_content)

    asyncio.run(run())
    text = "# Pramaan MCP session transcript\n\nGenerated by `python -m pramaan mcp-demo` (real MCP client ↔ server session)." + "".join(lines) + "\n"
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"transcript written to {a.out}")
    else:
        print(text)
    return 0


def cmd_ledger(a: argparse.Namespace) -> int:
    from .store import Store
    store = Store()
    if a.action == "verify":
        out = store.verify()
        print(json.dumps(out, indent=2))
        return 0 if out["ok"] else 2
    for e in reversed(store.ledger(limit=a.limit)):
        print(f"{e['seq']:>5} {e['ts'][:19]} {e['actor']:<12} {e['action']:<24} {e.get('case_id') or '-':<20} {e['hash'][:16]}")
    return 0


def cmd_benchmark(a: argparse.Namespace) -> int:
    from .benchmark import run_benchmark
    r = run_benchmark(a.n, a.seed)
    if a.json:
        print(json.dumps(r.as_dict(), indent=2, default=str))
        return 0
    print(f"Synthetic scene: {r.n_items} exhibits, seed {r.seed}; triaged in {r.seconds}s ({r.items_per_second} items/s)")
    print("counts:", r.counts)
    print("\nNeedles (exhibits a good triage must surface):")
    for n in r.needles:
        print(f"  {n['needle']}  {n['label']:<8} listed #{n['listed_at']:<4} -> rank {n['rank']:<4} {n['tier']}  {n['type']}")
    print(f"\n{'policy':<22}{'value':>8}{'perish.':>9}{'late':>6}{'P1 days':>9}{'makespan':>10}")
    for name, p in r.policies.items():
        pv = "-" if p["perishable_value_retained"] is None else f"{p['perishable_value_retained']:.1%}"
        print(f"{name + ' ' + p['policy'] if name == 'pramaan' else name:<22}{p['value_retained']:>8.1%}{pv:>9}{p['late']:>6}"
              f"{str(p['p1_mean_days']):>9}{p['makespan_days']:>10}")
    return 0


def cmd_legal_pdf(a: argparse.Namespace) -> int:
    from .bsa import legal_analysis_pdf
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(legal_analysis_pdf())
    print(f"legal analysis written to {out}")
    return 0


def cmd_scale(a: argparse.Namespace) -> int:
    from .network import scale_benchmark
    extra = {a.add_division.upper(): a.add_examiners} if a.add_division and a.add_examiners else None
    r = scale_benchmark(a.cases, a.items, add_examiners=extra)
    if a.json:
        for k in ("hq_only", "network"):
            r[k].pop("assignments", None)
        print(json.dumps(r, indent=2, default=str))
        return 0
    print(f"{r['cases']} cases x {a.items} exhibits = {r['exhibits']} exhibits triaged in {r['triage_seconds']} s "
          f"({r['exhibits_per_second']} exhibits/s)")
    print(r["summary"])
    print(f"\n{'unit':<12}{'exhibits':>9}{'P1':>5}{'busy days':>11}{'bottleneck':>14}{'its load':>10}")
    for u in r["network"]["units"]:
        print(f"{u['id']:<12}{u['exhibits']:>9}{u['p1']:>5}{u['busy_days']:>11}{str(u['bottleneck']):>14}{u['bottleneck_utilisation']:>10.0%}")
    return 0


def cmd_scenarios(a: argparse.Namespace) -> int:
    for f in sorted(SCENARIOS_DIR.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        print(f"{f.stem:<32} {d.get('crime_type'):<16} {d.get('title')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pramaan", description=f"Pramaan {ENGINE_VERSION} — crime-scene evidence triage")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("triage", help="triage a case JSON (path, scenario name, or - for stdin)")
    t.add_argument("case"); t.add_argument("--persist", action="store_true"); t.add_argument("--json", action="store_true")
    t.add_argument("--packet", help="write packet to this .pdf or .md path"); t.set_defaults(fn=cmd_triage)
    sub.add_parser("seed", help="triage all bundled scenarios into the database").set_defaults(fn=cmd_seed)
    s = sub.add_parser("serve", help="run dashboard + REST API + MCP (HTTP) server")
    s.add_argument("--host", default=get_settings().api_host); s.add_argument("--port", type=int, default=get_settings().api_port)
    s.set_defaults(fn=cmd_serve)
    m = sub.add_parser("mcp", help="run the MCP server (stdio by default)"); m.add_argument("--http", action="store_true"); m.set_defaults(fn=cmd_mcp)
    mc = sub.add_parser("mcp-config", help="print (or write for IBM Bob) an MCP client config with absolute paths")
    mc.add_argument("--client", choices=["generic", "bob"], default="generic")
    mc.add_argument("--transport", choices=["http", "stdio"], default="http", help="for --client bob")
    mc.add_argument("--write", action="store_true", help="write .bob/mcp.json (with --client bob)")
    mc.set_defaults(fn=cmd_mcp_config)
    d = sub.add_parser("mcp-demo", help="run a scripted MCP client session and print the transcript")
    d.add_argument("--out"); d.add_argument("--max-chars", type=int, default=2500); d.set_defaults(fn=cmd_mcp_demo)
    lg = sub.add_parser("ledger", help="show or verify the chain-of-custody ledger")
    lg.add_argument("action", choices=["show", "verify"]); lg.add_argument("--limit", type=int, default=50); lg.set_defaults(fn=cmd_ledger)
    b = sub.add_parser("benchmark", help="Hyderabad-scale synthetic benchmark")
    b.add_argument("--n", type=int, default=200); b.add_argument("--seed", type=int, default=2019); b.add_argument("--json", action="store_true")
    b.set_defaults(fn=cmd_benchmark)
    sub.add_parser("scenarios", help="list bundled scenarios").set_defaults(fn=cmd_scenarios)
    lp = sub.add_parser("legal-pdf", help="write the BSA 2023 electronic-evidence legal analysis PDF")
    lp.add_argument("--out", default=str(REPO_DIR / "docs" / "legal" / "BSA-2023-evidence-authenticity-analysis.pdf")); lp.set_defaults(fn=cmd_legal_pdf)
    sc = sub.add_parser("scale", help="FSL scalability benchmark: many cases, network plan vs HQ-only")
    sc.add_argument("--cases", type=int, default=10); sc.add_argument("--items", type=int, default=200)
    sc.add_argument("--add-division"); sc.add_argument("--add-examiners", type=int, default=0)
    sc.add_argument("--json", action="store_true"); sc.set_defaults(fn=cmd_scale)
    args = p.parse_args(argv)
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
