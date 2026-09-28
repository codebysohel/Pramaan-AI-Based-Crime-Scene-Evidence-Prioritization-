# Pramaan project rules (all modes)

- This repository is **Pramaan**, an explainable crime-scene evidence triage system. The backend (FastAPI + MCP server) runs with `cd src && python -m pramaan serve`; the dashboard is at http://127.0.0.1:8000 and the MCP endpoint at http://127.0.0.1:8000/mcp.
- Forensic reasoning lives in `src/pramaan/knowledge/*.yaml`. Any KB edit changes the KB hash on new results — run `cd src && python -m pytest` after editing.
- Never write to `src/runtime/`, `*.sqlite3` or `audit.jsonl` (evidence store and custody ledger). Hooks block this.
- Never introduce personal names, phone, Aadhaar or e-mail data into code, tests, scenarios or notes. All scenarios are synthetic.
- Scores are deterministic rules; do not propose "AI-adjusted" scores.
