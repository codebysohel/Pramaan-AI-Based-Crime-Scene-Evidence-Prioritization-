"""Capture dashboard screenshots (and optionally a walkthrough video) of a RUNNING Pramaan server.

    python -m pramaan serve &            # in src/
    python scripts/capture_demo.py --base http://127.0.0.1:8000 --out ../demo/screenshots [--video ../demo/video]

Requires: pip install playwright && python -m playwright install chromium
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default="../demo/screenshots")
    ap.add_argument("--video", default=None, help="directory for a .webm walkthrough")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = json.load(urllib.request.urlopen(f"{a.base}/api/cases"))
    homicide = next(c["case_id"] for c in cases if "784/2026" in c["case_ref"])
    errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx_args = {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1}
        if a.video:
            ctx_args.update(record_video_dir=a.video, record_video_size={"width": 1440, "height": 900})
        ctx = browser.new_context(**ctx_args)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)

        def shot(name: str, full: bool = False, pause: float = 0.6) -> None:
            time.sleep(pause)
            page.screenshot(path=str(out / name), full_page=full)

        # 2. case queue
        page.goto(f"{a.base}/#/case/{homicide}/queue")
        page.wait_for_selector("tr[data-item]")
        shot("01-evidence-queue.png", full=True, pause=1.0)

        # 3. item drawer + what-if simulation
        page.click("tr[data-item] >> text=Ex-A17")
        page.wait_for_selector("#drawer.open")
        page.click("[data-sim='refrigerated']")
        page.wait_for_selector(".sim-out")
        shot("02-exhibit-explanation.png", pause=0.8)
        page.keyboard.press("Escape")

        # 4. lab plan
        page.goto(f"{a.base}/#/case/{homicide}/lab")
        page.wait_for_selector("svg.gantt")
        shot("03-lab-plan-gantt.png", full=True)

        # 5. ledger verified
        page.goto(f"{a.base}/#/case/{homicide}/ledger")
        page.wait_for_selector("#verify")
        page.click("#verify")
        page.wait_for_selector(".banner")
        shot("05-custody-ledger.png")

        # 5b. BSA authenticity tab and FSL network page
        page.goto(f"{a.base}/#/case/{homicide}/authenticity")
        page.wait_for_selector(".ecard")
        shot("13-bsa-authenticity.png", full=True, pause=0.8)
        page.goto(f"{a.base}/#/network")
        page.wait_for_selector(".ubar")
        shot("14-fsl-network.png", full=True, pause=0.6)

        # 6. gaps + packet
        page.goto(f"{a.base}/#/case/{homicide}/gaps")
        shot("07-gap-analysis.png")
        page.goto(f"{a.base}/#/case/{homicide}/packet")
        page.wait_for_function("document.querySelector('#md') && !document.querySelector('#md').textContent.startsWith('Loading')")
        shot("08-fsl-packet.png")

        # 7. benchmark
        page.goto(f"{a.base}/#/benchmark")
        page.wait_for_selector("#bres .big", timeout=30000)
        shot("04-benchmark.png", full=True, pause=0.8)

        # 8. MCP
        page.goto(f"{a.base}/#/mcp")
        page.wait_for_selector("code.snip")
        shot("09-mcp-server.png", full=True)

        # 9. lab-wide queue
        page.goto(f"{a.base}/#/lab")
        page.wait_for_selector("svg.gantt")
        shot("10-lab-wide-queue.png", full=True)

        # 11. output bundle: report.html and graph.html
        page.goto(f"{a.base}/api/cases/{homicide}/report.html")
        shot("11-report-html.png", pause=0.5)
        page.goto(f"{a.base}/api/cases/{homicide}/graph.html")
        page.wait_for_selector("svg#g")
        page.hover("g.n[data-id='x:E-002']")
        shot("12-evidence-graph.png", full=True, pause=0.5)

        # 10. intake (last, so its toast never leaks into other shots) with a scenario loaded
        page.goto(f"{a.base}/#/new")
        page.wait_for_selector("[data-scen]")
        page.click("[data-scen='04_hit_and_run_rain']")
        shot("06-intake-form.png", pause=1.0)

        ctx.close()
        browser.close()
    print("screenshots:", sorted(x.name for x in out.glob("*.png")))
    print("browser errors:", errors or "none")


if __name__ == "__main__":
    main()
