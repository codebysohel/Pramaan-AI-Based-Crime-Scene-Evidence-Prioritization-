"""Gap analysis — what is MISSING from the exhibit list.

A ranking can only order what was collected. The 2019 Hyderabad case showed the
costlier failure: a DNA-bearing cigarette butt that nearly never entered the
list. This module compares the exhibit list against what the crime profile
expects (knowledge base ``gaps`` rules) and against the scene photographs, and
returns prioritised follow-up actions for the investigating officer.
"""

from __future__ import annotations

import re

from .knowledge import KnowledgeBase
from .models import GapAlert, SceneContext, TriagedItem

# Clinical / autopsy / reference samples are documented by the doctor, not by scene photography.
_NOT_AT_SCENE = {"viscera", "body_fluid_tox", "reference_blood", "sexual_assault_kit", "fingernail_scrapings", "gsr_kit"}
_SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _rule_fires(rule: dict, types: set[str], categories: set[str], scene: SceneContext) -> bool:
    if rule.get("only_if_setting") and scene.setting not in rule["only_if_setting"] and not (
        scene.setting == "mixed" and "outdoor" in rule["only_if_setting"]
    ):
        return False
    need_present = rule.get("only_if_category_present")
    if need_present and not (set(need_present) & categories):
        return False
    missing_types = rule.get("missing_any_type")
    missing_cats = rule.get("missing_any_category")
    if missing_types and set(missing_types) & types:
        return False
    if missing_cats and set(missing_cats) & categories:
        return False
    return bool(missing_types or missing_cats)


def analyse(
    kb: KnowledgeBase,
    crime_type: str,
    items: list[TriagedItem],
    scene: SceneContext,
    photo_captions: list[str] | None = None,
) -> list[GapAlert]:
    types = {i.classification.type_id for i in items}
    categories = {i.classification.category for i in items}
    alerts: list[GapAlert] = []
    seen: set[str] = set()
    for rule in list(kb.profile(crime_type).get("gaps", []) or []) + list(kb.common_gaps):
        if rule["id"] in seen:
            continue
        seen.add(rule["id"])
        if _rule_fires(rule, types, categories, scene):
            alerts.append(GapAlert(id=rule["id"], severity=rule.get("severity", "medium"),
                                   message=rule["message"], action=rule["action"]))

    # Photo coverage: every P1/P2 exhibit should be traceable to an in-situ photograph.
    if photo_captions:
        captions = " \n ".join(photo_captions).lower()
        missing: list[TriagedItem] = []
        for it in items:
            if it.tier not in ("P1", "P2") or it.classification.type_id in _NOT_AT_SCENE:
                continue
            label_hit = re.search(rf"(?<!\w){re.escape(it.label.lower())}(?!\w)", captions)
            type_hit = any(p.search(captions) for _, p in kb.types[it.classification.type_id].patterns)
            if not label_hit and not type_hit:
                missing.append(it)
        if missing:
            labels = ", ".join(it.label for it in missing[:12]) + (f" (+{len(missing) - 12} more)" if len(missing) > 12 else "")
            p1_missing = sum(it.tier == "P1" for it in missing)
            alerts.append(GapAlert(
                id="photo_coverage", severity="high" if p1_missing else "medium",
                message=(f"{len(missing)} priority exhibit(s) ({p1_missing} P1) have no linked in-situ photograph among "
                         f"{len(photo_captions)} captions: {labels}."),
                action=("Link each exhibit to its in-situ photograph (scale + exhibit marker) in the photo log before "
                        "forwarding; courts expect the position to be documented before lifting."),
            ))

    # Batch advice: many similar exhibits -> staged testing saves DNA bench time.
    for it in items:
        if it.quantity >= 4 and "DNA" in it.divisions:
            alerts.append(GapAlert(
                id=f"batch_{it.item_id}", severity="low",
                message=f"{it.label} is a batch of {it.quantity} similar exhibits ({it.classification.type_name}).",
                action="Request staged testing: submit the 2–3 exhibits closest to the body / freshest first; test the rest only if the first round is uninformative.",
            ))

    alerts.sort(key=lambda a: _SEV_ORDER.get(a.severity, 9))
    return alerts
