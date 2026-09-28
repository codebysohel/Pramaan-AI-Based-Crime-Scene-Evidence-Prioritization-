"""
PRAMAAN-X Dual Parser Reconciliation

Compares:
    M1 IBM Granite extraction
            VS
    PRAMAAN deterministic extractor.py

The purpose is to detect omissions and disagreements BEFORE
evidence enters forensic prioritisation.

No EPI or forensic priority is calculated here.
"""

from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any

from .classifier import classify
from .extractor import parse_description
from .knowledge import KnowledgeBase, load_kb


# Engineering matching threshold.
# This is NOT a forensic probability.
MATCH_THRESHOLD = 0.50

_WORD = re.compile(
    r"[a-z0-9]+",
    re.I,
)


# ============================================================
# HELPERS
# ============================================================

def _text(
    value: Any,
) -> str | None:

    if value is None:
        return None

    value = str(value).strip()

    return value or None


def _tokens(
    value: str | None,
) -> set[str]:

    return set(
        _WORD.findall(
            (value or "").lower()
        )
    )


def _similarity(
    a: str | None,
    b: str | None,
) -> float:

    a = (a or "").strip().lower()
    b = (b or "").strip().lower()

    if not a or not b:
        return 0.0

    sequence = SequenceMatcher(
        None,
        a,
        b,
    ).ratio()

    ta = _tokens(a)
    tb = _tokens(b)

    if ta and tb:
        jaccard = (
            len(ta & tb)
            / len(ta | tb)
        )
    else:
        jaccard = 0.0

    return (
        0.65 * sequence
        + 0.35 * jaccard
    )


# ============================================================
# CLASSIFICATION
# ============================================================

def _classify_candidate(
    kb: KnowledgeBase,
    description: str,
    location: str | None,
) -> dict[str, Any]:

    result = classify(
        kb,
        description,
        location,
    )

    c = result.classification

    return {
        "type_id": c.type_id,
        "type_name": c.type_name,
        "category": c.category,
        "confidence": c.confidence,
        "method": c.method,
        "matched_keywords": list(
            c.matched_keywords
        ),
    }


# ============================================================
# NORMALISE M1
# ============================================================

def _normalise_m1(
    kb: KnowledgeBase,
    result: dict[str, Any],
) -> list[dict[str, Any]]:

    output = []

    for number, raw in enumerate(
        result.get("items") or [],
        start=1,
    ):

        if not isinstance(
            raw,
            dict,
        ):
            continue

        description = _text(
            raw.get("description")
        )

        if not description:
            continue

        location = _text(
            raw.get("location")
        )

        output.append(
            {
                "id": str(
                    raw.get("item_id")
                    or f"M1-{number:03d}"
                ),

                "description":
                    description,

                "quantity":
                    int(
                        raw.get("quantity")
                        or 1
                    ),

                "location":
                    location,

                "distance_m":
                    raw.get("distance_m"),

                "condition":
                    _text(
                        raw.get("condition")
                    ),

                "packaging":
                    _text(
                        raw.get("packaging")
                    ),

                "source_text":
                    _text(
                        raw.get("source_text")
                    ),

                "source_verified":
                    bool(
                        raw.get(
                            "source_verified",
                            False,
                        )
                    ),

                # M1 itself does NOT classify.
                # We pass its extracted description through
                # PRAMAAN's deterministic classifier.
                "classification":
                    _classify_candidate(
                        kb,
                        description,
                        location,
                    ),
            }
        )

    return output


# ============================================================
# NORMALISE RULE PARSER
# ============================================================

def _normalise_rules(
    kb: KnowledgeBase,
    scene_text: str,
) -> tuple[
    list[dict[str, Any]],
    list[str],
]:

    items, warnings = (
        parse_description(
            kb,
            scene_text,
        )
    )

    output = []

    for number, item in enumerate(
        items,
        start=1,
    ):

        classification = (
            _classify_candidate(
                kb,
                item.description,
                item.location,
            )
        )

        output.append(
            {
                "id":
                    f"RULE-{number:03d}",

                "description":
                    item.description,

                "quantity":
                    item.quantity,

                "location":
                    item.location,

                "condition":
                    item.condition,

                "collected":
                    item.collected,

                "classification":
                    classification,
            }
        )

    return output, warnings


# ============================================================
# MATCHING SCORE
# ============================================================

def _pair_score(
    m1: dict[str, Any],
    rule: dict[str, Any],
) -> float:

    score = _similarity(
        m1["description"],
        rule["description"],
    )

    m1_type = (
        m1["classification"]["type_id"]
    )

    rule_type = (
        rule["classification"]["type_id"]
    )

    # Same deterministic evidence type provides
    # additional matching evidence.
    if (
        m1_type == rule_type
        and m1_type != "other_object"
    ):
        score += 0.30

    # Quantity agreement.
    if (
        m1.get("quantity")
        == rule.get("quantity")
    ):
        score += 0.05

    # M1 source provenance often contains the full
    # deterministic parser segment.
    source = (
        m1.get("source_text")
        or ""
    ).lower()

    rule_description = (
        rule.get("description")
        or ""
    ).lower()

    if (
        source
        and rule_description
        and (
            source in rule_description
            or rule_description in source
        )
    ):
        score += 0.10

    return min(
        score,
        1.0,
    )


# ============================================================
# RECONCILIATION
# ============================================================

def reconcile_scene(
    scene_text: str,
    m1_result: dict[str, Any],
    *,
    kb: KnowledgeBase | None = None,
) -> dict[str, Any]:

    kb = kb or load_kb()

    # --------------------------------------------------------
    # RUN BOTH EXTRACTION PATHS
    # --------------------------------------------------------

    m1_items = _normalise_m1(
        kb,
        m1_result,
    )

    rule_items, parser_warnings = (
        _normalise_rules(
            kb,
            scene_text,
        )
    )

    # --------------------------------------------------------
    # BUILD POSSIBLE MATCHES
    # --------------------------------------------------------

    candidates = []

    for m1_index, m1_item in enumerate(
        m1_items
    ):

        for rule_index, rule_item in enumerate(
            rule_items
        ):

            score = _pair_score(
                m1_item,
                rule_item,
            )

            if score >= MATCH_THRESHOLD:

                candidates.append(
                    (
                        score,
                        m1_index,
                        rule_index,
                    )
                )

    # Best matches first.
    candidates.sort(
        reverse=True
    )

    used_m1 = set()
    used_rules = set()

    matches = []

    type_conflicts = []
    quantity_conflicts = []
    condition_conflicts = []

    # --------------------------------------------------------
    # ONE-TO-ONE GREEDY MATCHING
    # --------------------------------------------------------

    for (
        score,
        m1_index,
        rule_index,
    ) in candidates:

        if (
            m1_index in used_m1
            or rule_index in used_rules
        ):
            continue

        used_m1.add(
            m1_index
        )

        used_rules.add(
            rule_index
        )

        m1_item = (
            m1_items[m1_index]
        )

        rule_item = (
            rule_items[rule_index]
        )

        match_id = (
            f"PAIR-{len(matches) + 1:03d}"
        )

        pair = {
            "match_id":
                match_id,

            "score":
                round(
                    score,
                    3,
                ),

            "m1":
                m1_item,

            "rules":
                rule_item,
        }

        matches.append(
            pair
        )

        # ----------------------------------------------------
        # TYPE CONFLICT
        # ----------------------------------------------------

        m1_type = (
            m1_item[
                "classification"
            ]["type_id"]
        )

        rule_type = (
            rule_item[
                "classification"
            ]["type_id"]
        )

        if m1_type != rule_type:

            type_conflicts.append(
                {
                    "match_id":
                        match_id,

                    "m1_type":
                        m1_type,

                    "rules_type":
                        rule_type,
                }
            )

        # ----------------------------------------------------
        # QUANTITY CONFLICT
        # ----------------------------------------------------

        if (
            m1_item.get("quantity")
            != rule_item.get("quantity")
        ):

            quantity_conflicts.append(
                {
                    "match_id":
                        match_id,

                    "m1_quantity":
                        m1_item.get(
                            "quantity"
                        ),

                    "rules_quantity":
                        rule_item.get(
                            "quantity"
                        ),
                }
            )

        # ----------------------------------------------------
        # CONDITION CONFLICT
        # ----------------------------------------------------

        m1_condition = (
            m1_item.get(
                "condition"
            )
        )

        rule_condition = (
            rule_item.get(
                "condition"
            )
        )

        # Only call it a conflict if BOTH explicitly
        # provided a condition.
        if (
            m1_condition
            and rule_condition
            and m1_condition
            != rule_condition
        ):

            condition_conflicts.append(
                {
                    "match_id":
                        match_id,

                    "m1_condition":
                        m1_condition,

                    "rules_condition":
                        rule_condition,
                }
            )

    # ========================================================
    # MISSING ITEMS
    # ========================================================

    missing_from_rules = [
        m1_items[index]
        for index in range(
            len(m1_items)
        )
        if index not in used_m1
    ]

    unmatched_rules = [
        rule_items[index]
        for index in range(
            len(rule_items)
        )
        if index not in used_rules
    ]

    # --------------------------------------------------------
    # IMPORTANT
    #
    # extractor.py intentionally preserves unknown text.
    #
    # Example:
    #     "Suspected homicide scene"
    #
    # becomes other_object/fallback.
    #
    # We must NOT automatically accuse M1 of missing evidence
    # for such narrative/header text.
    # --------------------------------------------------------

    missing_from_m1 = [
        item
        for item in unmatched_rules
        if (
            item["classification"][
                "method"
            ]
            != "fallback"
        )
    ]

    unclassified_rule_candidates = [
        item
        for item in unmatched_rules
        if (
            item["classification"][
                "method"
            ]
            == "fallback"
        )
    ]

    # ========================================================
    # RESULT
    # ========================================================

    return {

        "module":
            "dual_parser_reconciliation",

        "match_threshold":
            MATCH_THRESHOLD,

        "counts": {

            "m1":
                len(m1_items),

            "rules":
                len(rule_items),

            "matched":
                len(matches),

            "missing_from_m1":
                len(
                    missing_from_m1
                ),

            "missing_from_rules":
                len(
                    missing_from_rules
                ),

            "unclassified_rule_candidates":
                len(
                    unclassified_rule_candidates
                ),
        },

        "matches":
            matches,

        "missing_from_m1":
            missing_from_m1,

        "missing_from_rules":
            missing_from_rules,

        "unclassified_rule_candidates":
            unclassified_rule_candidates,

        "type_conflicts":
            type_conflicts,

        "quantity_conflicts":
            quantity_conflicts,

        "condition_conflicts":
            condition_conflicts,

        "parser_warnings":
            parser_warnings,
    }