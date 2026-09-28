# IBM Bob integration — configuration reference and walkthrough

IBM Bob is Pramaan's **agent front-end**. The officer talks to Bob; Bob drives the Pramaan **MCP server** (backend); every case Bob creates appears live in the **web dashboard** (frontend) and in the hash-chained custody ledger. This document is the Bob counterpart of SAVVYDFIR-MCP's `claude_config/CLAUDE.md` + `.claude/` setup.

## 1. Architecture (Bob in the loop)

```
  Scene Inputs                       Pramaan Engine                  MCP Server
  ────────────                       ──────────────                  ──────────
  seizure list (free text)   ───>   extractor, classifier     ───>  ┌──────────────────┐
  scene context, custody     ───>   degradation, scoring      ───>  │  pramaan-mcp     │
  photo captions             ───>   sequencing, staging       ───>  │  (MCPServer,     │
  knowledge/*.yaml (4 KB)    ───>   scheduler (ATC), gaps     ───>  │   21 tools)      │
                                    reports (PDF / HTML)      ───>  │                  │
                                                                    │  PrivacyGate     │
                                                                    │  AuditLedger     │
                                                                    │  CaseStore       │
                                                                    └────────┬─────────┘
                                                                             │ streamable HTTP /mcp
                                                                             │ (or stdio) JSON-RPC
                                                                             v
                                                                    ┌──────────────────┐
                                                                    │  IBM Bob         │
                                                                    │  Agent Loop      │
                                                                    │                  │
                                                                    │  AGENTS.md       │
                                                                    │  Mode:           │
                                                                    │  forensic-triage │
                                                                    │  Skill:          │
                                                                    │  .bob/skills/    │
                                                                    │  evidence-triage-│
                                                                    │  workflow        │
                                                                    │  Hooks:          │
                                                                    │  .bob/settings   │
                                                                    └────────┬─────────┘
                                                                             │
                                                                             v
                                                                    ┌──────────────────┐
                                                                    │  Output          │
                                                                    │                  │
                                                                    │  state.json      │
                                                                    │  audit.jsonl     │
                                                                    │  report.html     │
                                                                    │  graph.html      │
                                                                    │  packet.pdf      │
                                                                    │  case-notes/*.md │
                                                                    └──────────────────┘
        Web dashboard http://127.0.0.1:8000 reads the same CaseStore + AuditLedger live
```

| SAVVYDFIR-MCP component | Pramaan component | Code |
|---|---|---|
| `SafeRunner` (safe tool execution) | **PrivacyGate** + typed tool wrapper (`ToolError`s, no raw shell) | `pramaan/privacy.py`, `mcp_server.tool` |
| `AuditLogger` (hash-chained `audit.jsonl`) | **AuditLedger** (SQLite hash chain + `audit.jsonl` mirror + per-case `audit.jsonl`) | `pramaan/store.py`, `pramaan/outputs.py` |
| `StateManager` (`state.json`) | **CaseStore** (cases table + per-case `state.json`) | `pramaan/store.py`, `pramaan/outputs.py` |
| Claude Code agent loop + skill | **IBM Bob** agent loop + mode + skills + hooks | `AGENTS.md`, `.bob/` |
| `report.html`, `graph.html` | `report.html`, `graph.html`, `packet.pdf` | `pramaan/outputs.py`, `pramaan/reports.py` |

## 2. What ships in the repository

```
AGENTS.md                                  agent protocol (≈ CLAUDE.md) — auto-loaded by Bob
.bobignore                                 keeps Bob out of src/runtime, *.sqlite3, .env
.bob/
├── mcp.json                               MCP servers: pramaan (HTTP, enabled) + pramaan-stdio (disabled)
├── custom_modes.yaml                      🔬 forensic-triage · 🧪 fsl-liaison · ⚖️ court-reviewer
├── rules/01-pramaan-project.md            injected into every conversation
├── rules-forensic-triage/                 triage protocol · legal guard-rails · output format
├── rules-fsl-liaison/                     lab planning
├── skills/
│   ├── evidence-triage-workflow/          main 7-phase workflow (+ references/flag-playbook.md)
│   ├── exhibit-classification/            confirm/correct types
│   ├── preservation-and-custody/          what-ifs, seals, hand-overs
│   ├── fsl-scheduling/                    lab plan with baselines
│   ├── court-ready-outputs/               packet + output bundle + case note
│   └── tools-reference/                   17-tool contract
├── commands/                              /triage-scene · /fsl-packet · /lab-queue · /verify-custody
├── settings.json                          5 lifecycle hooks
└── hooks/run_hook.sh                      → python -m pramaan.bob_hooks <hook>
bob_config/                                global install (≈ claude_config/): AGENTS.md + install_global.py
case-notes/                                the only folder Bob's triage mode may write
```

## 3. Configuration reference (researched against IBM Bob documentation)

### 3.1 MCP — `.bob/mcp.json`
Bob reads project MCP servers from `.bob/mcp.json` (Bob Settings → MCP → *Edit Project MCP*) and global ones from the global MCP file (`~/.bob/mcp_settings.json`). Both use an `mcpServers` object. Local servers use STDIO (`command`, `args`, `cwd`, `env`, `alwaysAllow`, `disabled`); remote/HTTP servers use `"type": "streamable-http"` with `url`, optional `headers`, `alwaysAllow`, `disabled`, and optionally `timeout` (seconds). Restart Bob or toggle the server after editing.

Pramaan ships:

```json
{
  "mcpServers": {
    "pramaan": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8000/mcp",
      "alwaysAllow": ["describe_tool_catalog", "list_crime_profiles", "lookup_evidence_type", "parse_scene_description",
                      "list_cases", "get_case", "explain_item_priority", "simulate_preservation", "build_fsl_schedule",
                      "lab_queue", "gap_analysis", "verify_custody_ledger"],
      "timeout": 120,
      "disabled": false
    },
    "pramaan-stdio": {
      "command": "python", "args": ["-m", "pramaan.mcp_server"],
      "cwd": "${workspaceFolder}/src",
      "env": { "PYTHONPATH": "${workspaceFolder}/src", "PRAMAAN_MCP_ACTOR": "ibm-bob" },
      "timeout": 120, "disabled": true
    }
  }
}
```

* **HTTP is the default** so Bob and the dashboard share one live database and the case appears on screen as Bob works.
* **Read-only tools are `alwaysAllow`**; state-changing tools (`triage_scene`, `update_item`, `record_custody_event`, `generate_submission_packet`, `export_case_outputs`) always ask the officer for approval — a deliberate human-in-the-loop checkpoint.
* **stdio:** Bob may start stdio servers from a different working directory, so give absolute paths. `python -m pramaan mcp-config --client bob --transport stdio --write` rewrites `.bob/mcp.json` with absolute paths for your machine (use this if your Bob build does not expand `${workspaceFolder}`).

### 3.2 Agent instructions — `AGENTS.md` and rules
Bob composes its instructions from organisation/global → project → mode → skill. The root `AGENTS.md` carries the Pramaan protocol (identity, constraints, tool routing, classification labels, self-correction, 7-phase workflow, completion promises, skill routing, outputs). Every file in `.bob/rules/` is injected into every conversation in every mode; `.bob/rules-<mode-slug>/` applies only to that mode. (`/init` creates per-mode AGENTS.md files; if you run it, keep the Pramaan sections.)

### 3.3 Skills — `.bob/skills/<name>/SKILL.md`
A skill is a folder with a `SKILL.md` whose YAML front-matter has `name` and `description` (Bob uses the description to decide when to activate it) and optionally `user-invocable: true` so it can be run as `/name`. Supporting files (e.g. `references/`) are readable once the skill is active. Project skills (`.bob/skills/`) override global ones (`~/.bob/skills/`) of the same name. Bob asks permission before activating a skill unless auto-activation is allowed in Bob Settings → Skills. Use **Agent/Code-capable modes**; Pramaan's modes include the `skill` tool group.

### 3.4 Custom modes — `.bob/custom_modes.yaml`
`customModes[]` entries with `slug`, `name`, `description`, `roleDefinition`, `whenToUse`, `customInstructions`, `groups`. A group left out is a capability the mode does not get; `edit` can be narrowed with `fileRegex`.

| Mode | Groups | Purpose |
|---|---|---|
| `forensic-triage` 🔬 | read, mcp, skill, todo, edit(`^case-notes/.*\.md$`) | the officer's triage assistant |
| `fsl-liaison` 🧪 | read, mcp, skill | cross-case lab planning |
| `court-reviewer` ⚖️ | read, mcp, skill | sceptical review before the packet leaves (the role SAVVYDFIR gives its corroboration sub-agent; Bob uses modes rather than sub-agent files) |

### 3.5 Lifecycle hooks — `.bob/settings.json`
Bob accepts five events — `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop` — in the Claude-Code-compatible shape `{"hooks": {"<Event>": [{"matcher": "<regex on tool name>", "hooks": [{"type": "command", "command": "...", "timeout": 5}]}]}}`. `matcher` applies to tool events only; exit code **2 blocks** on blocking events. Keep the shape exact: unknown keys can cause Bob to ignore the hook block (our `tests/test_bob_config.py` enforces it). Project hooks live in `.bob/settings.json`; global hooks in `~/.bob/settings/settings.json`.

| Event | Hook | Behaviour |
|---|---|---|
| SessionStart | `session_start` | prints a briefing: open cases, ledger head, rules |
| UserPromptSubmit | `prompt_guard` | exit 2 if the prompt contains Aadhaar / phone / e-mail / hashed protected names; logs `privacy_block` (kind only) |
| PreToolUse (`write_to_file\|apply_diff\|…`) | `write_guard` | exit 2 on writes to `src/runtime/`, `*.sqlite3`, `audit.jsonl` |
| PostToolUse (`use_mcp_tool`) | `mcp_audit` | appends `mcp_call {tool, server, output_sha256, session_id}` to the ledger as `ibm-bob:hook` |
| Stop | `completion_gate` | exit 2 **once per session** if a case Bob triaged has no packet yet (SAVVYDFIR-style completion promise); respects `stop_hook_active` so it never loops |

All hooks run `sh .bob/hooks/run_hook.sh <hook>` → `python -m pramaan.bob_hooks <hook>` with the event JSON on stdin (fields `hook_event_name`, `session_id`, `prompt`, `tool_name`, `tool_input`, `tool_response`, `stop_hook_active`; parsed tolerantly).

### 3.6 Slash commands — `.bob/commands/*.md`
Markdown prompts with `description` / `argument-hint` front-matter: `/triage-scene`, `/fsl-packet`, `/lab-queue`, `/verify-custody`. Skills are also invocable directly, e.g. `/evidence-triage-workflow`.

## 4. Step-by-step: run it

1. **Backend + frontend**
   ```bash
   cd src && python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
   pip install -r requirements-dev.txt && python -m pramaan seed
   PRAMAAN_MCP_ACTOR=ibm-bob python -m pramaan serve               # Windows PowerShell: $env:PRAMAAN_MCP_ACTOR="ibm-bob"
   ```
   Dashboard http://127.0.0.1:8000 · MCP http://127.0.0.1:8000/mcp
2. **Open the repository root in IBM Bob.** Bob Settings → **MCP**: `pramaan` shows connected (21 tools). Bob Settings → **Skills**: six Pramaan skills from the project. Mode picker: the three Pramaan modes.
3. **Pick 🔬 Forensic Triage Officer** and type `/triage-scene homicide` followed by the notes, e.g.
   ```
   Incident 25 Sep 2026 21:30 IST, outdoor, 31 °C, dry; accused in custody since 26 Sep 06:00.
   Ex-A1: half-burnt cigarette butt, 3 m from the body
   Ex-A2: CCTV at toll plaza covering the service road, not yet seized
   Ex-A3: viscera preserved at autopsy, kept at ambient temperature
   Ex-A4: 6 cigarette butts near the parked lorry, 40 m from the body
   ```
   Bob activates `evidence-triage-workflow`, calls `parse_scene_description`, shows the table, then `triage_scene` (approve it) and answers ACT NOW first.
4. **Watch the dashboard**: the case appears in the sidebar; *Custody ledger* shows `ibm-bob` (tool actions) and `ibm-bob:hook` (audit) rows.
5. Ask follow-ups: *"Why is Ex-A1 P1?"*, *"What if the viscera is refrigerated?"*, *"Ex-A4 was actually 2 m away"* (Bob uses `update_item` with a reason), *"Hand Ex-A1 to the Malkhana, seal intact."*
6. **Finish**: `/fsl-packet <case_id>` → Bob verifies the ledger, generates the bundle (`state.json`, `audit.jsonl`, `report.html`, `graph.html`, `packet.md`, `packet.pdf`) and writes `case-notes/<case_id>.md`. If Bob tries to stop before this, the Stop hook sends it back once.
7. **Lab view**: switch to 🧪 FSL Liaison → `/lab-queue`. **Review**: switch to ⚖️ Court Readiness Reviewer → *"Is PRM-… court-ready?"*
8. **Optional — use Pramaan from any folder**: `python bob_config/install_global.py` (merges into `~/.bob/`; `--dry-run`, `--uninstall`).

## 5. Verification checklist

| Check | How | Expected |
|---|---|---|
| Hook wiring | `echo '{"prompt":"call 9876543210"}' \| sh .bob/hooks/run_hook.sh prompt_guard; echo $?` | message on stderr, `2` |
| Write guard | `echo '{"tool_name":"write_to_file","tool_input":{"path":"src/runtime/x.sqlite3"}}' \| sh .bob/hooks/run_hook.sh write_guard; echo $?` | `2` |
| Config shape | `cd src && pytest tests/test_bob_config.py` | pass |
| MCP reachable | open http://127.0.0.1:8000/#/mcp | 21 tools listed |
| End-to-end without Bob | `cd src && python -m pramaan mcp-demo` | transcript ending in `verify_custody_ledger` ok |

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `pramaan` red/disconnected in Bob | start the backend; check port; `PRAMAAN_ALLOWED_HOSTS` includes `127.0.0.1:*`; restart Bob after editing `mcp.json` |
| Skills not offered | Bob Settings → Skills: check they are listed from `.bob/skills/`; use a mode with the `skill` group; invoke with `/evidence-triage-workflow` |
| Mode missing | YAML error in `.bob/custom_modes.yaml` — run `pytest tests/test_bob_config.py` |
| Hooks never fire | shape must match §3.5 exactly; on Windows run Bob with Git Bash/WSL available for `sh`, or set `PRAMAAN_PYTHON` |
| Cases don't appear in dashboard | Bob must use the HTTP server (or the same `PRAMAAN_HOME` for stdio) |
| Ledger shows `mcp-client` instead of `ibm-bob` | start the server with `PRAMAAN_MCP_ACTOR=ibm-bob` |

## 7. Sources

* IBM Bob docs — Create and use skills: https://bob.ibm.com/docs/ide/tutorials/use-skills
* IBM Bob docs — Standardize Bob's behavior (rules, `/init`, AGENTS.md): https://bob.ibm.com/docs/ide/tutorials/standardize-bobs-behavior
* IBM Bob docs — Using MCP in Bob: https://bob.ibm.com/docs/ide/configuration/mcp/mcp-in-bob
* IBM Bob docs — Add a custom mode: https://bob.ibm.com/docs/ide/tutorials/add-bob-capabilities
* IBM Documentation examples of `.bob/mcp.json` with `streamable-http`, `alwaysAllow`, `timeout` (e.g. Guardium Data Protection, Decision Intelligence integrations)
* Community configuration references for Bob hook events and file locations (rulesync `bob` target; Bob hackathon kits using `.bob/settings.json` hooks)
* Reference architecture: https://github.com/kismatkunwar89/SAVVYDFIR-MCP (`claude_config/CLAUDE.md`, `.claude/skills`, hooks)

Bob evolves quickly; if a field name differs in your Bob version, the contract tests in `src/tests/test_bob_config.py` show exactly which shape Pramaan assumes.
