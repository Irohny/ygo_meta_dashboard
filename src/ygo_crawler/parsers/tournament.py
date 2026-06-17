from __future__ import annotations

from dataclasses import dataclass
import re

from bs4 import BeautifulSoup

from .common import (
    absolute_url,
    extract_slug_and_site_id,
    parse_price_usd,
    parse_placement,
    normalize_whitespace,
    strip_flag_emoji,
)

_SUBTITLE_RE = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})\s*-\s*(?P<country>.+?)\s*-\s*(?P<participants>\d+)\s+Duelists\s*-\s*(?P<tier>.+)",
    re.IGNORECASE,
)
_META_DESCRIPTION_RE = re.compile(
    r"^\s*(?P<date>\d{4}-\d{2}-\d{2})\s*-\s*(?P<name>.+?)\s*-\s*Yu-Gi-Oh!",
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class ParsedTournamentEntry:
    placement_label: str
    placement_sort_value: int
    placement_group_size: int | None
    player_name: str
    archetype_text: str | None
    deck_price_usd: float | None
    deck_url: str | None
    deck_site_id: int | None


@dataclass(slots=True, frozen=True)
class ParsedTournamentPage:
    tournament_site_id: int
    tournament_slug: str
    tournament_name: str
    tournament_url: str
    tournament_date: str
    country: str | None
    tier: str | None
    participants_count: int
    subtitle_text: str
    meta_description: str
    entries: tuple[ParsedTournamentEntry, ...]


def parse_tournament_page(html: str, url: str) -> ParsedTournamentPage:
    soup = BeautifulSoup(html, "html.parser")
    meta_description = normalize_whitespace(
        (soup.find("meta", attrs={"name": "description"}) or {}).get("content")
    )

    subtitle_element = soup.select_one("small.d-block.text-muted.ml-1.mt-2")
    subtitle_text = normalize_whitespace(
        subtitle_element.get_text(" ", strip=True) if subtitle_element else ""
    )
    tournament_name = _extract_tournament_name(
        subtitle_element, subtitle_text, meta_description
    )

    subtitle_match = _SUBTITLE_RE.search(subtitle_text)
    if subtitle_match is None:
        raise ValueError("Could not parse tournament subtitle")

    tournament_slug, tournament_site_id = extract_slug_and_site_id(url)
    entries = tuple(_parse_entries(soup))

    return ParsedTournamentPage(
        tournament_site_id=tournament_site_id,
        tournament_slug=tournament_slug,
        tournament_name=tournament_name,
        tournament_url=url,
        tournament_date=subtitle_match.group("date"),
        country=normalize_whitespace(subtitle_match.group("country")) or None,
        tier=normalize_whitespace(subtitle_match.group("tier")) or None,
        participants_count=int(subtitle_match.group("participants")),
        subtitle_text=subtitle_text,
        meta_description=meta_description,
        entries=entries,
    )


def _extract_tournament_name(
    subtitle_element: object, subtitle_text: str, meta_description: str
) -> str:
    if (
        subtitle_element is not None
        and getattr(subtitle_element, "parent", None) is not None
    ):
        container_text = normalize_whitespace(
            subtitle_element.parent.get_text(" ", strip=True)
        )
        if subtitle_text and container_text.endswith(subtitle_text):
            candidate = normalize_whitespace(container_text[: -len(subtitle_text)])
            if candidate:
                return candidate

        candidate = normalize_whitespace(container_text.replace(subtitle_text, ""))
        if candidate:
            return candidate

    description_match = _META_DESCRIPTION_RE.search(meta_description)
    if description_match is not None:
        return normalize_whitespace(description_match.group("name"))

    raise ValueError("Could not determine tournament name")


def _parse_entries(soup: BeautifulSoup) -> list[ParsedTournamentEntry]:
    parsed: list[ParsedTournamentEntry] = []
    current_placement: tuple[str, int, int | None] | None = None

    for row in soup.select("a.tournament_table_row"):
        cells = [
            normalize_whitespace(cell.get_text(" ", strip=True))
            for cell in row.select("span.as-tablecell")
        ]
        cells = [cell for cell in cells if cell]
        if len(cells) < 2:
            continue

        player_index = 1
        try:
            current_placement = parse_placement(cells[0])
        except ValueError:
            if current_placement is None:
                raise
            player_index = 0

        placement_label, placement_sort_value, placement_group_size = current_placement
        player_name = strip_flag_emoji(cells[player_index])
        archetype_index = player_index + 1
        price_index = player_index + 2
        archetype_text = (
            cells[archetype_index] if len(cells) > archetype_index else None
        )
        trailing_text = (
            " ".join(cells[price_index:])
            if len(cells) > price_index
            else row.get_text(" ", strip=True)
        )
        deck_price_usd = parse_price_usd(trailing_text)

        deck_url = absolute_url(row.get("data-deckurl") or row.get("href"))
        deck_site_id = None
        if deck_url is not None:
            _, deck_site_id = extract_slug_and_site_id(deck_url)

        parsed.append(
            ParsedTournamentEntry(
                placement_label=placement_label,
                placement_sort_value=placement_sort_value,
                placement_group_size=placement_group_size,
                player_name=player_name,
                archetype_text=archetype_text,
                deck_price_usd=deck_price_usd,
                deck_url=deck_url,
                deck_site_id=deck_site_id,
            )
        )
    return parsed
