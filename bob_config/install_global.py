#!/usr/bin/env python3
"""Install Pramaan's IBM Bob configuration at USER level (all workspaces) — the counterpart of SAVVYDFIR's
claude_config/ install. Project-level config in .bob/ already works without this script; use it when you want
Bob to reach Pramaan from any folder.

    python bob_config/install_global.py            # install / update
    python bob_config/install_global.py --dry-run  # show what would change
    python bob_config/install_global.py --uninstall

Writes (merging, never clobbering other entries):
    ~/.bob/AGENTS.md                 Pramaan protocol section between markers
    ~/.bob/skills/<pramaan skills>/  copied from .bob/skills/
    ~/.bob/mcp_settings.json         "pramaan" stdio server with absolute paths
    ~/.bob/settings/settings.json    lifecycle hooks with absolute paths
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOME = Path.home() / ".bob"
BEGIN, END = "<!-- PRAMAAN:BEGIN -->", "<!-- PRAMAAN:END -->"
EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")


def _python() -> str:
    venv = REPO / "src" / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return str(venv if venv.exists() else Path(sys.executable))


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except json.JSONDecodeError:
        sys.exit(f"{path} is not valid JSON — fix it before installing")


def plan(uninstall: bool) -> list[tuple[Path, str | None, str]]:
    """Return [(path, new_text_or_None_to_delete, description)]."""
    out: list[tuple[Path, str | None, str]] = []
    agents = HOME / "AGENTS.md"
    old = agents.read_text(encoding="utf-8") if agents.is_file() else ""
    if BEGIN in old:
        old = old.split(BEGIN)[0].rstrip() + "\n" + old.split(END, 1)[-1].lstrip()
    section = "" if uninstall else f"\n{BEGIN}\n{(REPO / 'bob_config' / 'AGENTS.md').read_text(encoding='utf-8')}\n{END}\n"
    out.append((agents, (old.rstrip() + "\n" + section).lstrip(), "AGENTS.md Pramaan section"))

    mcp_path = HOME / "mcp_settings.json"
    mcp = _load(mcp_path)
    servers = mcp.setdefault("mcpServers", {})
    servers.pop("pramaan", None)
    if not uninstall:
        servers["pramaan"] = {
            "command": _python(), "args": ["-m", "pramaan.mcp_server"], "cwd": str(REPO / "src"),
            "env": {"PYTHONPATH": str(REPO / "src"), "PRAMAAN_HOME": str(REPO / "src" / "runtime"), "PRAMAAN_MCP_ACTOR": "ibm-bob"},
            "alwaysAllow": ["describe_tool_catalog", "list_crime_profiles", "lookup_evidence_type", "parse_scene_description",
                            "list_cases", "get_case", "explain_item_priority", "simulate_preservation", "build_fsl_schedule",
                            "lab_queue", "gap_analysis", "verify_custody_ledger"],
            "timeout": 120, "disabled": False,
        }
    out.append((mcp_path, json.dumps(mcp, indent=2) + "\n", "mcp_settings.json 'pramaan' server"))

    settings_path = HOME / "settings" / "settings.json"
    settings = _load(settings_path)
    hooks = settings.setdefault("hooks", {})
    runner = f'sh "{REPO / ".bob" / "hooks" / "run_hook.sh"}"'
    project = json.loads((REPO / ".bob" / "settings.json").read_text(encoding="utf-8"))["hooks"]
    for event in EVENTS:
        kept = [e for e in hooks.get(event, []) if not any("run_hook.sh" in h.get("command", "") and "pramaan" in h.get("command", "").lower()
                                                           or str(REPO) in h.get("command", "") for h in e.get("hooks", []))]
        if not uninstall:
            for entry in project.get(event, []):
                e = json.loads(json.dumps(entry))
                for h in e["hooks"]:
                    h["command"] = h["command"].replace("sh .bob/hooks/run_hook.sh", runner)
                kept.append(e)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    out.append((settings_path, json.dumps(settings, indent=2) + "\n", "settings.json lifecycle hooks"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()
    for path, text, desc in plan(a.uninstall):
        print(f"{'would write' if a.dry_run else 'writing'} {path}  ({desc})")
        if not a.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text or "", encoding="utf-8")
    src, dst = REPO / ".bob" / "skills", HOME / "skills"
    for skill in sorted(p for p in src.iterdir() if p.is_dir()):
        target = dst / skill.name
        print(f"{'would ' if a.dry_run else ''}{'remove' if a.uninstall else 'copy'} skill {skill.name} -> {target}")
        if not a.dry_run:
            shutil.rmtree(target, ignore_errors=True)
            if not a.uninstall:
                shutil.copytree(skill, target)
    print("Done. Restart IBM Bob to load the global configuration." if not a.dry_run else "Dry run only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
