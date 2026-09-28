"""Parse an investigator's free-text scene notes into structured exhibits.

Handles the way seizure lists are actually written in the field:

    Ex-A1: half-burnt cigarette butt, 3 m from the body (wet from rain)
    2) Bloodstained stone approx 2 kg near the head
    - two liquor bottles and a gutka packet under the culvert; mobile phone of deceased

Rules: split on lines / bullets / semicolons; split a segment further on commas
or "and" only when it names two or more distinct objects; pull out exhibit
labels, quantities, storage conditions and "not yet collected" status. Nothing
is invented: text that names no known exhibit becomes a warning (or, with the
watsonx.ai layer enabled, is offered to Granite for a closed-vocabulary guess).
"""

from __future__ import annotations

import re

from .classifier import rank_types
from .knowledge import KnowledgeBase
from .models import ItemInput

_LABEL = re.compile(
    r"^\s*(?:[-*•▪]\s*)?(?P<label>(?:ex(?:hibit)?|mo|article|art)\.?\s*(?:no\.?)?\s*[-#:]?\s*[a-z]{0,2}[-\s]?\d{1,3}[a-z]?)\s*[:.)\-–]?\s*",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*(?:[-*•▪]|\(?\d{1,3}[.)])\s*")
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a pair of": 2, "pair of": 2,
    "several": 3, "multiple": 3, "few": 3,
}
_QTY = re.compile(
    r"\b(?P<n>\d{1,3}|a pair of|pair of|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|several|multiple|few)\b(?![-\u2010\u2011]\w)",
    re.IGNORECASE,
)
_CONDITIONS = [
    ("frozen", re.compile(r"\b(frozen|freezer|-20\s*°?\s*c)\b", re.I)),
    ("refrigerated", re.compile(r"\b(refrigerated|fridge|refrigerator|ice\s*box|cold\s*storage|kept\s+cold|cold\s+chain|2\s*-\s*8\s*°?\s*c)\b", re.I)),
    ("dry_sealed", re.compile(r"\b(air[\s-]?dried|dried\s+and\s+sealed|paper\s+(?:envelope|bag|packed)|packed\s+in\s+paper|airtight\s+(?:can|container|tin))\b", re.I)),
    ("wet", re.compile(r"\b(wet|damp|soaked|rain[\s-]?soaked|rainwater|moist|in\s+(?:a\s+)?(?:plastic|polythene)\s+bag|sealed\s+in\s+plastic)\b", re.I)),
    ("sunlight", re.compile(r"\b(direct\s+sun(?:light)?|in\s+the\s+sun|exposed\s+to\s+(?:the\s+)?sun|under\s+the\s+sun)\b", re.I)),
    ("hot", re.compile(r"\b(hot|heat|inside\s+(?:a\s+)?(?:closed\s+)?(?:car|vehicle)\s+in\s+the\s+sun)\b", re.I)),
]
_NOT_COLLECTED = re.compile(
    r"\b(not\s+yet\s+(?:collected|seized|lifted)|still\s+at\s+(?:the\s+)?scene|yet\s+to\s+be\s+(?:collected|seized|lifted)|to\s+be\s+collected|not\s+collected|uncollected|in\s+situ\s+pending)\b",
    re.I,
)
_LOCATION = re.compile(
    r"\b(?:found|recovered|lying|seen|located|kept|collected)?\s*(?P<loc>(?:near|beside|next\s+to|under|inside|on|at|behind|below|in\s+front\s+of|from|around|close\s+to|about|approx\.?|approximately)\s+.+)$",
    re.I,
)
_HEADER = re.compile(r"^\s*[a-z /&-]{0,40}:\s*$", re.I)


def _split_segments(text: str) -> list[str]:
    segs: list[str] = []
    for line in re.split(r"[\r\n]+", text):
        line = line.strip()
        if not line or _HEADER.match(line):
            continue
        # Inline numbering "1) knife 2) stone" -> split before each number marker.
        parts = re.split(r"\s(?=\(?\d{1,2}[.)]\s)", line)
        for part in parts:
            segs.extend(p.strip() for p in part.split(";") if p.strip())
    return segs


def _distinct_objects(kb: KnowledgeBase, text: str) -> int:
    return len({et.id for _, et, _ in rank_types(kb, text) if et.kind != "stain"})


def _split_multi(kb: KnowledgeBase, seg: str) -> list[str]:
    if _distinct_objects(kb, seg) < 2:
        return [seg]
    pieces = [p.strip(" ,.") for p in re.split(r",\s*(?:and\s+)?|\s+and\s+|\s+along\s+with\s+|\s+with\s+a\s+", seg)]
    pieces = [p for p in pieces if p]
    merged: list[str] = []
    for p in pieces:
        # A fragment that names no object (e.g. "wet from rain") belongs to the previous piece.
        if merged and not rank_types(kb, p):
            merged[-1] = f"{merged[-1]}, {p}"
        else:
            merged.append(p)
    return merged or [seg]


def _quantity(text: str) -> int:
    m = _QTY.search(text)
    if not m:
        return 1
    token = m.group("n").lower()
    if token.isdigit():
        n = int(token)
        # Ignore numbers that are really measurements ("2 kg", "3 m", "1 L").
        tail = text[m.end(): m.end() + 9].lower()
        if re.match(r"\s*(?:(?:kg|g|gm|m|mtr|metres?|meters?|cm|mm|l|ml|litres?|liters?|ft|feet|am|pm|hrs?)\b|°)", tail):
            return 1
        return max(1, min(n, 500))
    return _NUMBER_WORDS.get(token, 1)


def _condition(text: str) -> str | None:
    for cond, pat in _CONDITIONS:
        if pat.search(text):
            return cond
    return None


def parse_description(kb: KnowledgeBase, text: str) -> tuple[list[ItemInput], list[str]]:
    """Return (items, warnings). Deterministic; never calls a network service."""
    items: list[ItemInput] = []
    warnings: list[str] = []
    for seg in _split_segments(text):
        label = None
        m = _LABEL.match(seg)
        if m:
            label = re.sub(r"\s+", "", m.group("label")).replace("exhibit", "Ex").replace("EXHIBIT", "Ex")
            label = label[0].upper() + label[1:]
            seg = seg[m.end():]
        else:
            seg = _BULLET.sub("", seg)
        seg = seg.strip(" .,-")
        if len(seg) < 3:
            continue
        pieces = _split_multi(kb, seg)
        for idx, piece in enumerate(pieces):
            if not rank_types(kb, piece):
                if len(piece.split()) >= 3:
                    warnings.append(f"No known exhibit type recognised in: '{piece[:80]}'")
                    items.append(ItemInput(description=piece, label=label if idx == 0 else None))
                continue
            loc = None
            lm = _LOCATION.search(piece)
            if lm and len(lm.group("loc").split()) >= 2:
                loc = lm.group("loc").strip(" .,")
            items.append(
                ItemInput(
                    description=piece,
                    label=(label if len(pieces) == 1 else (f"{label}.{idx + 1}" if label else None)),
                    location=loc,
                    quantity=_quantity(piece),
                    collected=not bool(_NOT_COLLECTED.search(piece)),
                    condition=_condition(piece),
                )
            )
    if not items:
        warnings.append("No exhibits could be extracted. List one exhibit per line, e.g. 'Ex-1: knife near the body'.")
    return items, warnings
