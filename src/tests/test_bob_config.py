"""Static contract checks for the IBM Bob workspace config — Bob silently ignores malformed hook/MCP entries,
so these tests guard the exact shapes (keys, events, tool names, skill frontmatter, mode groups)."""

import json
from pathlib import Path

import yaml

from pramaan.mcp_server import TOOL_CATALOG

ROOT = Path(__file__).resolve().parents[2]
BOB = ROOT / ".bob"
TOOLS = {t["name"] for t in TOOL_CATALOG}


def test_mcp_json_shape_and_tool_names():
    cfg = json.loads((BOB / "mcp.json").read_text())
    allowed = {"type", "url", "headers", "command", "args", "cwd", "env", "alwaysAllow", "disabled", "timeout"}
    for name, srv in cfg["mcpServers"].items():
        assert set(srv) <= allowed, (name, set(srv) - allowed)
        assert ("url" in srv) != ("command" in srv)
        assert set(srv.get("alwaysAllow", [])) <= TOOLS
    enabled = [s for s in cfg["mcpServers"].values() if not s.get("disabled")]
    assert enabled and enabled[0]["url"].endswith("/mcp")


def test_hooks_use_only_bob_events_and_keys():
    hooks = json.loads((BOB / "settings.json").read_text())["hooks"]
    assert set(hooks) <= {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"}
    for event, entries in hooks.items():
        for e in entries:
            assert set(e) <= {"matcher", "hooks"}
            if "matcher" in e:
                assert event in ("PreToolUse", "PostToolUse")
            for h in e["hooks"]:
                assert set(h) <= {"type", "command", "timeout"} and h["type"] == "command"
                assert "run_hook.sh" in h["command"]
    from pramaan.bob_hooks import HOOKS
    for entries in hooks.values():
        for e in entries:
            for h in e["hooks"]:
                assert h["command"].split()[-1] in HOOKS


def test_skills_modes_and_commands():
    skills = sorted((BOB / "skills").glob("*/SKILL.md"))
    assert len(skills) >= 6
    for s in skills:
        fm = yaml.safe_load(s.read_text().split("---")[1])
        assert fm["name"] == s.parent.name and len(fm["description"]) > 40
    modes = yaml.safe_load((BOB / "custom_modes.yaml").read_text())["customModes"]
    valid = {"read", "edit", "browser", "command", "execute", "mcp", "skill", "todo", "mode", "subtask", "workflow"}
    for m in modes:
        assert {"slug", "name", "roleDefinition", "groups"} <= set(m)
        for g in m["groups"]:
            assert (g if isinstance(g, str) else g[0]) in valid
    for c in (BOB / "commands").glob("*.md"):
        assert "description:" in c.read_text().split("---")[1]
    agents = (ROOT / "AGENTS.md").read_text()
    for t in ("triage_scene", "generate_submission_packet", "verify_custody_ledger"):
        assert t in agents


def test_global_installer_dry_run(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("inst", ROOT / "bob_config" / "install_global.py")
    inst = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inst)
    monkeypatch.setattr(inst, "HOME", tmp_path / ".bob")
    plan = {p.name: t for p, t, _ in inst.plan(False)}
    assert "PRAMAAN:BEGIN" in plan["AGENTS.md"]
    assert json.loads(plan["mcp_settings.json"])["mcpServers"]["pramaan"]["args"] == ["-m", "pramaan.mcp_server"]
    assert "Stop" in json.loads(plan["settings.json"])["hooks"]
