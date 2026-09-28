"""IBM Bob lifecycle hooks — guard-rails and audit enforced in code around the agent.

Configured in ``.bob/settings.json``; each hook runs ``sh .bob/hooks/run_hook.sh <name>``
which calls ``python -m pramaan.bob_hooks <name>`` with the event JSON on stdin.

    session_start  SessionStart      print a briefing (open cases, ledger head, rules) — injected into Bob's context
    prompt_guard   UserPromptSubmit  exit 2 (block) if the prompt contains Aadhaar / phone / e-mail / protected names
    write_guard    PreToolUse        exit 2 (block) writes to the evidence store (runtime/, *.sqlite3, audit.jsonl)
    mcp_audit      PostToolUse       append every Pramaan MCP call Bob made to the hash-chained ledger
    completion_gate Stop             block finishing ONCE if a case Bob triaged has no FSL packet / outputs yet

Payloads follow the Claude-Code-compatible hook contract Bob uses (``hook_event_name``, ``session_id``,
``prompt``, ``tool_name``, ``tool_input``, ``tool_response``, ``stop_hook_active``); exit code 2 blocks.

Parsing is tolerant of field-name differences between Bob versions. Audit hooks fail open
(never break the session); the privacy and write guards fail closed on a positive match.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, TextIO

from . import privacy
from .store import Store

ACTOR = "ibm-bob:hook"
BLOCK = 2
GATE_WINDOW_H = 12
_PROTECTED_PATH = re.compile(r"(^|[\\/])(runtime[\\/]|[^\\/]*\.sqlite3(-wal|-shm)?$|audit\.jsonl$)", re.I)


def _find(obj: Any, keys: tuple[str, ...]) -> Any:
    """Depth-first search for the first matching key in nested dicts."""
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] not in (None, ""):
                return obj[k]
        for v in obj.values():
            hit = _find(v, keys)
            if hit is not None:
                return hit
    return None


def session_start(_: dict) -> int:
    store = Store()
    cases = store.list_cases()[:5]
    head = store.head()
    print("[Pramaan briefing] Evidence-triage MCP server 'pramaan' is available. Use its tools for every score, tier, "
          "flag and schedule; never estimate them yourself. Never enter personal names, phone, Aadhaar or e-mail.")
    if cases:
        print("Open cases (newest first):")
        for c in cases:
            n = c.get("counts", {})
            print(f"  - {c['case_id']} | {c['case_ref']} | {c['crime_type']} | P1 {n.get('P1', 0)} / total {n.get('total', 0)}")
    else:
        print("No cases yet — start with parse_scene_description then triage_scene.")
    if head:
        print(f"Ledger head: seq {head['seq']} {head['hash'][:16]}…")
    return 0


def prompt_guard(data: dict) -> int:
    prompt = _find(data, ("prompt", "user_prompt", "message", "text", "content"))
    if not isinstance(prompt, str):
        return 0
    kinds = privacy.scan([prompt])
    if not kinds:
        return 0
    try:
        Store().append(ACTOR, "privacy_block", {"kinds": kinds, "surface": "bob_prompt"})
    except Exception:  # pragma: no cover - audit must not mask the block
        pass
    print(f"Blocked by Pramaan privacy guard: the prompt contains {', '.join(kinds)}. Describe exhibits only — no names, "
          "phone, Aadhaar or e-mail (BNS 2023 §72, DPDP Act 2023).", file=sys.stderr)
    return BLOCK


def write_guard(data: dict) -> int:
    path = _find(data, ("path", "file_path", "target_file", "filePath", "file"))
    if isinstance(path, str) and _PROTECTED_PATH.search(path.replace("\\", "/")):
        print(f"Blocked by Pramaan write guard: '{path}' is part of the evidence store / custody ledger. "
              "Use the Pramaan MCP tools (update_item, record_custody_event) instead.", file=sys.stderr)
        return BLOCK
    return 0


def mcp_audit(data: dict) -> int:
    inner = data.get("tool_input") or data.get("input") or {}
    tool = _find(inner, ("tool_name", "toolName", "name")) or _find(data, ("tool_name", "toolName", "mcp_tool", "name"))
    server = _find(inner, ("server_name", "serverName", "server")) or _find(data, ("server_name", "serverName", "server"))
    if server and "pramaan" not in str(server).lower():
        return 0
    output = _find(data, ("tool_response", "output", "tool_output", "result", "response"))
    digest = hashlib.sha256(json.dumps(output, sort_keys=True, default=str).encode()).hexdigest() if output is not None else None
    case_id = _find(inner, ("case_id",)) or _find(data, ("case_id",))
    try:
        Store().append(ACTOR, "mcp_call", {"tool": tool, "server": server, "output_sha256": digest,
                                           "session_id": data.get("session_id")},
                       case_id=case_id if isinstance(case_id, str) else None)
    except Exception:
        pass
    return 0


def completion_gate(data: dict) -> int:
    """SAVVYDFIR-style completion promise: a case triaged by Bob must end with its packet/outputs generated."""
    if data.get("stop_hook_active"):
        return 0  # already continuing because of this hook — never loop
    store = Store()
    since = datetime.now(timezone.utc) - timedelta(hours=GATE_WINDOW_H)
    pending: list[str] = []
    for c in store.list_cases():
        entries = store.ledger(c["case_id"], limit=500)  # newest first
        bob = [e for e in entries if e["actor"].startswith("ibm-bob") and e["action"] in ("triage", "retriage")
               and datetime.fromisoformat(e["ts"]) >= since]
        if not bob:
            continue
        last_triage = bob[0]["seq"]
        done = any(e["action"] in ("packet_generated", "outputs_exported") and e["seq"] > last_triage for e in entries)
        if not done:
            pending.append(c["case_id"])
    if not pending:
        return 0
    marker = store.db_path.parent / f".stopgate-{data.get('session_id', 'nosession')}"
    if marker.exists():
        return 0  # block at most once per session
    marker.write_text(",".join(pending), encoding="utf-8")
    print("Completion gate (Pramaan): case(s) " + ", ".join(pending) + " were triaged in this session but have no FSL "
          "packet yet. Call generate_submission_packet for each, save the markdown to case-notes/<case_id>.md, then "
          "report the output file URLs.", file=sys.stderr)
    return BLOCK


HOOKS = {"session_start": session_start, "prompt_guard": prompt_guard, "write_guard": write_guard, "mcp_audit": mcp_audit,
         "completion_gate": completion_gate}


def main(argv: list[str] | None = None, stdin: TextIO | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in HOOKS:
        print(f"usage: python -m pramaan.bob_hooks {{{'|'.join(HOOKS)}}}", file=sys.stderr)
        return 0
    raw = (stdin or sys.stdin).read() if not (stdin or sys.stdin).isatty() else ""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {"prompt": raw}
    try:
        return HOOKS[argv[0]](data if isinstance(data, dict) else {"prompt": str(data)})
    except Exception as exc:  # fail open for anything unexpected
        print(f"pramaan hook {argv[0]} error: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
