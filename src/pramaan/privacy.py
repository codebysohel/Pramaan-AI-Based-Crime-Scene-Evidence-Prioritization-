"""Privacy gate — enforced in code, not by prompt.

Pramaan triages *exhibits*, never people. Any input (free text, item fields,
photo captions, update reasons) that contains a personal identifier is rejected
before it is parsed, scored or stored, whichever surface it came from (MCP, REST,
CLI). Only the *kind* of identifier is reported and logged — never the value.

Detected: Aadhaar-format numbers, Indian mobile numbers, e-mail addresses, and
optional case-specific protected terms (e.g. a victim's name) supplied as
SHA-256 hashes in ``PRAMAAN_PROTECTED_TERMS`` so the list itself reveals nothing.
Legal basis: BNS 2023 §72 (identity of sexual-offence victims) and the Digital
Personal Data Protection Act 2023 (data minimisation).
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .config import get_settings

_PATTERNS: dict[str, re.Pattern[str]] = {
    "aadhaar_number": re.compile(r"(?<![\d/.-])[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}(?![\d/.-])"),
    "mobile_number": re.compile(r"(?<![\d/.-])(?:\+91[\s-]?|0)?[6-9]\d{9}(?![\d/.-])"),
    "email_address": re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}"),
}


class PrivacyViolation(ValueError):
    def __init__(self, kinds: list[str]) -> None:
        self.kinds = kinds
        super().__init__(
            f"Input rejected: it contains personal identifiers ({', '.join(kinds)}). Pramaan works on exhibit "
            "descriptions only — remove names, phone, Aadhaar and e-mail details and describe the exhibit instead "
            "(BNS 2023 §72; DPDP Act 2023)."
        )


@lru_cache(maxsize=4)
def _protected_hashes(path: str) -> frozenset[str]:
    p = Path(path)
    if not p.is_file():
        return frozenset()
    lines = [ln.strip().lower() for ln in p.read_text(encoding="utf-8").splitlines()]
    return frozenset(ln for ln in lines if re.fullmatch(r"[0-9a-f]{64}", ln))


def hash_term(term: str) -> str:
    """Normalise and hash a protected term (what goes into the protected-terms file)."""
    return hashlib.sha256(" ".join(term.lower().split()).encode("utf-8")).hexdigest()


def scan(texts: Iterable[str | None]) -> list[str]:
    kinds: set[str] = set()
    hashes = _protected_hashes(str(get_settings().protected_terms_file))
    for text in texts:
        if not text:
            continue
        for kind, pat in _PATTERNS.items():
            if pat.search(text):
                kinds.add(kind)
        if hashes:
            words = re.findall(r"[^\W\d_]+", text.lower())
            grams = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
            if any(hashlib.sha256(g.encode("utf-8")).hexdigest() in hashes for g in grams):
                kinds.add("protected_term")
    return sorted(kinds)


def case_texts(case) -> list[str | None]:
    out: list[str | None] = [case.case_ref, case.title, case.description, *case.photo_captions]
    for it in case.items:
        out += [it.description, it.location, it.label, it.override_reason]
        if it.electronic:
            e = it.electronic
            out += [e.device, e.record_description, e.part_a_signatory_role, e.expert_role]
    return out
