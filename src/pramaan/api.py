"""REST API + web dashboard + streamable-HTTP MCP endpoint, in one process.

    /            static dashboard (no CDN, works air-gapped)
    /api/...     JSON API used by the dashboard (and scriptable)
    /mcp         MCP streamable-HTTP endpoint (same tools as the stdio server)

Running both from one process means a triage started by an MCP client appears in the
dashboard immediately and vice versa — they share the SQLite store and ledger.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field, ValidationError

from . import bsa, network, outputs, pipeline, reports
from .ai_pipeline import run_ai_triage
from .ai_orchestrator import get_ai_runtime_status
from . import scheduler as scheduler_mod
from .benchmark import run_benchmark
from .config import ENGINE_VERSION, SCENARIOS_DIR, WEB_DIR, get_settings
from .knowledge import KnowledgeBaseError, load_kb
from .llm.client import get_llm
from .mcp_server import TOOL_CATALOG, mcp
from .models import CaseInput, TriageResult
from .privacy import PrivacyViolation
from .store import Store

ACTOR = "dashboard"


class UpdateRequest(BaseModel):
    changes: dict[str, Any]
    reason: str = Field(..., min_length=5, max_length=300)


class SimulateRequest(BaseModel):
    condition: Literal["ambient", "hot", "wet", "sunlight", "refrigerated", "frozen", "dry_sealed"]


class CustodyRequest(BaseModel):
    event: Literal["sealed", "handed_over", "received", "opened_for_examination", "resealed", "returned", "note"]
    from_party: Optional[str] = None
    to_party: Optional[str] = None
    seal_intact: Optional[bool] = None
    note: Optional[str] = Field(None, max_length=300)


class AIPhoto(BaseModel):
    filename: str = Field(..., min_length=1, max_length=1024)
    data_base64: str = Field(..., min_length=1)


class AITriageRequest(BaseModel):
    case: dict[str, Any]
    run_m5: bool = False
    photos: list[AIPhoto] = Field(default_factory=list, max_length=8)


def _hosts() -> list[str]:
    raw = os.getenv("PRAMAAN_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*,[::1]:*")
    return [h.strip() for h in raw.split(",") if h.strip()]


def _result(store: Store, case_id: str) -> TriageResult:
    case = store.get_case(case_id)
    if not case:
        raise HTTPException(404, f"Unknown case {case_id}")
    return TriageResult(**case["result"])


def create_app() -> FastAPI:
    settings = get_settings()
    hosts = _hosts()
    mcp_http = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=os.getenv("PRAMAAN_MCP_DNS_PROTECTION", "1") != "0",
            allowed_hosts=hosts, allowed_origins=[f"http://{h}" for h in hosts] + [f"https://{h}" for h in hosts],
        ),
    )
    session_manager = mcp.session_manager

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.ensure_dirs()
        async with session_manager.run():
            yield

    app = FastAPI(title="Pramaan API", version=ENGINE_VERSION, lifespan=lifespan,
                  description="Explainable crime-scene evidence triage for Indian forensic science laboratories.")
    for route in mcp_http.routes:  # serve /mcp directly (no sub-mount redirect)
        app.router.routes.append(route)

    @app.exception_handler(PrivacyViolation)
    async def _privacy(_, exc: PrivacyViolation):
        return JSONResponse(status_code=422, content={"detail": str(exc), "kinds": exc.kinds})

    @app.exception_handler(KnowledgeBaseError)
    async def _kb(_, exc: KnowledgeBaseError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # ------------------------------------------------------------- meta
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        kb = load_kb()
        store = Store()
        return {"status": "ok", "engine_version": ENGINE_VERSION, "kb_hash": kb.kb_hash,
                "llm_provider": get_llm().name, "evidence_types": len(kb.types), "crime_profiles": len(kb.profiles),
                "cases": len(store.list_cases()), "ledger_head": store.head(), "mcp_endpoint": "/mcp",
                "ai_endpoint": "/api/ai/triage", "ai_models": get_ai_runtime_status(),
                "bench_hours_per_day": float(kb.lab.get("bench_hours_per_day", 8))}

    @app.get("/api/knowledge/crime-profiles")
    def crime_profiles() -> list[dict[str, Any]]:
        kb = load_kb()
        return [{"id": k, "label": v["label"], "key_questions": v.get("key_questions", []),
                 "weights": v.get("weights") or kb.default_weights} for k, v in kb.profiles.items()]

    @app.get("/api/knowledge/evidence-types")
    def evidence_types(q: Optional[str] = None) -> list[dict[str, Any]]:
        kb = load_kb()
        types = kb.search(q, limit=15) if q else list(kb.types.values())
        return [{"id": t.id, "name": t.name, "category": t.category, "individualizing": t.individualizing,
                 "degradation": t.degradation, "exams": [kb.exams[e]["name"] for e in t.exam_plan],
                 "caveat": t.caveat, "handling": t.handling} for t in types]

    @app.get("/api/mcp/tools")
    def mcp_tools() -> dict[str, Any]:
        return {"endpoint": "/mcp", "transport": "streamable-http", "stdio": "python -m pramaan.mcp_server",
                "tools": TOOL_CATALOG}

    # --------------------------------------------------------------- AI
    @app.get("/api/ai/status")
    def ai_status() -> dict[str, Any]:
        """Live, process-local proof of which M1-M5 models loaded and ran."""
        return {
            "models": get_ai_runtime_status(),
            "wiring": {
                "dashboard": "/api/ai/triage",
                "bob_mcp_tool": "analyze_scene_ai",
                "text_path": ["M1", "rules", "reconciliation", "M3", "M4", "GuardRail", "deterministic engine"],
                "image_path": ["M2", "optional M5", "investigator review"],
            },
        }

    @app.post("/api/ai/triage")
    def ai_triage(req: AITriageRequest) -> dict[str, Any]:
        """Dashboard entry point for the same PRAMAAN-X path Bob uses.

        M1/M3/M4 run for text. If photos are attached, M2 runs; M5 runs only
        when explicitly enabled because it is much heavier on CPU/RAM. Images
        arrive as base64 JSON so the application has no multipart dependency.
        """
        try:
            case = CaseInput.model_validate(req.case)
        except ValidationError as exc:
            raise HTTPException(400, str(exc)) from exc

        upload_root = get_settings().home / "uploads" / uuid.uuid4().hex
        image_paths: list[Path] = []
        allowed = {".jpg", ".jpeg", ".png"}
        try:
            for photo in req.photos:
                suffix = Path(photo.filename).suffix.lower()
                if suffix not in allowed:
                    raise HTTPException(400, f"Unsupported image type: {suffix or 'unknown'}. Use JPG/PNG.")
                try:
                    data = base64.b64decode(photo.data_base64, validate=True)
                except Exception as exc:
                    raise HTTPException(400, f"Invalid base64 image: {photo.filename}") from exc
                if len(data) > 15 * 1024 * 1024:
                    raise HTTPException(400, "Each image must be 15 MB or smaller.")
                upload_root.mkdir(parents=True, exist_ok=True)
                target = upload_root / f"{uuid.uuid4().hex}{suffix}"
                target.write_bytes(data)
                image_paths.append(target)

            envelope = run_ai_triage(
                case,
                image_paths=image_paths,
                store=Store(),
                actor=ACTOR,
                persist=True,
                run_m2=True,
                run_m3=True,
                run_m4=True,
                run_m5=req.run_m5,
                save_annotated=True,
            )
            return envelope
        except PrivacyViolation:
            raise
        except HTTPException:
            raise
        except (ValueError, ValidationError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, f"AI triage failed: {type(exc).__name__}: {exc}") from exc

    # -------------------------------------------------------- scenarios
    @app.get("/api/scenarios")
    def scenarios() -> list[dict[str, Any]]:
        out = []
        for f in sorted(SCENARIOS_DIR.glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append({"name": f.stem, "title": d.get("title"), "crime_type": d.get("crime_type"), "case_ref": d.get("case_ref")})
        return out

    @app.get("/api/scenarios/{name}")
    def scenario(name: str) -> dict[str, Any]:
        f = SCENARIOS_DIR / f"{name}.json"
        if not f.is_file() or f.parent != SCENARIOS_DIR:
            raise HTTPException(404, "Unknown scenario")
        return json.loads(f.read_text(encoding="utf-8"))

    # ------------------------------------------------------------ triage
    @app.post("/api/triage")
    def triage(case: CaseInput) -> dict[str, Any]:
        try:
            result = pipeline.run_triage(case, llm=get_llm(), store=Store(), actor=ACTOR)
        except PrivacyViolation:
            raise
        except (ValueError, ValidationError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return result.model_dump(mode="json")

    @app.get("/api/cases")
    def cases() -> list[dict[str, Any]]:
        return Store().list_cases()

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str) -> dict[str, Any]:
        store = Store()
        res = _result(store, case_id)
        return {"result": res.model_dump(mode="json"), "ledger": store.ledger(case_id, limit=200),
                "verify": store.verify_case(case_id), "ai_control": store.get_ai(case_id)}

    @app.post("/api/cases/{case_id}/items/{item}/update")
    def update(case_id: str, item: str, req: UpdateRequest) -> dict[str, Any]:
        store = Store()
        try:
            res = pipeline.update_item(store, case_id, item, req.changes, actor=ACTOR)
        except pipeline.CaseNotFound as exc:
            raise HTTPException(404, f"Unknown case {case_id}") from exc
        except PrivacyViolation:
            raise
        except (ValueError, KeyError, ValidationError) as exc:
            raise HTTPException(400, str(exc).strip('"')) from exc
        store.append(ACTOR, "update_reason", {"reason": req.reason, "changes": req.changes}, case_id=case_id, item_id=item)
        return res.model_dump(mode="json")

    @app.post("/api/cases/{case_id}/items/{item}/simulate")
    def simulate(case_id: str, item: str, req: SimulateRequest) -> dict[str, Any]:
        try:
            return pipeline.simulate_preservation(Store(), case_id, item, req.condition)
        except pipeline.CaseNotFound as exc:
            raise HTTPException(404, f"Unknown case {case_id}") from exc
        except KeyError as exc:
            raise HTTPException(400, str(exc).strip('"')) from exc

    @app.post("/api/cases/{case_id}/items/{item}/custody")
    def custody(case_id: str, item: str, req: CustodyRequest) -> dict[str, Any]:
        store = Store()
        res = _result(store, case_id)
        it = next((i for i in res.items if item in (i.item_id, i.label)), None)
        if not it:
            raise HTTPException(404, f"No exhibit {item}")
        return store.append(ACTOR, f"custody:{req.event}", {"label": it.label, "from": req.from_party, "to": req.to_party,
                                                             "seal_intact": req.seal_intact, "note": req.note or ""},
                            case_id=case_id, item_id=it.item_id)

    @app.get("/api/cases/{case_id}/packet.md", response_class=PlainTextResponse)
    def packet_md(case_id: str) -> str:
        store = Store()
        return reports.packet_markdown(_result(store, case_id), store.head())

    @app.get("/api/cases/{case_id}/packet.pdf")
    def packet_pdf(case_id: str) -> Response:
        store = Store()
        res = _result(store, case_id)
        pdf = reports.packet_pdf(res, store.head())
        store.append(ACTOR, "packet_generated", {"result_sha256": res.result_sha256}, case_id=case_id)
        name = f"FSL_packet_{reports.safe_filename(case_id)}.pdf"
        return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})

    @app.get("/api/cases/{case_id}/report.html", response_class=HTMLResponse)
    def report_html(case_id: str) -> str:
        store = Store()
        return outputs.report_html(_result(store, case_id), store.head(), store.verify_case(case_id))

    @app.get("/api/cases/{case_id}/graph.html", response_class=HTMLResponse)
    def graph_html(case_id: str) -> str:
        return outputs.graph_html(_result(Store(), case_id))

    @app.get("/api/cases/{case_id}/state.json")
    def state_json(case_id: str) -> dict[str, Any]:
        store = Store()
        _result(store, case_id)
        return outputs.state_dict(store, case_id)

    @app.get("/api/cases/{case_id}/audit.jsonl", response_class=PlainTextResponse)
    def audit_jsonl(case_id: str) -> str:
        store = Store()
        _result(store, case_id)
        return outputs.audit_lines(store, case_id)

    @app.get("/api/cases/{case_id}/authenticity")
    def authenticity(case_id: str) -> dict[str, Any]:
        store = Store()
        _result(store, case_id)
        return outputs.authenticity(store, case_id)

    @app.get("/api/cases/{case_id}/authenticity.pdf")
    def authenticity_pdf(case_id: str) -> Response:
        store = Store()
        res = _result(store, case_id)
        pdf = bsa.authenticity_report_pdf(outputs.authenticity(store, case_id), res)
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="authenticity_{reports.safe_filename(case_id)}.pdf"'})

    @app.get("/api/cases/{case_id}/items/{item}/bsa63-certificate.pdf")
    def certificate(case_id: str, item: str) -> Response:
        store = Store()
        case = store.get_case(case_id)
        if not case:
            raise HTTPException(404, f"Unknown case {case_id}")
        res = TriageResult(**case["result"])
        it = next((i for i in res.items if item in (i.item_id, i.label)), None)
        if not it or not bsa.is_electronic(it):
            raise HTTPException(400, "Not an electronic exhibit")
        pdf = bsa.certificate_pdf(res, it, outputs.electronic_input(case, it.item_id))
        store.append(ACTOR, "bsa63_certificate_drafted", {"label": it.label}, case_id=case_id, item_id=it.item_id)
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="bsa63_{reports.safe_filename(it.label)}.pdf"'})

    @app.get("/api/legal/bsa-analysis.pdf")
    def legal_pdf() -> Response:
        return Response(bsa.legal_analysis_pdf(), media_type="application/pdf")

    @app.get("/api/legal/bsa")
    def legal_map() -> dict[str, Any]:
        return {"law": bsa.LAW, "disclaimer": bsa.DISCLAIMER}

    @app.get("/api/network-plan")
    def network_plan(add_division: Optional[str] = None, add_examiners: int = Query(0, ge=0, le=50)) -> dict[str, Any]:
        kb = load_kb()
        store = Store()
        cases = []
        for row in reversed(store.list_cases()):
            res = _result(store, row["case_id"])
            left = None if not res.custody_deadline else (res.custody_deadline - res.reference_time).total_seconds() / 3600
            cases.append((res.case_id, res.items, left))
        extra = {add_division.upper(): add_examiners} if add_division and add_examiners else None
        out = network.compare(kb, cases, extra)
        out["units_config"] = kb.network
        return out

    @app.get("/api/scale-benchmark")
    def scale(cases: int = Query(10, ge=1, le=60), items: int = Query(200, ge=20, le=400)) -> dict[str, Any]:
        out = network.scale_benchmark(cases, items)
        for k in ("hq_only", "network"):
            out[k].pop("assignments", None)
        return out

    @app.post("/api/cases/{case_id}/export")
    def export(case_id: str) -> dict[str, Any]:
        store = Store()
        _result(store, case_id)
        files = outputs.export_case(store, case_id)
        store.append(ACTOR, "outputs_exported", {"files": sorted(files)}, case_id=case_id)
        return {"case_id": case_id, "files": files}

    # ------------------------------------------------------ ledger & lab
    @app.get("/api/ledger")
    def ledger(case_id: Optional[str] = None, limit: int = Query(200, ge=1, le=2000)) -> list[dict[str, Any]]:
        return Store().ledger(case_id, limit)

    @app.get("/api/ledger/verify")
    def ledger_verify() -> dict[str, Any]:
        return Store().verify()

    @app.get("/api/lab-queue")
    def lab_queue() -> dict[str, Any]:
        kb = load_kb()
        store = Store()
        cases = []
        for row in reversed(store.list_cases()):
            res = _result(store, row["case_id"])
            left = None if not res.custody_deadline else (res.custody_deadline - res.reference_time).total_seconds() / 3600
            cases.append((res.case_id, res.items, left))
        return scheduler_mod.plan_lab(kb, cases).model_dump(mode="json")

    @app.get("/api/benchmark")
    def benchmark(n: int = Query(200, ge=20, le=600), seed: int = 2019) -> dict[str, Any]:
        return run_benchmark(n, seed).as_dict()

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
