from __future__ import annotations

from dataclasses import dataclass
import json
import re

from bs4 import BeautifulSoup

from .common import absolute_url, extract_slug_and_site_id, normalize_whitespace, parse_placement, parse_players_count

_LISTING_STATS_RE = re.compile(
    r"(?P<placement>Winner|Runner-Up|Runner Up|Top\s+\d+|\d+(?:st|nd|rd|th))\s+\((?P<players>~?[0-9][0-9,]*)\s+players\)\s+(?P<relative_age>.+?)\s+piloted by\s+(?P<pilot>.+)$",
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class ParsedMetaDeckListing:
    deck_site_id: int
    deck_slug: str
    deck_name: str
    deck_url: str
    tournament_name: str | None
    placement_label: str | None
    placement_sort_value: int | None
    placement_group_size: int | None
    participants_count: int | None
    player_name: str | None
    relative_age: str | None


def parse_meta_deck_category_page(html: str) -> tuple[ParsedMetaDeckListing, ...]:
    soup = BeautifulSoup(html, "html.parser")
    parsed: list[ParsedMetaDeckListing] = []

    for container in soup.select("#latest-decks .deck_article-card-container"):
        tournament_badge = container.select_one("span.deck-type-badge")
        deck_anchor = container.select_one("a.deck_article-card-title[href*='/deck/']")
        stats_element = container.select_one("div.deck_article-card-stats")

        if tournament_badge is None or deck_anchor is None or stats_element is None:
            continue

        tournament_name = normalize_whitespace(tournament_badge.get_text(" ", strip=True))
        deck_name = normalize_whitespace(deck_anchor.get_text(" ", strip=True))
        deck_url = absolute_url(deck_anchor.get("href"))
        stats_text = normalize_whitespace(stats_element.get_text(" ", strip=True))

        if not tournament_name or not deck_name or not deck_url or not stats_text:
            continue

        stats_match = _LISTING_STATS_RE.search(stats_text)
        if stats_match is None:
            continue

        placement_label, placement_sort_value, placement_group_size = parse_placement(stats_match.group("placement"))
        participants_count = parse_players_count(stats_match.group("players"))
        relative_age = normalize_whitespace(stats_match.group("relative_age")) or None
        player_name = normalize_whitespace(stats_match.group("pilot")) or None

        deck_slug, deck_site_id = extract_slug_and_site_id(deck_url)
        parsed.append(
            ParsedMetaDeckListing(
                deck_site_id=deck_site_id,
                deck_slug=deck_slug,
                deck_name=deck_name,
                deck_url=deck_url,
                tournament_name=tournament_name,
                placement_label=placement_label,
                placement_sort_value=placement_sort_value,
                placement_group_size=placement_group_size,
                participants_count=participants_count,
                player_name=player_name,
                relative_age=relative_age,
            )
        )

    return tuple(parsed)


def parse_meta_deck_api_page(payload: str) -> tuple[ParsedMetaDeckListing, ...]:
    raw_items = json.loads(payload)
    if not isinstance(raw_items, list):
        raise ValueError("Expected a JSON array for category API response")

    parsed: list[ParsedMetaDeckListing] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue

        deck_name = normalize_whitespace(_string_value(item.get("deck_name")))
        pretty_url = normalize_whitespace(_string_value(item.get("pretty_url")))
        tournament_name = normalize_whitespace(_string_value(item.get("tournamentName"))) or None
        placement_text = normalize_whitespace(_string_value(item.get("tournamentPlacement"))) or None
        if not deck_name or not pretty_url:
            continue

        deck_url = absolute_url(f"/deck/{pretty_url}")
        if not deck_url:
            continue

        placement_label: str | None = None
        placement_sort_value: int | None = None
        placement_group_size: int | None = None
        if placement_text:
            placement_label, placement_sort_value, placement_group_size = parse_placement(placement_text)

        participants_count = _int_value(item.get("tournamentPlayerCount"))
        player_name = normalize_whitespace(_string_value(item.get("tournamentPlayerName"))) or None
        relative_age = normalize_whitespace(_string_value(item.get("submit_date"))) or None
        deck_slug, deck_site_id = extract_slug_and_site_id(deck_url)

        parsed.append(
            ParsedMetaDeckListing(
                deck_site_id=deck_site_id,
                deck_slug=deck_slug,
                deck_name=deck_name,
                deck_url=deck_url,
                tournament_name=tournament_name,
                placement_label=placement_label,
                placement_sort_value=placement_sort_value,
                placement_group_size=placement_group_size,
                participants_count=participants_count,
                player_name=player_name,
                relative_age=relative_age,
            )
        )

    return tuple(parsed)


def _string_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _int_value(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = normalize_whitespace(_string_value(value))
    if not text:
        return None
    digits = text.replace(",", "").removeprefix("~")
    if digits.isdigit():
        return int(digits)
    return None