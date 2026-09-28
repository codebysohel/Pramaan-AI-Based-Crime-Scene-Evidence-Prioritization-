"""
PRAMAAN GuardRail

Prevents evidence triage/final submission when the AI extraction
and deterministic extraction paths materially disagree.

States:

READY
NEEDS_REVIEW
BLOCKED
"""

from __future__ import annotations

from dataclasses import (
    asdict,
    dataclass,
)

from typing import (
    Any,
    Literal,
)


GuardState = Literal[
    "READY",
    "NEEDS_REVIEW",
    "BLOCKED",
]

Severity = Literal[
    "critical",
    "high",
    "medium",
    "low",
    "info",
]


# ============================================================
# ISSUE
# ============================================================

@dataclass
class GuardIssue:

    code: str

    severity: Severity

    message: str

    item_id: str | None = None


# ============================================================
# RESULT
# ============================================================

@dataclass
class GuardRailResult:

    state: GuardState

    triage_allowed: bool

    submission_allowed: bool

    human_confirmation_required: bool

    issues: list[GuardIssue]

    summary: str

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return asdict(
            self
        )


# ============================================================
# GUARDRAIL
# ============================================================

def evaluate_guardrail(
    reconciliation: dict[str, Any] | None,
    m1_result: dict[str, Any] | None = None,
) -> GuardRailResult:

    issues = []

    # --------------------------------------------------------
    # RECONCILIATION REQUIRED
    # --------------------------------------------------------

    if not reconciliation:

        issues.append(
            GuardIssue(
                code=
                    "NO_RECONCILIATION",

                severity=
                    "critical",

                message=
                    "Dual-parser reconciliation has not been completed.",
            )
        )

    else:

        counts = (
            reconciliation.get(
                "counts"
            )
            or {}
        )

        # ----------------------------------------------------
        # NO EVIDENCE
        # ----------------------------------------------------

        if (
            int(
                counts.get(
                    "m1",
                    0,
                )
            )
            == 0
            and
            int(
                counts.get(
                    "rules",
                    0,
                )
            )
            == 0
        ):

            issues.append(
                GuardIssue(
                    code=
                        "NO_EVIDENCE",

                    severity=
                        "critical",

                    message=
                        "Neither extraction path produced an evidence candidate.",
                )
            )

        # ----------------------------------------------------
        # M1 POSSIBLE OMISSION
        # ----------------------------------------------------

        for item in (
            reconciliation.get(
                "missing_from_m1"
            )
            or []
        ):

            issues.append(
                GuardIssue(
                    code=
                        "M1_POSSIBLE_OMISSION",

                    severity=
                        "high",

                    message=(
                        "Deterministic parser found an exhibit "
                        "not matched by M1: "
                        f"{item.get('description')}"
                    ),

                    item_id=
                        item.get("id"),
                )
            )

        # ----------------------------------------------------
        # RULE PARSER POSSIBLE OMISSION
        # ----------------------------------------------------

        for item in (
            reconciliation.get(
                "missing_from_rules"
            )
            or []
        ):

            issues.append(
                GuardIssue(
                    code=
                        "RULE_PARSER_POSSIBLE_OMISSION",

                    severity=
                        "high",

                    message=(
                        "M1 found an exhibit not matched by "
                        "the deterministic parser: "
                        f"{item.get('description')}"
                    ),

                    item_id=
                        item.get("id"),
                )
            )

        # ----------------------------------------------------
        # TYPE CONFLICT
        # ----------------------------------------------------

        for conflict in (
            reconciliation.get(
                "type_conflicts"
            )
            or []
        ):

            issues.append(
                GuardIssue(
                    code=
                        "TYPE_CONFLICT",

                    severity=
                        "high",

                    message=(
                        "Parser-derived classifications disagree "
                        f"for {conflict.get('match_id')}: "
                        f"{conflict.get('m1_type')} vs "
                        f"{conflict.get('rules_type')}."
                    ),
                )
            )

        # ----------------------------------------------------
        # QUANTITY CONFLICT
        # ----------------------------------------------------

        for conflict in (
            reconciliation.get(
                "quantity_conflicts"
            )
            or []
        ):

            issues.append(
                GuardIssue(
                    code=
                        "QUANTITY_CONFLICT",

                    severity=
                        "high",

                    message=(
                        "Quantity disagreement for "
                        f"{conflict.get('match_id')}: "
                        f"{conflict.get('m1_quantity')} vs "
                        f"{conflict.get('rules_quantity')}."
                    ),
                )
            )

        # ----------------------------------------------------
        # CONDITION CONFLICT
        # ----------------------------------------------------

        for conflict in (
            reconciliation.get(
                "condition_conflicts"
            )
            or []
        ):

            issues.append(
                GuardIssue(
                    code=
                        "CONDITION_CONFLICT",

                    severity=
                        "high",

                    message=(
                        "Condition disagreement for "
                        f"{conflict.get('match_id')}: "
                        f"{conflict.get('m1_condition')} vs "
                        f"{conflict.get('rules_condition')}."
                    ),
                )
            )

        # ----------------------------------------------------
        # UNKNOWN RULE TEXT
        # ----------------------------------------------------
        #
        # LOW severity deliberately.
        #
        # Example:
        # "Suspected homicide scene"
        #
        # extractor.py may retain this as fallback text.
        # It should remain visible but should NOT block the
        # entire case automatically.
        # ----------------------------------------------------

        for item in (
            reconciliation.get(
                "unclassified_rule_candidates"
            )
            or []
        ):

            issues.append(
                GuardIssue(
                    code=
                        "UNCLASSIFIED_RULE_TEXT",

                    severity=
                        "low",

                    message=(
                        "Deterministic parser saw "
                        "unclassified text: "
                        f"{item.get('description')}"
                    ),

                    item_id=
                        item.get("id"),
                )
            )

    # ========================================================
    # M1 PROVENANCE CHECK
    # ========================================================

    if m1_result:

        for item in (
            m1_result.get(
                "items"
            )
            or []
        ):

            if (
                item.get(
                    "source_verified"
                )
                is False
            ):

                issues.append(
                    GuardIssue(
                        code=
                            "UNVERIFIED_M1_SOURCE",

                        severity=
                            "high",

                        message=(
                            "M1 source phrase was not verified "
                            "against the investigator notes: "
                            f"{item.get('description')}"
                        ),

                        item_id=
                            item.get(
                                "item_id"
                            ),
                    )
                )

    # ========================================================
    # STATE
    # ========================================================

    severities = {
        issue.severity
        for issue in issues
    }

    if "critical" in severities:

        state: GuardState = (
            "BLOCKED"
        )

    elif (
        "high" in severities
        or "medium" in severities
    ):

        state = (
            "NEEDS_REVIEW"
        )

    else:

        state = (
            "READY"
        )

    # READY can be submitted automatically. NEEDS_REVIEW is still allowed to
    # produce a *provisional* deterministic triage so investigators can see EPI,
    # preservation actions, sequencing and the FSL plan while reviewing the
    # disagreement. Only a critical BLOCKED state prevents triage entirely.
    # Final submission remains restricted to READY below.
    allowed = (
        state != "BLOCKED"
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    blocking_count = sum(
        issue.severity
        in (
            "critical",
            "high",
            "medium",
        )
        for issue in issues
    )

    if state == "READY":

        summary = (
            "GuardRail passed: both extraction paths "
            "are sufficiently reconciled."
        )

    else:

        summary = (
            f"GuardRail {state}: "
            f"{blocking_count} "
            "review-blocking issue(s)."
        )

    return GuardRailResult(

        state=
            state,

        triage_allowed=
            allowed,

        submission_allowed=
            state == "READY",

        human_confirmation_required=
            not allowed,

        issues=
            issues,

        summary=
            summary,
    )