# Setup Guide

Tested end-to-end on Ubuntu 24.04 (Python 3.12) and with Docker. Windows/macOS commands are given where they differ.

## 1. Prerequisites

| Need | Version | Check |
|---|---|---|
| Python | 3.11 or newer | `python --version` |
| pip | recent | `python -m pip --version` |
| Git | any | `git --version` |
| Docker (optional) | 24+ with Compose | `docker compose version` |

No internet access is needed at runtime. IBM Cloud credentials are optional (only for the watsonx.ai layer).

## 2. Install and test

```bash
git clone <your-repo-url> pramaan && cd pramaan/src
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
cp .env.example .env                 # optional; defaults work offline (Windows: copy .env.example .env)
pytest                               # expected: 46 passed
```

## 3. Run the app

```bash
python -m pramaan seed               # triage the 4 synthetic scenarios into src/runtime/
python -m pramaan serve              # dashboard http://127.0.0.1:8000 , MCP http://127.0.0.1:8000/mcp
```

Open `http://127.0.0.1:8000`:

1. **Cases** (left) → *Cr. No. 784/2026 …* → **Evidence queue**: ACT NOW panel and ranked exhibits. Click a row for the explanation drawer; try *What if stored as → refrigerated* on **Ex-A17**.
2. **Lab plan**: policy comparison and Gantt; click a baseline card to compare.
3. **Custody ledger** → *Verify entire hash chain*.
4. **FSL packet** → *Open PDF packet*.
5. **+ New triage** → *Load* a scenario → *Run triage*; or paste your own list (one exhibit per line).
6. **Benchmark** → 200-exhibit synthetic run. **Lab queue** → one queue across all cases.

CLI equivalents:

```bash
python -m pramaan triage 01_roadside_homicide --packet /tmp/packet.pdf
python -m pramaan benchmark --n 200
python -m pramaan ledger verify
```

## 4. Connect IBM Bob (recommended agent front-end)

Start the backend with `PRAMAAN_MCP_ACTOR=ibm-bob python -m pramaan serve`, open the repository folder in IBM Bob (it reads `.bob/mcp.json`, custom modes, rules, hooks and `AGENTS.md`), choose **🔬 Forensic Triage Officer**, and paste a seizure list. Full walkthrough: [bob-integration.md](bob-integration.md).

## 4b. Connect another MCP client

**stdio (recommended for desktop clients).** Print a config with absolute paths and paste it into your client (e.g. `claude_desktop_config.json`, VS Code `mcp.json`):

```bash
python -m pramaan mcp-config
```

Clients that read a project-level `.mcp.json` (e.g. Claude Code) can use the one at the repo root as-is — start them from the repo root with the virtual environment active.

**Streamable HTTP.** While `python -m pramaan serve` runs, point the client at `http://127.0.0.1:8000/mcp`. Cases created this way show up in the dashboard live.

**Smoke test without any client:**

```bash
python -m pramaan mcp-demo          # real MCP client session in-process; prints the transcript
```

Try asking your assistant: *"Use Pramaan to triage this homicide scene: …notes… Show ACT NOW items first, then the top 10 with tier and EPI exactly as returned."*

## 5. Optional: IBM watsonx.ai layer

In `src/.env`:

```
PRAMAAN_LLM_PROVIDER=watsonx
WATSONX_URL=https://us-south.ml.cloud.ibm.com
WATSONX_API_KEY=<IBM Cloud API key>
WATSONX_PROJECT_ID=<watsonx project id>
WATSONX_MODEL_ID=ibm/granite-4-h-small
```

Restart the server; the header shows `LLM watsonx:ibm/granite-4-h-small`. If credentials are missing or the service is unreachable, Pramaan logs a warning and continues offline. Scores never depend on the model.

## 6. Docker

```bash
docker compose up --build            # from the repo root; seeds scenarios on first start
# open http://127.0.0.1:8000
```

Data persists in the `pramaan-data` volume. To expose beyond localhost, set `PRAMAAN_ALLOWED_HOSTS` (e.g. `myhost:*`) and put the service behind an authenticating reverse proxy.

## 7. Regenerate demo assets (optional)

```bash
pip install playwright && python -m playwright install chromium
python -m pramaan serve &            # in src/
python scripts/capture_demo.py --out ../demo/screenshots --video ../demo/video
python -m pramaan mcp-demo --out ../demo/mcp-session-transcript.md
python scripts/presubmit_check.py    # replica of the Validate Submission workflow
```

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: pramaan` | Run commands from `src/`, or set `PYTHONPATH=src` from the repo root. |
| `No module named mcp.server.mcpserver` | You have the 1.x MCP SDK: `pip install -U "mcp>=2.2,<3"`. |
| Port 8000 busy | `python -m pramaan serve --port 8010` (and use `/mcp` on that port). |
| MCP HTTP returns 421 / host error | Add your host to `PRAMAAN_ALLOWED_HOSTS` (DNS-rebinding protection). |
| Triage rejected with *personal identifiers* | Remove phone/Aadhaar/e-mail/names — describe exhibits only. |
| Empty dashboard | Run `python -m pramaan seed` or create a triage; check `PRAMAAN_HOME`. |
| Want a clean slate | Stop the server and delete `src/runtime/` (this erases the ledger). |
| PDF shows boxes for symbols | Install DejaVu fonts (`apt install fonts-dejavu`); Pramaan otherwise falls back to Helvetica. |
