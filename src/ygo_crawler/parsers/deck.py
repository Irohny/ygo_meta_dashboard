from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from .common import (
    absolute_url,
    extract_card_passcode,
    extract_slug_and_site_id,
    normalize_whitespace,
    parse_human_date,
    parse_placement,
    parse_price_usd,
)

_SECTION_IDS = {
    "main_deck": "main",
    "extra_deck": "extra",
    "side_deck": "side",
}
_PRICE_RE = re.compile(r"TCGplayer\s*\$\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)


@dataclass(slots=True, frozen=True)
class ParsedDeckCard:
    section: str
    card_passcode: int
    quantity: int
    card_name: str | None


@dataclass(slots=True, frozen=True)
class ParsedDeckPage:
    deck_site_id: int
    deck_slug: str
    deck_name: str
    deck_url: str
    author_name: str | None
    player_name: str | None
    placement_label: str | None
    placement_sort_value: int | None
    placement_group_size: int | None
    tournament_name: str | None
    tournament_url: str | None
    tournament_site_id: int | None
    tournament_slug: str | None
    tournament_date: str | None
    uploaded_at: str | None
    tcg_price_usd: float | None
    primer: str | None
    tags: tuple[str, ...]
    cards: tuple[ParsedDeckCard, ...]


def parse_deck_page(html: str, url: str) -> ParsedDeckPage:
    soup = BeautifulSoup(html, "html.parser")

    heading = soup.find("h1")
    if heading is None:
        raise ValueError("Could not find deck heading")
    deck_name = normalize_whitespace(heading.get_text(" ", strip=True))
    if not deck_name:
        raise ValueError("Deck heading is empty")

    metadata_spans = list(soup.select("span.deck-metadata-child"))
    author_link = soup.select_one("a[href*='/author/']")
    author_name = (
        normalize_whitespace(author_link.get_text(" ", strip=True)) or None
        if author_link
        else None
    )

    metadata_texts = [
        normalize_whitespace(span.get_text(" ", strip=True)) for span in metadata_spans
    ]
    uploaded_at = _extract_uploaded_at(metadata_texts)
    tournament_metadata = _extract_tournament_metadata(metadata_spans)
    tcg_price_usd = _extract_tcg_price_usd(soup)
    primer = _extract_primer(soup)
    tags = tuple(
        normalize_whitespace(anchor.get_text(" ", strip=True))
        for anchor in soup.select("span.deck-metadata-child a[href*='/category/']")
        if normalize_whitespace(anchor.get_text(" ", strip=True))
    )

    deck_slug, deck_site_id = extract_slug_and_site_id(url)
    cards = tuple(_parse_cards(soup))

    return ParsedDeckPage(
        deck_site_id=deck_site_id,
        deck_slug=deck_slug,
        deck_name=deck_name,
        deck_url=url,
        author_name=author_name,
        player_name=tournament_metadata["player_name"],
        placement_label=tournament_metadata["placement_label"],
        placement_sort_value=tournament_metadata["placement_sort_value"],
        placement_group_size=tournament_metadata["placement_group_size"],
        tournament_name=tournament_metadata["tournament_name"],
        tournament_url=tournament_metadata["tournament_url"],
        tournament_site_id=tournament_metadata["tournament_site_id"],
        tournament_slug=tournament_metadata["tournament_slug"],
        tournament_date=tournament_metadata["tournament_date"],
        uploaded_at=uploaded_at,
        tcg_price_usd=tcg_price_usd,
        primer=primer,
        tags=tags,
        cards=cards,
    )


def _extract_uploaded_at(metadata_texts: list[str]) -> str | None:
    for text in metadata_texts:
        if "Uploaded" in text:
            return normalize_whitespace(text.split("Uploaded", 1)[1]) or None
    return None


def _extract_tcg_price_usd(soup: BeautifulSoup) -> float | None:
    full_text = normalize_whitespace(soup.get_text(" ", strip=True))
    match = _PRICE_RE.search(full_text)
    if match is not None:
        return float(match.group(1))
    return parse_price_usd(full_text)


def _extract_primer(soup: BeautifulSoup) -> str | None:
    heading = None
    for candidate in soup.select("h3.heading-section"):
        if "Deck Primer" in normalize_whitespace(candidate.get_text(" ", strip=True)):
            heading = candidate
            break
    if heading is None:
        return None

    fragments: list[str] = []
    for sibling in heading.next_siblings:
        if isinstance(sibling, Tag):
            sibling_classes = sibling.get("class", [])
            if sibling.name in {"h3", "h4"}:
                break
            if sibling.name == "div" and "deck-output" in sibling_classes:
                break
            text = normalize_whitespace(sibling.get_text(" ", strip=True))
        elif isinstance(sibling, NavigableString):
            text = normalize_whitespace(str(sibling))
        else:
            text = ""

        if not text or text == "Toggle Master Duel View":
            continue
        fragments.append(text)

    primer = normalize_whitespace(" ".join(fragments))
    return primer or None


def _parse_cards(soup: BeautifulSoup) -> list[ParsedDeckCard]:
    parsed_cards: list[ParsedDeckCard] = []
    for dom_id, section in _SECTION_IDS.items():
        container = soup.select_one(f"div.deck-output#{dom_id}")
        if container is None:
            continue

        counts: Counter[int] = Counter()
        names: dict[int, str] = {}
        for anchor in container.select("a.ygodeckcard[href*='/card/?search=']"):
            passcode = extract_card_passcode(anchor.get("href"))
            if passcode is None:
                continue
            counts[passcode] += 1

            card_name = _extract_card_name(anchor)
            if card_name and passcode not in names:
                names[passcode] = card_name

        for passcode, quantity in counts.items():
            parsed_cards.append(
                ParsedDeckCard(
                    section=section,
                    card_passcode=passcode,
                    quantity=quantity,
                    card_name=names.get(passcode),
                )
            )
    return parsed_cards


def _extract_card_name(anchor: Tag) -> str | None:
    title = normalize_whitespace(anchor.get("title"))
    if title:
        return title

    for image in anchor.select("img"):
        data_card_name = normalize_whitespace(image.get("data-cardname"))
        if data_card_name:
            return data_card_name

        alt = normalize_whitespace(image.get("alt"))
        if alt:
            return alt
    return None


def _extract_tournament_metadata(
    metadata_spans: list[Tag],
) -> dict[str, str | int | None]:
    placement_label: str | None = None
    placement_sort_value: int | None = None
    placement_group_size: int | None = None
    tournament_name: str | None = None
    tournament_url: str | None = None
    tournament_site_id: int | None = None
    tournament_slug: str | None = None
    player_name: str | None = None
    tournament_date: str | None = None

    for span in metadata_spans:
        text = normalize_whitespace(span.get_text(" ", strip=True))
        if not text:
            continue

        tournament_anchor = span.select_one("a[href*='/tournament/']")
        if tournament_anchor is not None:
            bold_elements = span.select("b")
            if bold_elements:
                placement_label = (
                    normalize_whitespace(bold_elements[0].get_text(" ", strip=True))
                    or None
                )
                if placement_label:
                    placement_label, placement_sort_value, placement_group_size = (
                        parse_placement(placement_label)
                    )

            tournament_name = (
                normalize_whitespace(tournament_anchor.get_text(" ", strip=True))
                or None
            )
            tournament_url = absolute_url(tournament_anchor.get("href"))
            if tournament_url is not None:
                tournament_slug, tournament_site_id = extract_slug_and_site_id(
                    tournament_url
                )
            continue

        if "piloted by" in text:
            player_anchor = span.select_one("a[href*='/tournaments/by-player/']")
            if player_anchor is not None:
                player_name = (
                    normalize_whitespace(player_anchor.get_text(" ", strip=True))
                    or None
                )
            continue

        if text.lower() == "pilot unknown":
            player_name = "Unknown"
            continue

        parsed_date = parse_human_date(text)
        if parsed_date is not None:
            tournament_date = parsed_date

    return {
        "placement_label": placement_label,
        "placement_sort_value": placement_sort_value,
        "placement_group_size": placement_group_size,
        "tournament_name": tournament_name,
        "tournament_url": tournament_url,
        "tournament_site_id": tournament_site_id,
        "tournament_slug": tournament_slug,
        "player_name": player_name,
        "tournament_date": tournament_date,
    }
