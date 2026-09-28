"""Local replica of the hackathon 'Validate Submission' workflow + extra hygiene checks.

    python src/scripts/presubmit_check.py          (from the repo root)
Exit code 0 = ready; warnings list the fields you still have to personalise.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ["submission.yaml", "README.md", "src", "docs/problem-statement.md", "docs/solution-overview.md",
            "docs/architecture.md", "docs/setup-guide.md", "demo/demo-video-link.txt", "demo/screenshots",
            "presentation", "CONTRIBUTING.md", ".gitignore", ".github/workflows/validate.yml"]
errors: list[str] = []
warnings: list[str] = []

for rel in REQUIRED:
    if not (ROOT / rel).exists():
        errors.append(f"missing {rel}")

sub = yaml.safe_load((ROOT / "submission.yaml").read_text(encoding="utf-8"))
team, s = sub.get("team", {}), sub.get("submission", {})
for label, val in [("team.name", team.get("name")), ("team.track", team.get("track")),
                   ("team.lead.name", team.get("lead", {}).get("name")), ("team.lead.email", team.get("lead", {}).get("email")),
                   ("submission.title", s.get("title")), ("submission.problem_statement", s.get("problem_statement")),
                   ("submission.solution_summary", s.get("solution_summary"))]:
    if not val or not str(val).strip():
        errors.append(f"{label} is empty")
    elif "REPLACE_ME" in str(val):
        warnings.append(f"{label} still contains a REPLACE_ME placeholder")
if team.get("track") not in ("AI", "DevOps", "Sustainability", "Open"):
    errors.append("team.track must be AI | DevOps | Sustainability | Open")
if not [k for k in s.get("key_features", []) if str(k).strip()]:
    errors.append("key_features is empty")
if not [p for p in (ROOT / "src").rglob("*") if p.is_file() and p.name != "README.md"]:
    errors.append("src/ has no source files")
video = (ROOT / "demo/demo-video-link.txt").read_text(encoding="utf-8")
if "your-demo-video-link-here" in video:
    errors.append("demo-video-link.txt still has the template placeholder")
if not re.search(r"https?://\S+", video) or "REPLACE_ME" in video:
    warnings.append("demo-video-link.txt has no real video URL yet")
readme = (ROOT / "README.md").read_text(encoding="utf-8")
for ph in ("[Your Project Title Here]", "[Your Team Name]"):
    if ph in readme:
        errors.append(f"README.md still contains {ph}")
shots = [p for p in (ROOT / "demo/screenshots").iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif")]
if len(shots) < 3:
    errors.append("fewer than 3 screenshots")
if not any((ROOT / "presentation").glob("slides.*")):
    errors.append("presentation/slides.pdf or .pptx missing")
for bad in (".env", "src/.env"):
    if (ROOT / bad).exists():
        errors.append(f"{bad} exists — never commit it")
for pat in ("node_modules", ".venv", "venv", "runtime"):
    for p in ROOT.rglob(pat):
        if p.is_dir() and ".git" not in p.parts:
            warnings.append(f"{p.relative_to(ROOT)} exists locally — make sure it is git-ignored")
try:
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    leaked = [t for t in tracked if t.endswith(".env") or "node_modules/" in t or "/runtime/" in t or t.endswith(".sqlite3")]
    if leaked:
        errors.append(f"tracked files that must not be committed: {leaked[:5]}")
except (OSError, subprocess.CalledProcessError):
    pass

for w in warnings:
    print("WARN ", w)
for e in errors:
    print("ERROR", e)
print("OK — structure matches the Validate Submission workflow" if not errors else f"{len(errors)} error(s)")
sys.exit(1 if errors else 0)
