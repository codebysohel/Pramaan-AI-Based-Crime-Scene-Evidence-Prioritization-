# Convenience targets (Linux/macOS). Windows users: run the commands shown in docs/setup-guide.md.
PY ?= python3
.PHONY: install test seed serve mcp benchmark demo check docker
install:   ; cd src && $(PY) -m pip install -r requirements-dev.txt
test:      ; cd src && $(PY) -m pytest
seed:      ; cd src && $(PY) -m pramaan seed
serve:     ; cd src && $(PY) -m pramaan serve
mcp:       ; cd src && $(PY) -m pramaan mcp
benchmark: ; cd src && $(PY) -m pramaan benchmark
demo:      ; cd src && $(PY) -m pramaan mcp-demo --out ../demo/mcp-session-transcript.md
check:     ; $(PY) src/scripts/presubmit_check.py
docker:    ; docker compose up --build
