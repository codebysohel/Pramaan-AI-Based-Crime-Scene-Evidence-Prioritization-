"""Interface tests: REST API + dashboard, MCP server (in-memory client and HTTP endpoint), CLI."""

import asyncio
import json

from fastapi.testclient import TestClient
from mcp import Client

from pramaan.api import create_app
from pramaan.cli import main as cli_main
from pramaan.config import SCENARIOS_DIR
from pramaan.mcp_server import mcp

SC = json.loads((SCENARIOS_DIR / "01_roadside_homicide.json").read_text())


def test_rest_api_full_flow():
    with TestClient(create_app()) as c:
        assert c.get("/api/health").json()["status"] == "ok"
        assert "Pramaan" in c.get("/").text
        assert len(c.get("/api/scenarios").json()) >= 4
        r = c.post("/api/triage", json=SC)
        assert r.status_code == 200
        cid = r.json()["case_id"]
        case = c.get(f"/api/cases/{cid}").json()
        assert case["verify"]["ok"] and case["ledger"][0]["action"] == "triage"
        assert c.get(f"/api/cases/{cid}/packet.pdf").content[:5] == b"%PDF-"
        assert "ACT NOW" in c.get(f"/api/cases/{cid}/packet.md").text
        sim = c.post(f"/api/cases/{cid}/items/Ex-A17/simulate", json={"condition": "refrigerated"}).json()
        assert sim["hours_to_risk"]["to"] > sim["hours_to_risk"]["from"]
        up = c.post(f"/api/cases/{cid}/items/Ex-A16/update",
                    json={"changes": {"override_tier": "P2", "override_reason": "compare with footwear soil"}, "reason": "IO request"})
        assert up.status_code == 200 and any(f["code"] == "OFFICER_OVERRIDE" for i in up.json()["items"] for f in i["flags"])
        assert c.post(f"/api/cases/{cid}/items/Ex-A2/custody", json={"event": "handed_over", "from_party": "IO", "to_party": "Malkhana"}).status_code == 200
        assert c.get("/api/ledger/verify").json()["ok"]
        assert c.get("/api/lab-queue").json()["recommended"]["ops"]
        assert len(c.get("/api/mcp/tools").json()["tools"]) >= 16
        bad = dict(SC, description="Ex-1: knife, owner phone 9876543210")
        r = c.post("/api/triage", json=bad)
        assert r.status_code == 422 and r.json()["kinds"] == ["mobile_number"]
        assert c.post("/api/triage", json=dict(SC, crime_type="alien_abduction")).status_code == 400


def test_mcp_http_endpoint_initialises():
    with TestClient(create_app()) as c:
        r = c.post("/mcp", headers={"Accept": "application/json, text/event-stream", "Host": "127.0.0.1:8000"},
                   json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}})
        assert r.status_code == 200 and "pramaan" in r.text


def test_mcp_tools_end_to_end():
    async def run():
        async with Client(mcp) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert {"triage_scene", "explain_item_priority", "generate_submission_packet", "verify_custody_ledger"} <= names
            r = await c.call_tool("triage_scene", {k: SC[k] for k in ("case_ref", "crime_type", "description", "incident_time",
                                                                    "reference_time", "accused_in_custody", "custody_start")})
            res = r.structured_content
            assert res["counts"]["total"] == 18 and res["act_now"]
            cid = res["case_id"]
            e = (await c.call_tool("explain_item_priority", {"case_id": cid, "item": "Ex-A2"})).structured_content
            assert abs(sum(e["points_by_factor"].values()) - e["epi"]) < 0.3
            bad = await c.call_tool("get_case", {"case_id": "PRM-NOPE"})
            assert bad.is_error and "Unknown case" in bad.content[0].text
            pk = (await c.call_tool("generate_submission_packet", {"case_id": cid})).structured_content
            assert pk["markdown"].startswith("# FSL Submission Packet")
            v = (await c.call_tool("verify_custody_ledger", {"case_id": cid})).structured_content
            assert v["ledger"]["ok"] and v["case"]["ok"]
    asyncio.run(run())


def test_cli_commands(capsys):
    assert cli_main(["triage", "01_roadside_homicide"]) == 0
    assert "ACT NOW" in capsys.readouterr().out
    assert cli_main(["benchmark", "--n", "60"]) == 0
    assert cli_main(["ledger", "verify"]) == 0
