# bob_config — IBM Bob configuration package

The counterpart of SAVVYDFIR-MCP's `claude_config/`. Everything IBM Bob needs is already in the repo at **project level** (`AGENTS.md`, `.bob/`), so opening this folder in Bob is enough. This folder adds:

| File | Purpose |
|---|---|
| `AGENTS.md` | The Pramaan agent protocol (identity, constraints, tool routing, classification, self-correction, workflow, completion promises, skill routing, outputs). Identical to the root `AGENTS.md`. |
| `install_global.py` | Installs the protocol, skills, stdio MCP server and hooks into `~/.bob/` so Bob can use Pramaan from **any** workspace. Merges; never overwrites unrelated entries. `--dry-run`, `--uninstall`. |

Mapping from the Claude Code layout used by SAVVYDFIR-MCP:

| SAVVYDFIR-MCP (Claude Code) | Pramaan (IBM Bob) |
|---|---|
| `claude_config/CLAUDE.md` | `AGENTS.md` (project) / `~/.bob/AGENTS.md` (global) |
| `.claude/skills/<name>/SKILL.md` | `.bob/skills/<name>/SKILL.md` (6 skills, `/name` to invoke) |
| `.claude/agents/*.md` (sub-agents) | `.bob/custom_modes.yaml` (3 modes) + skills — Bob uses modes, not sub-agent files |
| `.claude/settings.json` hooks | `.bob/settings.json` hooks (5 events) → `.bob/hooks/run_hook.sh` → `pramaan.bob_hooks` |
| `.claude/settings.json` permissions | MCP `alwaysAllow` + mode `groups` (edit limited by `fileRegex`) |
| `.mcp.json` | `.bob/mcp.json` (project) / `~/.bob/mcp_settings.json` (global) |
| slash commands | `.bob/commands/*.md` |
| — | `.bob/rules/`, `.bob/rules-<mode>/` (always-injected rules), `.bobignore` |
