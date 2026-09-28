"""The three narrowly-scoped jobs the LLM is allowed to do. All outputs are validated."""

from __future__ import annotations

import logging

from ..knowledge import KnowledgeBase
from ..models import ItemInput
from .client import LLMClient, LLMError, extract_json

log = logging.getLogger(__name__)

_EXTRACT_SYSTEM = (
    "You are a forensic evidence clerk for an Indian police investigation. Split the investigator's notes "
    "into individual exhibits. Return ONLY a JSON array; each element: "
    '{"label": string|null, "description": string, "location": string|null, "quantity": integer, '
    '"collected": boolean, "type_id": string}. type_id MUST be one of the allowed ids given. '
    "Copy wording from the notes; never invent exhibits, never include names of victims or witnesses."
)

_CLASSIFY_SYSTEM = (
    "You map one crime-scene exhibit to exactly one evidence type id from a closed list. "
    'Return ONLY JSON: {"type_id": "<id from the list>", "confidence": <0..1>}.'
)

_NARRATIVE_SYSTEM = (
    "You draft the covering paragraph of a forwarding letter from an Investigating Officer to a State Forensic "
    "Science Laboratory. Formal, factual, 4-6 sentences, no speculation about guilt, no personal names. "
    "Mention the most urgent exhibits and why, using only the facts provided."
)


def llm_extract_items(llm: LLMClient, kb: KnowledgeBase, text: str) -> list[tuple[ItemInput, str | None]] | None:
    """Return (item, proposed_type_id) pairs; the proposal is used only when keyword rules are unsure."""
    allowed = ", ".join(sorted(kb.types))
    try:
        reply = llm.chat(_EXTRACT_SYSTEM, f"Allowed type ids: {allowed}\n\nInvestigator notes:\n{text}", max_tokens=1800)
        data = extract_json(reply)
    except LLMError as exc:
        log.warning("LLM extraction unavailable: %s", exc)
        return None
    if not isinstance(data, list):
        return None
    items: list[tuple[ItemInput, str | None]] = []
    for raw in data:
        if not isinstance(raw, dict) or not str(raw.get("description", "")).strip():
            continue
        hint = raw.get("type_id") if raw.get("type_id") in kb.types else None
        try:
            item = ItemInput(
                description=str(raw["description"])[:500], label=(str(raw["label"])[:20] if raw.get("label") else None),
                location=(str(raw["location"])[:200] if raw.get("location") else None),
                quantity=max(1, min(int(raw.get("quantity") or 1), 500)), collected=bool(raw.get("collected", True)),
            )
            items.append((item, hint))
        except (ValueError, TypeError):
            continue
    return items or None


def llm_classify(llm: LLMClient, kb: KnowledgeBase, description: str) -> str | None:
    allowed = "\n".join(f"- {t.id}: {t.name}" for t in kb.types.values())
    try:
        data = extract_json(llm.chat(_CLASSIFY_SYSTEM, f"Types:\n{allowed}\n\nExhibit: {description}", max_tokens=80))
    except LLMError as exc:
        log.warning("LLM classification unavailable: %s", exc)
        return None
    tid = data.get("type_id") if isinstance(data, dict) else None
    return tid if tid in kb.types else None


def llm_narrative(llm: LLMClient, facts: str) -> str | None:
    try:
        text = llm.chat(_NARRATIVE_SYSTEM, facts, max_tokens=400).strip()
    except LLMError as exc:
        log.warning("LLM narrative unavailable: %s", exc)
        return None
    return text[:2000] if text else None
