"""PRAMAAN-X AI orchestration layer.

Coordinates M1-M5 while keeping forensic decisions auditable:
M1 extracts text facts, deterministic parser independently parses the same notes,
reconciliation + GuardRail decide whether the case is ready, M3 groups related
exhibits, M4 flags possible textual contradictions, and M2/M5 add visual
candidates. Visual AI never auto-creates or confirms evidence.
"""
from __future__ import annotations

import gc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .digital_twin import build_digital_twins
from .guardrail import evaluate_guardrail
from .knowledge import KnowledgeBase, load_kb
from .reconciliation import reconcile_scene


MODEL_META = {
    "m1": {"name": "IBM Granite 3.3 2B", "model": "ibm-granite/granite-3.3-2b-instruct", "role": "scene text extraction"},
    "m2": {"name": "YOLO-World", "model": "yolov8s-worldv2.pt", "role": "visual evidence candidates"},
    "m3": {"name": "MiniLM", "model": "sentence-transformers/all-MiniLM-L6-v2", "role": "semantic similarity / clustering"},
    "m4": {"name": "DeBERTa NLI", "model": "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli", "role": "contradiction checks"},
    "m5": {"name": "IBM Granite Vision", "model": "ibm-granite/granite-vision-3.3-2b", "role": "visual shadow scan"},
}

_MODEL_RUNTIME = {
    key: {**meta, "status": "NOT_LOADED", "loaded": False, "last_inference_at": None, "error": None}
    for key, meta in MODEL_META.items()
}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _mark_model(module: str, *, status: str, loaded: bool | None = None, error: str | None = None, inference: bool = False) -> None:
    row = _MODEL_RUNTIME[module]
    row["status"] = status
    if loaded is not None:
        row["loaded"] = loaded
    row["error"] = error
    if inference:
        row["last_inference_at"] = _now_iso()

def get_ai_runtime_status() -> dict[str, Any]:
    """Process-local status used by the dashboard to prove which models loaded/ran."""
    return {k: dict(v) for k, v in _MODEL_RUNTIME.items()}


class PRAMAANAIOrchestrator:
    """Lazy-loading controller for PRAMAAN AI modules M1-M5."""

    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        self.kb = kb or load_kb()
        self._m1 = None
        self._m2 = None
        self._m3 = None
        self._m4 = None
        self._m5 = None

    # ------------------------------------------------------------------
    # Lazy model loading. M1 and M5 are intentionally not kept together
    # because both are large Granite models and the hackathon machine is
    # CPU/RAM constrained.
    # ------------------------------------------------------------------
    def _load_model(self, module: str, attr: str, factory):
        obj = getattr(self, attr)
        if obj is not None:
            return obj
        _mark_model(module, status="LOADING", loaded=False, error=None)
        try:
            obj = factory()
            setattr(self, attr, obj)
            _mark_model(module, status="LOADED", loaded=True, error=None)
            return obj
        except Exception as exc:
            _mark_model(module, status="ERROR", loaded=False, error=f"{type(exc).__name__}: {exc}")
            raise

    def _get_m1(self):
        if self._m1 is None:
            self.release("m5")
        def factory():
            from .ai.scene_extractor import GraniteSceneExtractor
            return GraniteSceneExtractor()
        return self._load_model("m1", "_m1", factory)

    def _get_m2(self):
        def factory():
            from .ai.yolo_detector import ForensicYOLOWorldDetector
            return ForensicYOLOWorldDetector()
        return self._load_model("m2", "_m2", factory)

    def _get_m3(self):
        def factory():
            from .ai.embeddings import EvidenceEmbeddingModel
            return EvidenceEmbeddingModel()
        return self._load_model("m3", "_m3", factory)

    def _get_m4(self):
        def factory():
            from .ai.contradiction import EvidenceContradictionDetector
            return EvidenceContradictionDetector()
        return self._load_model("m4", "_m4", factory)

    def _get_m5(self):
        if self._m5 is None:
            self.release("m1")
        def factory():
            from .ai.vision import GraniteEvidenceShadowScanner
            return GraniteEvidenceShadowScanner()
        return self._load_model("m5", "_m5", factory)

    def release(self, module: str = "all") -> None:
        """Release one model (m1..m5) or all loaded models from memory."""
        names = ("m1", "m2", "m3", "m4", "m5") if module == "all" else (module.lower(),)
        for name in names:
            attr = f"_{name}"
            if hasattr(self, attr):
                if getattr(self, attr) is not None:
                    setattr(self, attr, None)
                    previous = _MODEL_RUNTIME[name]
                    _mark_model(
                        name,
                        status="INFERENCE_OK" if previous.get("last_inference_at") else "RELEASED",
                        loaded=False,
                        error=None,
                    )
        gc.collect()

    # ------------------------------------------------------------------
    # Core text/control layer
    # ------------------------------------------------------------------
    def analyze_text(
        self,
        scene_text: str,
        *,
        m1_result: dict[str, Any] | None = None,
        run_m3: bool = True,
        run_m4: bool = True,
    ) -> dict[str, Any]:
        if not scene_text or not scene_text.strip():
            raise ValueError("scene_text cannot be empty")

        # Allow a precomputed M1 result for fast testing and reproducibility.
        if m1_result is None:
            m1_result = self._get_m1().extract(scene_text)
            _mark_model("m1", status="INFERENCE_OK", loaded=True, error=None, inference=True)
        else:
            _mark_model("m1", status="PRECOMPUTED_INPUT", loaded=self._m1 is not None, error=None, inference=False)

        reconciliation = reconcile_scene(
            scene_text,
            m1_result,
            kb=self.kb,
        )

        guardrail_obj = evaluate_guardrail(reconciliation, m1_result)
        guardrail = guardrail_obj.to_dict()
        twins = build_digital_twins(
            reconciliation,
            guardrail=guardrail,
        )

        m3_result: dict[str, Any] = {
            "status": "NOT_RUN",
            "clusters": [],
            "similar_pairs": [],
        }
        if run_m3 and twins:
            m3_result = self._run_m3(twins)

        m4_result: dict[str, Any] = {
            "status": "NOT_RUN",
            "checks": [],
            "contradictions": [],
        }
        if run_m4 and reconciliation.get("matches"):
            m4_result = self._run_m4(reconciliation, twins)

        return {
            "scene_text": scene_text,
            "m1": m1_result,
            "reconciliation": reconciliation,
            "guardrail": guardrail,
            "digital_twins": twins,
            "m3": m3_result,
            "m4": m4_result,
            "model_runtime": get_ai_runtime_status(),
        }

    def _run_m3(self, twins: list[dict[str, Any]]) -> dict[str, Any]:
        descriptions = [str(t.get("description") or "").strip() for t in twins]
        descriptions = [d for d in descriptions if d]
        if not descriptions:
            return {"status": "NO_ITEMS", "clusters": [], "similar_pairs": []}

        threshold = 0.65
        try:
            model = self._get_m3()
            clusters = model.cluster(descriptions, threshold=threshold)
            similar_pairs = model.find_similar(descriptions, threshold=threshold)
            _mark_model("m3", status="INFERENCE_OK", loaded=True, error=None, inference=True)
        except Exception as exc:
            _mark_model("m3", status="ERROR", loaded=False, error=f"{type(exc).__name__}: {exc}")
            return {"status": "ERROR", "model": MODEL_META["m3"]["model"], "error": str(exc), "clusters": [], "similar_pairs": []}

        # Attach cluster metadata to each digital twin.
        for cluster in clusters:
            items = set(cluster.get("items") or [])
            for twin in twins:
                if twin.get("description") in items:
                    twin["ai_extensions"]["m3_cluster"] = {
                        "cluster_id": cluster.get("cluster_id"),
                        "cluster_size": cluster.get("count", len(items)),
                        "similarity_threshold": threshold,
                    }

        return {
            "status": "COMPLETED",
            "model": "sentence-transformers/all-MiniLM-L6-v2",
            "similarity_threshold": threshold,
            "clusters": clusters,
            "similar_pairs": similar_pairs,
        }

    def _run_m4(
        self,
        reconciliation: dict[str, Any],
        twins: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            detector = self._get_m4()
        except Exception as exc:
            _mark_model("m4", status="ERROR", loaded=False, error=f"{type(exc).__name__}: {exc}")
            return {"status": "ERROR", "model": MODEL_META["m4"]["model"], "error": str(exc), "checks": [], "contradictions": []}
        checks: list[dict[str, Any]] = []
        contradictions: list[dict[str, Any]] = []
        twin_by_match = {
            (t.get("reconciliation") or {}).get("match_id"): t
            for t in twins
        }

        for match in reconciliation.get("matches") or []:
            m1 = match.get("m1") or {}
            rules = match.get("rules") or {}
            statement_a = str(m1.get("source_text") or m1.get("description") or "").strip()
            statement_b = str(rules.get("description") or "").strip()
            if not statement_a or not statement_b:
                continue

            result = detector.check(statement_a, statement_b)
            result["match_id"] = match.get("match_id")
            checks.append(result)

            # NLI is a review signal only. Use a conservative threshold before
            # surfacing a contradiction to the twin.
            if result.get("label") == "contradiction" and float(result.get("confidence", 0)) >= 0.70:
                flagged = {
                    "match_id": match.get("match_id"),
                    "confidence": result.get("confidence"),
                    "statement_a": statement_a,
                    "statement_b": statement_b,
                    "status": "POSSIBLE_CONTRADICTION",
                    "requires_investigator_review": True,
                }
                contradictions.append(flagged)
                twin = twin_by_match.get(match.get("match_id"))
                if twin is not None:
                    twin["ai_extensions"]["m4_contradictions"].append(flagged)

        _mark_model("m4", status="INFERENCE_OK", loaded=True, error=None, inference=True)
        return {
            "status": "COMPLETED",
            "model": "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli",
            "checks": checks,
            "contradictions": contradictions,
            "note": "M4 flags possible textual conflicts; it never changes evidence records automatically.",
        }

    # ------------------------------------------------------------------
    # Visual layer
    # ------------------------------------------------------------------
    def analyze_images(
        self,
        image_paths: Iterable[str | Path],
        *,
        twins: list[dict[str, Any]],
        run_m2: bool = True,
        run_m5: bool = False,
        save_annotated: bool = True,
    ) -> dict[str, Any]:
        paths = [Path(p) for p in image_paths]
        if not paths:
            return {"m2": [], "m5": [], "unlinked_visual_candidates": []}

        manifest = [str(t.get("description") or "").strip() for t in twins]
        manifest = [m for m in manifest if m]

        m2_outputs: list[dict[str, Any]] = []
        m5_outputs: list[dict[str, Any]] = []
        unlinked: list[dict[str, Any]] = []

        if run_m2:
            try:
                detector = self._get_m2()
                for path in paths:
                    result = detector.detect(path, save_annotated=save_annotated)
                    m2_outputs.append(result)
                    for detection in result.get("detections") or []:
                        if not self._attach_m2_candidate(detection, twins):
                            unlinked.append({"module": "M2", "image": path.name, "candidate": detection})
                _mark_model("m2", status="INFERENCE_OK", loaded=True, error=None, inference=True)
            except Exception as exc:
                _mark_model("m2", status="ERROR", loaded=False, error=f"{type(exc).__name__}: {exc}")
                m2_outputs.append({"status": "ERROR", "model": MODEL_META["m2"]["model"], "error": str(exc), "detections": [], "detection_count": 0})

        if run_m5:
            # Free every model we no longer need before loading Granite Vision.
            # M5 is the heaviest branch on CPU/RAM constrained demo machines.
            # release() deliberately preserves last_inference_at, so M1-M4 still
            # show INFERENCE_OK even though their weights have been reclaimed.
            self.release("m1")
            self.release("m2")
            self.release("m3")
            self.release("m4")
            try:
                scanner = self._get_m5()
                for path in paths:
                    result = scanner.scan(path, manifest=manifest)
                    m5_outputs.append(result)
                    for candidate in result.get("candidates") or []:
                        if not self._attach_m5_candidate(candidate, twins):
                            unlinked.append({"module": "M5", "image": path.name, "candidate": candidate})
                _mark_model("m5", status="INFERENCE_OK", loaded=True, error=None, inference=True)
                # Keep the inference proof but return the large vision model's
                # memory immediately to the OS/allocator after this request.
                self.release("m5")
            except Exception as exc:
                _mark_model("m5", status="ERROR", loaded=False, error=f"{type(exc).__name__}: {exc}")
                m5_outputs.append({"status": "ERROR", "model": MODEL_META["m5"]["model"], "error": str(exc), "candidates": []})

        return {
            "m2": m2_outputs,
            "m5": m5_outputs,
            "unlinked_visual_candidates": unlinked,
            "model_runtime": get_ai_runtime_status(),
        }

    @staticmethod
    def _twin_type(twin: dict[str, Any]) -> str | None:
        classification = twin.get("classification") or {}
        return classification.get("type_id")

    def _attach_m2_candidate(
        self,
        detection: dict[str, Any],
        twins: list[dict[str, Any]],
    ) -> bool:
        candidate_type = detection.get("pramaan_type_candidate")
        if not candidate_type or candidate_type == "other_object":
            return False
        matches = [t for t in twins if self._twin_type(t) == candidate_type]
        # Only auto-link when the type identifies exactly one existing exhibit.
        # Multiple same-type exhibits require human association.
        if len(matches) != 1:
            return False
        matches[0]["ai_extensions"]["m2_visual_detections"].append(detection)
        return True

    def _attach_m5_candidate(
        self,
        candidate: dict[str, Any],
        twins: list[dict[str, Any]],
    ) -> bool:
        candidate_type = candidate.get("suggested_type")
        if not candidate_type or candidate_type == "other_object":
            return False
        matches = [t for t in twins if self._twin_type(t) == candidate_type]
        if len(matches) != 1:
            return False
        matches[0]["ai_extensions"]["m5_shadow_candidates"].append(candidate)
        return True

    # ------------------------------------------------------------------
    # Full orchestration entry point
    # ------------------------------------------------------------------
    def analyze_scene(
        self,
        scene_text: str,
        *,
        image_paths: Iterable[str | Path] | None = None,
        m1_result: dict[str, Any] | None = None,
        run_m2: bool = True,
        run_m3: bool = True,
        run_m4: bool = True,
        run_m5: bool = False,
        save_annotated: bool = True,
    ) -> dict[str, Any]:
        result = self.analyze_text(
            scene_text,
            m1_result=m1_result,
            run_m3=run_m3,
            run_m4=run_m4,
        )

        visual = {"m2": [], "m5": [], "unlinked_visual_candidates": []}
        if image_paths:
            visual = self.analyze_images(
                image_paths,
                twins=result["digital_twins"],
                run_m2=run_m2,
                run_m5=run_m5,
                save_annotated=save_annotated,
            )

        result["visual"] = visual
        result["summary"] = {
            "guardrail_state": result["guardrail"]["state"],
            "reconciled_exhibits": len(result["digital_twins"]),
            "m2_detections": sum(x.get("detection_count", 0) for x in visual["m2"]),
            "m4_contradictions": len(result["m4"].get("contradictions") or []),
            "m5_shadow_candidates": sum(len(x.get("candidates") or []) for x in visual["m5"]),
            "unlinked_visual_candidates": len(visual["unlinked_visual_candidates"]),
        }
        return result
