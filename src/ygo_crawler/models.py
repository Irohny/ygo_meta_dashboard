from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RunMode = Literal["full-crawl", "sync", "crawl-tournament", "crawl-deck"]
RunStatus = Literal["running", "success", "failed", "partial"]
SourceConfidence = Literal["confirmed_tcg", "inferred_tcg"]
EntrySource = Literal["tournament_page", "deck_search_lookup"]
DeckSection = Literal["main", "extra", "side"]
SkippedSourceType = Literal["tournament", "deck", "search_result", "lookup_hit"]
SkipReason = Literal[
    "not_tcg",
    "ocg_marker",
    "genyssis_marker",
    "genesis_marker",
    "ambiguous_format",
    "missing_deck_link",
    "parse_error",
    "duplicate",
    "manual_skip",
]


@dataclass(slots=True, frozen=True)
class CrawlRunRecord:
    run_mode: RunMode
    started_at: str
    status: RunStatus = "running"
    finished_at: str | None = None
    discovered_tournament_count: int = 0
    crawled_deck_count: int = 0
    skipped_source_count: int = 0
    note: str | None = None


@dataclass(slots=True, frozen=True)
class TournamentRecord:
    tournament_site_id: int
    tournament_name: str
    tournament_url: str
    tournament_date: str
    participants_count: int
    last_seen_at: str
    crawled_at: str
    tournament_slug: str | None = None
    country: str | None = None
    tier: str | None = None
    format: Literal["TCG"] = "TCG"
    source_confidence: SourceConfidence = "confirmed_tcg"
    last_run_id: int | None = None


@dataclass(slots=True, frozen=True)
class TournamentEntryRecord:
    tournament_site_id: int
    placement_label: str
    placement_sort_value: int
    player_name: str
    tournament_participants_count: int
    created_at: str
    updated_at: str
    deck_site_id: int | None = None
    placement_group_size: int | None = None
    archetype_text: str | None = None
    deck_price_usd: float | None = None
    deck_url: str | None = None
    entry_source: EntrySource = "tournament_page"


@dataclass(slots=True, frozen=True)
class DeckRecord:
    deck_site_id: int
    entry_id: int
    tournament_site_id: int
    deck_name: str
    deck_url: str
    placement_label: str
    placement_sort_value: int
    tournament_participants_count: int
    player_name: str
    fetched_at: str
    deck_slug: str | None = None
    archetype_text: str | None = None
    author_name: str | None = None
    uploaded_at: str | None = None
    tcg_price_usd: float | None = None
    primer: str | None = None
    last_run_id: int | None = None


@dataclass(slots=True, frozen=True)
class CardRecord:
    card_passcode: int
    canonical_name: str
    card_archetype: str | None = None
    card_type: str | None = None
    card_race: str | None = None
    card_attribute: str | None = None
    frame_type: str | None = None
    effect_text: str | None = None
    cardmarket_price_eur: float | None = None
    image_url_small: str | None = None
    last_enriched_at: str | None = None
    metadata_version: int = 0


@dataclass(slots=True, frozen=True)
class DeckCardRecord:
    deck_site_id: int
    section: DeckSection
    card_passcode: int
    quantity: int
    card_name: str | None = None


@dataclass(slots=True, frozen=True)
class SkippedSourceRecord:
    source_url: str
    source_type: SkippedSourceType
    skip_reason: SkipReason
    seen_at: str
    run_id: int | None = None
    matched_text: str | None = None