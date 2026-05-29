from __future__ import annotations

import re

from .config import EXCLUDED_MARKERS, TCG_MARKER

_TCG_PATTERN = re.compile(rf"\b{re.escape(TCG_MARKER)}\b", re.IGNORECASE)
_EXCLUDED_PATTERNS = {
    marker: re.compile(rf"\b{re.escape(marker)}\b", re.IGNORECASE)
    for marker in EXCLUDED_MARKERS
}


def _iter_texts(parts: tuple[str | None, ...]) -> list[str]:
    return [part.strip() for part in parts if part and part.strip()]


def find_excluded_marker(*parts: str | None) -> str | None:
    for text in _iter_texts(parts):
        for marker, pattern in _EXCLUDED_PATTERNS.items():
            if pattern.search(text):
                return marker
    return None


def is_probably_tcg(*parts: str | None) -> bool:
    texts = _iter_texts(parts)
    if not texts:
        return False
    if find_excluded_marker(*texts) is not None:
        return False
    return any(_TCG_PATTERN.search(text) for text in texts)


def is_allowed_deck(*parts: str | None) -> bool:
    return find_excluded_marker(*parts) is None