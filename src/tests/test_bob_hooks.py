"""IBM Bob lifecycle hooks: privacy block, evidence-store write guard, MCP audit, session briefing."""

import io
import json

from pramaan import bob_hooks
from pramaan.store import Store


def run(name, payload):
    return bob_hooks.main([name], io.StringIO(json.dumps(payload)))


def test_prompt_guard_blocks_identifiers_and_logs():
    assert run("prompt_guard", {"event": "UserPromptSubmit", "prompt": "victim's brother 9876543210 saw a knife"}) == 2
    assert Store().ledger()[0]["action"] == "privacy_block"
    assert run("prompt_guard", {"prompt": "Ex-A1: knife 2 m from the body"}) == 0


def test_write_guard_protects_evidence_store():
    assert run("write_guard", {"tool": "write_to_file", "input": {"path": "src/runtime/pramaan.sqlite3"}}) == 2
    assert run("write_guard", {"tool": "apply_diff", "tool_input": {"file_path": "src/runtime/audit.jsonl"}}) == 2
    assert run("write_guard", {"tool": "write_to_file", "input": {"path": "case-notes/PRM-1.md"}}) == 0


def test_mcp_audit_and_session_briefing(capsys):
    assert run("mcp_audit", {"tool": "use_mcp_tool", "input": {"server_name": "pramaan", "tool_name": "triage_scene"},
                             "output": {"case_id": "PRM-X"}}) == 0
    e = Store().ledger()[0]
    assert e["actor"] == "ibm-bob:hook" and e["payload"]["tool"] == "triage_scene" and e["payload"]["output_sha256"]
    assert run("session_start", {}) == 0
    assert "Pramaan briefing" in capsys.readouterr().out
    assert bob_hooks.main(["unknown"], io.StringIO("")) == 0  # never breaks a session


def test_claude_compatible_payloads_and_completion_gate(monkeypatch):
    """Bob's hook contract is Claude-Code-shaped: tool_name/tool_input/tool_response, stop_hook_active."""
    import json as _json
    from pramaan.config import SCENARIOS_DIR
    from pramaan.models import CaseInput
    from pramaan.pipeline import run_triage
    store = Store()
    case = CaseInput(**_json.loads((SCENARIOS_DIR / "03_burglary_night.json").read_text()))
    r = run_triage(case, store=store, actor="ibm-bob")
    payload = {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "use_mcp_tool",
               "tool_input": {"server_name": "pramaan", "tool_name": "triage_scene", "arguments": "{}"},
               "tool_response": {"case_id": r.case_id}}
    assert run("mcp_audit", payload) == 0
    assert Store().ledger()[0]["payload"]["tool"] == "triage_scene"
    stop = {"hook_event_name": "Stop", "session_id": "s1", "stop_hook_active": False}
    assert run("completion_gate", stop) == 2          # packet missing -> Bob must continue
    assert run("completion_gate", stop) == 0          # but only once per session
    assert run("completion_gate", {"session_id": "s2", "stop_hook_active": True}) == 0
    from pramaan import outputs
    outputs.export_case(store, r.case_id)
    store.append("ibm-bob", "packet_generated", {}, case_id=r.case_id)
    assert run("completion_gate", {"session_id": "s3"}) == 0
