# Pramaan — source

Python 3.11+ package `pramaan` plus a zero-dependency web dashboard.

| Path | What |
|---|---|
| `pramaan/knowledge/*.yaml` | The forensic knowledge base (4 layers) — evidence types, lab divisions & examinations, degradation profiles, crime profiles |
| `pramaan/pipeline.py` | End-to-end triage (parse → classify → degrade → score → flag → sequence → stage → schedule → gaps → hash → ledger) |
| `pramaan/bob_hooks.py` | IBM Bob lifecycle hooks (privacy block, write guard, MCP audit, session briefing) |
| `pramaan/mcp_server.py` | MCP server (21 tools, 3 resources, 1 prompt) — stdio and streamable HTTP |
| `pramaan/api.py` | FastAPI REST API + static dashboard + `/mcp` endpoint in one process |
| `pramaan/cli.py` | `python -m pramaan triage | serve | mcp | seed | benchmark | ledger | mcp-config | mcp-demo` |
| `web/` | Dashboard (vanilla HTML/CSS/JS, no CDN, works air-gapped) |
| `scenarios/` | Synthetic case files with ground-truth expectations |
| `tests/` | pytest suite (engine, API, MCP, CLI) |
| `scripts/` | `capture_demo.py` (screenshots/video), `presubmit_check.py` (submission validator) |

```bash
cd src
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest                                                  # all tests
python -m pramaan seed                                  # load the 4 synthetic scenarios
python -m pramaan serve                                 # http://127.0.0.1:8000  (MCP at /mcp)
```

Full instructions: [`../docs/setup-guide.md`](../docs/setup-guide.md).
