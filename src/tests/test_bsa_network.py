"""BSA 2023 ss.61-63 authenticity engine, certificate drafting, and FSL network scalability."""

import asyncio
import json

from fastapi.testclient import TestClient
from mcp import Client

from pramaan import bsa, network
from pramaan.api import create_app
from pramaan.config import SCENARIOS_DIR
from pramaan.knowledge import load_kb
from pramaan.mcp_server import mcp
from pramaan.models import CaseInput, ElectronicRecord, ItemInput
from pramaan.pipeline import run_triage
from pramaan.store import Store

H = "a" * 64


def _cctv(er=None, seizure_video=True):
    case = CaseInput(case_ref="T-BSA", crime_type="homicide", seizure_video_recorded=seizure_video,
                     items=[ItemInput(label="Ex-1", description="CCTV DVR of the petrol pump, seized", electronic=er)])
    return run_triage(case, persist=False).items[0]


def test_missing_electronic_facts_are_curable_and_flagged():
    it = _cctv()
    assert it.authenticity.kind == "electronic" and it.authenticity.status == "CURABLE_GAPS"
    assert "BSA63_DETAILS_MISSING" in [f.code for f in it.flags]
    assert it.tier == it.engine_tier  # legal-readiness flags never change forensic priority


def test_fully_documented_record_is_ready():
    er = ElectronicRecord(acquisition="exported_copy", hash_at_acquisition=H, hash_at_lab=H.upper(), regular_use=True,
                          ordinary_course=True, operating_properly=True, derived_from_ordinary_course=True, clock_offset_s=42,
                          certificate_part_a=True, part_a_signatory_role="Manager, petrol pump", certificate_part_b=True,
                          expert_role="FSL Cyber Division examiner")
    a = _cctv(er).authenticity
    assert a.status == "READY" and a.score >= 95
    assert {c.id: c.status for c in a.checks}["hash_verified"] == "PASS"


def test_hash_mismatch_and_failed_condition_put_record_at_risk():
    er = ElectronicRecord(hash_at_acquisition=H, hash_at_lab="b" * 64, operating_properly=False)
    it = _cctv(er)
    codes = [f.code for f in it.flags]
    assert it.authenticity.status == "AT_RISK" and "HASH_MISMATCH" in codes and "BSA63_CONDITION_NOT_MET" in codes


def test_original_device_route_makes_certificate_advisory():
    a = _cctv(ElectronicRecord(acquisition="original_device", hash_at_acquisition=H)).authenticity
    st = {c.id: c for c in a.checks}
    assert st["cert_part_a"].status == "ADVISORY" and not st["cert_part_a"].required and a.status == "READY"


def test_invalid_hash_format_fails():
    a = _cctv(ElectronicRecord(hash_at_acquisition="1234")).authenticity
    assert {c.id: c.status for c in a.checks}["hash_recorded"] == "FAIL"


def test_case_assessment_uses_custody_ledger_and_pdfs():
    store = Store()
    case = CaseInput(**json.loads((SCENARIOS_DIR / "01_roadside_homicide.json").read_text()))
    r = run_triage(case, store=store)
    a2 = next(i for i in r.items if i.label == "Ex-A2")
    store.append("t", "custody:sealed", {"seal_intact": True}, case_id=r.case_id, item_id=a2.item_id)
    store.append("t", "custody:handed_over", {"seal_intact": False}, case_id=r.case_id, item_id=a2.item_id)
    from pramaan import outputs
    rep = outputs.authenticity(store, r.case_id)
    row = next(x for x in rep["items"] if x["label"] == "Ex-A2")
    assert row["assessment"]["status"] == "AT_RISK"  # broken seal
    assert rep["electronic_records"] >= 2 and len(rep["law"]) >= 10
    pdf = bsa.authenticity_report_pdf(rep, r)
    cert = bsa.certificate_pdf(r, next(i for i in r.items if i.label == "Ex-A13"), None)
    assert pdf[:5] == b"%PDF-" and cert[:5] == b"%PDF-" and bsa.legal_analysis_pdf()[:5] == b"%PDF-"


def test_network_plan_beats_hq_only_and_scales():
    r = network.scale_benchmark(3, 80)
    assert r["network"]["p1_mean_days"] < r["hq_only"]["p1_mean_days"]
    assert r["network"]["makespan_days"] <= r["hq_only"]["makespan_days"]
    assert r["network"]["exhibits"] == r["hq_only"]["exhibits"] and not r["network"]["unplaced"]
    assert r["network"]["plan_seconds"] < 2.0
    cfsl = next(u for u in r["network"]["units"] if u["id"] == "CFSL")
    assert all(a["tier"] in ("P1", "P2") for a in r["network"]["assignments"] if a["unit"] == "CFSL") or cfsl["exhibits"] == 0


def test_capacity_what_if_reduces_hq_backlog():
    kb = load_kb()
    case, _ = __import__("pramaan.benchmark", fromlist=["x"]).synthetic_case(120, 7)
    items = run_triage(case, persist=False).items
    base = network.plan_network(kb, [("C1", items, None)], hq_only=True)
    bott = base["units"][0]["bottleneck"]
    more = network.plan_network(kb, [("C1", items, None)], hq_only=True, add_examiners={bott: 3})
    assert more["makespan_days"] <= base["makespan_days"]


def test_bsa_api_and_mcp_tools():
    sc = json.loads((SCENARIOS_DIR / "01_roadside_homicide.json").read_text())
    with TestClient(create_app()) as c:
        cid = c.post("/api/triage", json=sc).json()["case_id"]
        assert c.get(f"/api/cases/{cid}/authenticity").json()["electronic_records"] >= 2
        assert c.get(f"/api/cases/{cid}/authenticity.pdf").content[:5] == b"%PDF-"
        assert c.get(f"/api/cases/{cid}/items/Ex-A13/bsa63-certificate.pdf").content[:5] == b"%PDF-"
        assert c.get("/api/legal/bsa-analysis.pdf").content[:5] == b"%PDF-"
        assert "network" in c.get("/api/network-plan").json()

    async def run():
        async with Client(mcp) as cl:
            r = await cl.call_tool("record_electronic_evidence", {"case_id": cid, "item": "Ex-A13", "reason": "DVR export at seizure",
                                                                  "details": {"hash_at_acquisition": H, "regular_use": True}})
            assert not r.is_error and r.structured_content["authenticity"]["kind"] == "electronic"
            bad = await cl.call_tool("record_electronic_evidence", {"case_id": cid, "item": "Ex-A8", "reason": "wrong item",
                                                                    "details": {}})
            assert bad.is_error and "not an electronic record" in bad.content[0].text
            a = (await cl.call_tool("assess_evidence_authenticity", {"case_id": cid, "item": "Ex-A13"})).structured_content
            assert a["items"][0]["open_items"]
            cert = (await cl.call_tool("generate_bsa63_certificate", {"case_id": cid, "item": "Ex-A13"})).structured_content
            assert cert["pdf_path"].endswith(".pdf")
            net = (await cl.call_tool("plan_fsl_network", {})).structured_content
            assert "summary" in net
    asyncio.run(run())


def test_privacy_gate_covers_electronic_fields():
    import pytest
    from pramaan.privacy import PrivacyViolation
    er = ElectronicRecord(part_a_signatory_role="owner, phone 9876543210")
    with pytest.raises(PrivacyViolation):
        run_triage(CaseInput(case_ref="T", crime_type="homicide",
                             items=[ItemInput(description="mobile phone of the deceased", electronic=er)]), persist=False)
