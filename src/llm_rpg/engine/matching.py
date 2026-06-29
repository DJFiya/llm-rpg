"""Fuzzy name resolution for player-typed entity targets."""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def normalize_item_base_name(name: str) -> str:
    """Strip legacy disambiguation suffixes like 'Sword (2)'."""
    base = name.strip()
    match = re.fullmatch(r"(.+?) \(\d+\)", base)
    return match.group(1).strip() if match else base


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def best_fuzzy_match(
    query: str,
    candidates: list[str],
    *,
    threshold: float = 0.72,
) -> str | None:
    """Return the best matching candidate name, if similarity clears threshold."""
    query = query.strip()
    if not query or not candidates:
        return None
    query_l = query.lower()
    best_name: str | None = None
    best_score = threshold
    query_first = query_l.split()[0] if query_l.split() else query_l

    for name in candidates:
        name_l = name.lower()
        if query_l == name_l or query_l in name_l or name_l in query_l:
            return name
        name_first = name_l.split()[0] if name_l.split() else name_l
        score = max(
            name_similarity(query_l, name_l),
            name_similarity(query_first, name_first),
        )
        if score > best_score:
            best_score = score
            best_name = name
    return best_name


def extract_name_hint(text: str) -> str | None:
    """Pull a likely NPC name from phrases like 'i ask rigmar'."""
    match = re.search(
        r"\b(?:ask|tell|talk to|speak to|say to|tell)\s+([a-z][a-z' -]{1,40})",
        text.strip(),
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return None
