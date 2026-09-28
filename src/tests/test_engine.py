"""Engine tests: knowledge base, classifier, parser, scoring, staging, scheduler, ledger, privacy, LLM guardrails."""

import dataclasses
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from pramaan import knowledge, privacy
from pramaan.benchmark import run_benchmark, synthetic_case
from pramaan.classifier import classify
from pramaan.config import SCENARIOS_DIR, Settings
from pramaan.extractor import parse_description
from pramaan.knowledge import KnowledgeBaseError, load_kb
from pramaan.llm.client import WatsonxLLM, extract_json
from pramaan.llm.tasks import llm_classify
from pramaan.models import CaseInput, ItemInput
from pramaan.pipeline import run_triage
from pramaan.store import Store

SCENARIOS = sorted(SCENARIOS_DIR.glob("*.json"))


def load(name):
    return CaseInput(**json.loads((SCENARIOS_DIR / f"{name}.json").read_text()))


def test_kb_loads_validates_and_hashes():
    kb = load_kb()
    assert len(kb.types) >= 40 and len(kb.profiles) >= 10
    assert len(kb.kb_hash) == 64


def test_kb_fails_closed_on_bad_reference():
    kb = load_kb()
    bad = dataclasses.replace(kb, exams={**kb.exams, "bogus": {"division": "NOPE", "hours": 1}})
    with pytest.raises(KnowledgeBaseError):
        knowledge._validate(bad)


def test_distance_to_body_changes_priority():
    kb = load_kb()
    near = classify(kb, "cigarette butt, 2 m from the body")
    far = classify(kb, "cigarette butt, 40 m from the body")
    assert near.context_boost > far.context_boost
    assert "near_body" not in far.classification.context_signals


@pytest.mark.parametrize("text,qty", [
    ("two-wheeler of the deceased near toll plaza", 1),
    ("4 mobile phones seized from the accused", 4),
    ("bloodstained stone approx 2 kg near the body", 1),
    ("two empty liquor bottles beside the lorry", 2),
])
def test_extractor_quantities(text, qty):
    items, _ = parse_description(load_kb(), text)
    assert items[0].quantity == qty


def test_not_collected_item_gets_collect_now():
    r = run_triage(load("01_roadside_homicide"), persist=False)
    a12 = next(i for i in r.items if i.label == "Ex-A12")
    assert not a12.collected and any(f.code == "COLLECT_NOW" for f in a12.flags) and a12.tier == "P1"


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_scenarios_meet_ground_truth(path):
    data = json.loads(path.read_text())
    r = run_triage(CaseInput(**data), persist=False)
    p1 = {i.label for i in r.items if i.tier == "P1"}
    exp = data.get("expect", {})
    assert set(exp.get("p1_must_include", [])) <= p1
    for label, code in exp.get("flags", {}).items():
        assert any(f.code == code for i in r.items if i.label == label for f in i.flags)
    assert not r.parse_warnings


def test_statutory_floor_for_sexual_assault_kit():
    r = run_triage(load("02_sexual_assault_clinical"), persist=False)
    kit = next(i for i in r.items if i.label == "Ex-S1")
    assert kit.score.epi >= 85 and kit.rank == 1


def test_ranking_is_deterministic():
    a = run_triage(load("01_roadside_homicide"), persist=False)
    b = run_triage(load("01_roadside_homicide"), persist=False)
    assert [i.model_dump() for i in a.items] == [i.model_dump() for i in b.items]
    assert a.schedule.model_dump() == b.schedule.model_dump()


def test_benchmark_needles_and_scheduler_gain():
    r = run_benchmark(200)
    assert all(n["tier"] == "P1" for n in r.needles)
    p, sq = r.policies["pramaan"], r.policies["status_quo"]
    assert p["value_retained"] > sq["value_retained"]
    assert p["late"] <= sq["late"] and p["p1_mean_days"] < sq["p1_mean_days"]


def test_staging_never_holds_near_body_traces():
    case, needles = synthetic_case(200)
    r = run_triage(case, persist=False)
    held = [i for i in r.items if i.stage == 2]
    assert held and all((i.classification.distance_m or 999) > 10 for i in held)


def test_officer_override_requires_reason():
    with pytest.raises(ValidationError):
        ItemInput(description="knife near the body", override_tier="P1")


def test_ledger_detects_tampering(tmp_path):
    s = Store(tmp_path / "l.sqlite3")
    for n in range(3):
        s.append("t", "event", {"n": n})
    assert s.verify()["ok"]
    with sqlite3.connect(tmp_path / "l.sqlite3") as c:
        c.execute("UPDATE ledger SET payload='{\"n\":99}' WHERE seq=2")
    v = s.verify()
    assert not v["ok"] and v["first_bad_seq"] == 2


def test_stored_result_integrity():
    store = Store()
    r = run_triage(load("03_burglary_night"), store=store)
    assert store.verify_case(r.case_id)["ok"]
    with sqlite3.connect(store.db_path) as c:
        c.execute("UPDATE cases SET result_json=replace(result_json, '\"P1\"', '\"P3\"')")
    assert not store.verify_case(r.case_id)["ok"]


def test_privacy_gate_blocks_identifiers(isolated_home):
    base = load("01_roadside_homicide")
    for bad in ("phone of informant 9876543210", "Aadhaar 2345 6789 0123 seen on card", "mail x.y@example.com"):
        with pytest.raises(privacy.PrivacyViolation):
            run_triage(base.model_copy(update={"description": f"Ex-1: knife near the body, {bad}"}), persist=False)
    (isolated_home / "protected.sha256").write_text(privacy.hash_term("Asha Rani") + "\n")
    privacy._protected_hashes.cache_clear()
    with pytest.raises(privacy.PrivacyViolation):
        run_triage(base.model_copy(update={"description": "Ex-1: dupatta of asha rani near the body"}), persist=False)
    run_triage(base, persist=False)  # FIR numbers, weights and distances are not identifiers


class FakeLLM:
    name = "fake"

    def chat(self, system, user, max_tokens=900):
        if "closed list" in system:
            return '```json\n{"type_id": "sharp_weapon", "confidence": 0.9}\n```'
        return "Forwarding note drafted by the model."


def test_llm_proposes_type_but_rules_dispose():
    item = ItemInput(label="X1", description="unfamiliar shiny object near the body")
    case = CaseInput(case_ref="T-1", crime_type="homicide", items=[item])
    r = run_triage(case, persist=False, llm=FakeLLM())
    it = r.items[0]
    assert it.classification.method == "llm" and it.classification.type_id == "sharp_weapon"
    hinted = run_triage(case.model_copy(update={"items": [item.model_copy(update={"type_hint": "sharp_weapon"})]}), persist=False)
    assert it.score.epi == hinted.items[0].score.epi  # the model chose a type; the score is pure rules
    assert r.llm_provider == "fake"


def test_watsonx_client_with_mock_transport(monkeypatch):
    monkeypatch.setenv("WATSONX_API_KEY", "k")
    monkeypatch.setenv("WATSONX_PROJECT_ID", "p")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "identity/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        body = json.loads(request.content)
        assert body["model_id"] and body["project_id"] == "p" and request.headers["Authorization"] == "Bearer tok"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"type_id": "not_a_type"}'}}]})

    llm = WatsonxLLM(Settings(), transport=httpx.MockTransport(handler))
    assert llm_classify(llm, load_kb(), "thing") is None  # out-of-vocabulary answers are rejected
    assert any("/ml/v1/text/chat" in u for u in calls)
    assert extract_json('noise {"a": 1} noise') == {"a": 1}
