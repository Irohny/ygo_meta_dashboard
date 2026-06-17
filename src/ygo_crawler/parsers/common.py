from __future__ import annotations

from datetime import datetime
import re
from urllib.parse import parse_qs, urljoin, urlparse

from ..config import BASE_URL

_SITE_ID_RE = re.compile(r"-(\d+)(?:/)?$")
_PRICE_RE = re.compile(r"\$\s*([0-9]+(?:\.[0-9]+)?)")
_PLACEMENT_RE = re.compile(r"top\s*(\d+)", re.IGNORECASE)
_ORDINAL_RE = re.compile(r"(\d+)(?:st|nd|rd|th)", re.IGNORECASE)
_FLAG_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")
_WHITESPACE_RE = re.compile(r"\s+")
_PLAYERS_RE = re.compile(r"~?([0-9][0-9,]*)\s+players", re.IGNORECASE)


def normalize_whitespace(text: str | None) -> str:
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", text).strip()


def absolute_url(value: str | None) -> str | None:
    if not value:
        return None
    return urljoin(BASE_URL, value)


def extract_slug_and_site_id(url: str) -> tuple[str, int]:
    tail = urlparse(url).path.rstrip("/").split("/")[-1]
    match = _SITE_ID_RE.search(tail)
    if match is None:
        raise ValueError(f"Could not extract site id from URL: {url}")
    site_id = int(match.group(1))
    slug = tail[: match.start()].strip("-")
    return slug, site_id


def extract_card_passcode(url: str | None) -> int | None:
    if not url:
        return None
    query = parse_qs(urlparse(url).query)
    values = query.get("search")
    if not values:
        return None
    try:
        return int(values[0])
    except ValueError:
        return None


def parse_price_usd(text: str | None) -> float | None:
    if not text:
        return None
    match = _PRICE_RE.search(text.replace(",", ""))
    if match is None:
        return None
    return float(match.group(1))


def strip_flag_emoji(text: str | None) -> str:
    return normalize_whitespace(_FLAG_RE.sub("", text or ""))


def parse_human_date(text: str | None) -> str | None:
    normalized = normalize_whitespace(text)
    if not normalized:
        return None
    without_suffixes = _ORDINAL_RE.sub(r"\1", normalized)
    for pattern in ("%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(without_suffixes, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def parse_players_count(text: str | None) -> int | None:
    normalized = normalize_whitespace(text)
    if not normalized:
        return None
    match = _PLAYERS_RE.search(normalized)
    if match is not None:
        return int(match.group(1).replace(",", ""))

    raw_value = normalized.removeprefix("~").replace(",", "")
    if raw_value.isdigit():
        return int(raw_value)
    return None


def parse_placement(label: str) -> tuple[str, int, int | None]:
    normalized = normalize_whitespace(label)
    lowered = normalized.lower()

    if lowered == "winner":
        return normalized, 1, 1
    if lowered in {"runner-up", "runner up"}:
        return normalized, 2, 2

    top_match = _PLACEMENT_RE.search(lowered)
    if top_match is not None:
        value = int(top_match.group(1))
        return normalized, value, value

    ordinal_match = _ORDINAL_RE.search(lowered)
    if ordinal_match is not None:
        value = int(ordinal_match.group(1))
        return normalized, value, None

    raise ValueError(f"Unsupported placement label: {label}")
