"""Output bundle (state.json, audit.jsonl, report.html, graph.html, packet) and its API/MCP surfaces."""

import asyncio
import json

from fastapi.testclient import TestClient
from mcp import Client

from pramaan import outputs
from pramaan.api import create_app
from pramaan.config import SCENARIOS_DIR
from pramaan.mcp_server import mcp
from pramaan.models import CaseInput
from pramaan.pipeline import run_triage
from pramaan.store import Store

SC = json.loads((SCENARIOS_DIR / "01_roadside_homicide.json").read_text())


def test_export_bundle_files():
    store = Store()
    r = run_triage(CaseInput(**SC), store=store)
    files = outputs.export_case(store, r.case_id)
    assert {"state.json", "audit.jsonl", "report.html", "graph.html", "packet.md", "packet.pdf",
            "authenticity.json", "authenticity_report.pdf"} <= set(files)
    assert any(k.startswith("bsa63_certificate_Ex-A13") for k in files)  # CCTV DVR exhibit
    state = json.loads(open(files["state.json"]).read())
    assert state["verify"]["ok"] and state["result_sha256"] == r.result_sha256
    lines = open(files["audit.jsonl"]).read().splitlines()
    assert json.loads(lines[0])["action"] == "triage"
    rep = open(files["report.html"]).read()
    assert "ACT NOW" in rep and "Ex-A17" in rep and "result hash matches ledger" in rep
    graph = open(files["graph.html"]).read()
    assert "<svg" in graph and "x:E-001" in graph and "d:DNA" in graph
    assert open(files["packet.pdf"], "rb").read(5) == b"%PDF-"


def test_output_endpoints_and_mcp_tool():
    with TestClient(create_app()) as c:
        cid = c.post("/api/triage", json=SC).json()["case_id"]
        assert "<svg" in c.get(f"/api/cases/{cid}/graph.html").text
        assert "Ranked exhibits" in c.get(f"/api/cases/{cid}/report.html").text
        assert c.get(f"/api/cases/{cid}/state.json").json()["case_id"] == cid
        assert c.get(f"/api/cases/{cid}/audit.jsonl").text.count("\n") >= 1
        assert "graph.html" in c.post(f"/api/cases/{cid}/export").json()["files"]

    async def run():
        async with Client(mcp) as cl:
            r = await cl.call_tool("triage_scene", {"case_ref": "T-9", "crime_type": "burglary",
                                                   "description": "Ex-1: footwear impression on the sill, not yet lifted"})
            cid = r.structured_content["case_id"]
            out = (await cl.call_tool("export_case_outputs", {"case_id": cid})).structured_content
            assert out["files"]["report.html"].endswith("report.html")
    asyncio.run(run())
