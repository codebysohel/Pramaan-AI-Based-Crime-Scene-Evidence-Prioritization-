"""
PRAMAAN-X Evidence Digital Twin

Creates one auditable digital record for each reconciled exhibit.

Future modules attach:

M2 -> visual detections
M3 -> semantic cluster
M4 -> contradictions
M5 -> shadow-scan candidates

The deterministic PRAMAAN triage result can also be attached.
"""

from __future__ import annotations

from typing import Any

from .confidence import (
    evidence_confidence,
)


def build_digital_twins(
    reconciliation: dict[str, Any],
    *,
    guardrail: dict[str, Any] | None = None,
    triage_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:

    # ========================================================
    # OPTIONAL TRIAGE LOOKUP
    # ========================================================

    triage_by_description = {}

    if triage_result:

        for item in (
            triage_result.get(
                "items"
            )
            or []
        ):

            description = str(
                item.get(
                    "description"
                )
                or ""
            ).strip().lower()

            if description:

                triage_by_description[
                    description
                ] = item

    guardrail_state = (
        (guardrail or {}).get(
            "state"
        )
    )

    twins = []

    # ========================================================
    # CREATE ONE TWIN PER RECONCILED EXHIBIT
    # ========================================================

    for number, match in enumerate(
        reconciliation.get(
            "matches"
        )
        or [],
        start=1,
    ):

        m1 = (
            match.get("m1")
            or {}
        )

        rules = (
            match.get("rules")
            or {}
        )

        description = str(
            m1.get(
                "description"
            )
            or rules.get(
                "description"
            )
            or ""
        ).strip()

        # ----------------------------------------------------
        # OPTIONAL EXISTING PRAMAAN TRIAGE RESULT
        # ----------------------------------------------------

        triage = (
            triage_by_description.get(
                description.lower()
            )
        )

        # ----------------------------------------------------
        # DIGITAL TWIN
        # ----------------------------------------------------

        twin = {

            "twin_id":
                f"TWIN-{number:03d}",

            "description":
                description,

            "quantity":
                m1.get(
                    "quantity",
                    rules.get(
                        "quantity",
                        1,
                    ),
                ),

            # =================================================
            # SCENE
            # =================================================

            "scene": {

                "location":
                    m1.get(
                        "location"
                    )
                    or rules.get(
                        "location"
                    ),

                "distance_m":
                    m1.get(
                        "distance_m"
                    ),
            },

            # =================================================
            # CONDITION
            # =================================================

            "condition": {

                "state":
                    m1.get(
                        "condition"
                    )
                    or rules.get(
                        "condition"
                    ),

                "packaging":
                    m1.get(
                        "packaging"
                    ),
            },

            # =================================================
            # CLASSIFICATION
            # =================================================

            "classification":
                m1.get(
                    "classification"
                )
                or rules.get(
                    "classification"
                ),

            # =================================================
            # PROVENANCE
            # =================================================

            "provenance": {

                "m1_item_id":
                    m1.get(
                        "id"
                    ),

                "rule_item_id":
                    rules.get(
                        "id"
                    ),

                "source_text":
                    m1.get(
                        "source_text"
                    ),

                "source_verified":
                    m1.get(
                        "source_verified"
                    ),
            },

            # =================================================
            # RECONCILIATION
            # =================================================

            "reconciliation": {

                "match_id":
                    match.get(
                        "match_id"
                    ),

                "match_score":
                    match.get(
                        "score"
                    ),
            },

            # =================================================
            # CONFIDENCE
            # =================================================

            "decision_confidence":
                evidence_confidence(
                    match
                ),

            # =================================================
            # GUARDRAIL
            # =================================================

            "guardrail_state":
                guardrail_state,

            # =================================================
            # AI EXTENSIONS
            #
            # These are deliberately empty now.
            # M2-M5 will populate them.
            # =================================================

            "ai_extensions": {

                "m2_visual_detections":
                    [],

                "m3_cluster":
                    None,

                "m4_contradictions":
                    [],

                "m5_shadow_candidates":
                    [],
            },

            # =================================================
            # EXISTING PRAMAAN TRIAGE
            # =================================================

            "triage":
                None,
        }

        # ----------------------------------------------------
        # ATTACH TRIAGE IF AVAILABLE
        # ----------------------------------------------------

        if triage:

            twin["triage"] = {

                "item_id":
                    triage.get(
                        "item_id"
                    ),

                "rank":
                    triage.get(
                        "rank"
                    ),

                "tier":
                    triage.get(
                        "tier"
                    ),

                "epi":
                    (
                        triage.get(
                            "score"
                        )
                        or {}
                    ).get(
                        "epi"
                    ),

                "flags":
                    triage.get(
                        "flags"
                    )
                    or [],

                "divisions":
                    triage.get(
                        "divisions"
                    )
                    or [],
            }

        twins.append(
            twin
        )

    return twins