"""
PRAMAAN-X Decision Confidence

This confidence value is deliberately separate from EPI.

It is an ENGINEERING confidence indicator based on:

- deterministic classification confidence
- parser agreement
- provenance verification
- field completeness

It is NOT:
- probability that evidence is genuine
- probability of guilt
- probability of admissibility
- part of the forensic EPI score
"""

from __future__ import annotations

from typing import Any


def evidence_confidence(
    match: dict[str, Any],
) -> dict[str, Any]:

    m1 = (
        match.get("m1")
        or {}
    )

    rules = (
        match.get("rules")
        or {}
    )

    # ========================================================
    # CLASSIFICATION CONFIDENCE
    # ========================================================

    m1_classification = (
        m1.get("classification")
        or {}
    )

    rule_classification = (
        rules.get("classification")
        or {}
    )

    m1_confidence = float(
        m1_classification.get(
            "confidence",
            0.0,
        )
    )

    rule_confidence = float(
        rule_classification.get(
            "confidence",
            0.0,
        )
    )

    classification = (
        m1_confidence
        + rule_confidence
    ) / 2.0

    classification = max(
        0.0,
        min(
            1.0,
            classification,
        ),
    )

    # ========================================================
    # PARSER AGREEMENT
    # ========================================================

    agreement = float(
        match.get(
            "score",
            0.0,
        )
    )

    agreement = max(
        0.0,
        min(
            1.0,
            agreement,
        ),
    )

    # ========================================================
    # PROVENANCE
    # ========================================================

    if (
        m1.get(
            "source_verified"
        )
        is True
    ):
        provenance = 1.0

    else:
        provenance = 0.45

    # ========================================================
    # COMPLETENESS
    # ========================================================

    fields = (
        "description",
        "quantity",
        "location",
        "condition",
    )

    present = sum(
        m1.get(field)
        not in (
            None,
            "",
            [],
        )
        for field in fields
    )

    # Missing location/condition should not make an otherwise
    # valid exhibit look completely unreliable.
    completeness = (
        0.60
        + 0.40
        * (
            present
            / len(fields)
        )
    )

    # ========================================================
    # COMBINED ENGINEERING CONFIDENCE
    # ========================================================

    value = (

        0.35
        * classification

        + 0.35
        * agreement

        + 0.20
        * provenance

        + 0.10
        * completeness
    )

    value = round(
        max(
            0.0,
            min(
                1.0,
                value,
            ),
        ),
        3,
    )

    # ========================================================
    # LABEL
    # ========================================================

    if value >= 0.80:

        label = "HIGH"

    elif value >= 0.60:

        label = "MEDIUM"

    else:

        label = "LOW"

    return {

        "value":
            value,

        "label":
            label,

        "components": {

            "classification":
                round(
                    classification,
                    3,
                ),

            "parser_agreement":
                round(
                    agreement,
                    3,
                ),

            "provenance":
                round(
                    provenance,
                    3,
                ),

            "completeness":
                round(
                    completeness,
                    3,
                ),
        },

        "note": (
            "Engineering confidence indicator; "
            "not a forensic probability and not part of EPI."
        ),
    }