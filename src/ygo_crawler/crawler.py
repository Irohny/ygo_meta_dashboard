from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from .client import YGOProDeckClient
from .config import (
    DEFAULT_CATEGORY_PAGE_SIZE,
    DEFAULT_META_DECK_API_FORMAT,
    DEFAULT_META_DECK_API_URL,
    DEFAULT_META_DECK_CATEGORY_URL,
)
from .filters import find_excluded_marker, is_allowed_deck, is_probably_tcg
from .models import (
    CardRecord,
    CrawlRunRecord,
    DeckCardRecord,
    DeckRecord,
    SkippedSourceRecord,
    TournamentEntryRecord,
    TournamentRecord,
)
from .parsers import parse_deck_page, parse_tournament_page
from .parsers.category import ParsedMetaDeckListing, parse_meta_deck_api_page
from .parsers.deck import ParsedDeckPage
from .storage import SQLiteStorage


@dataclass(slots=True, frozen=True)
class CrawlSummary:
    run_id: int
    tournament_site_id: int
    tournament_name: str
    tournament_url: str
    discovered_entry_count: int
    crawled_deck_count: int
    skipped_source_count: int


@dataclass(slots=True, frozen=True)
class CategoryCrawlSummary:
    run_id: int
    category_url: str
    requested_page_count: int
    crawled_page_count: int
    discovered_tournament_count: int
    discovered_deck_count: int
    crawled_deck_count: int
    skipped_source_count: int


@dataclass(slots=True, frozen=True)
class _ResolvedCategoryEntry:
    tournament_site_id: int
    tournament_slug: str
    tournament_name: str
    tournament_url: str
    tournament_date: str
    participants_count: int
    placement_label: str
    placement_sort_value: int
    placement_group_size: int | None
    player_name: str
    archetype_text: str


class TournamentCrawler:
    def __init__(self, storage: SQLiteStorage, client: YGOProDeckClient | None = None) -> None:
        self.storage = storage
        self.client = client

    def crawl_tournament(self, tournament_url: str) -> CrawlSummary:
        owns_client = self.client is None
        client = self.client or YGOProDeckClient()
        run_id = self.storage.insert_run(
            CrawlRunRecord(
                run_mode="crawl-tournament",
                started_at=_utc_now(),
            )
        )

        try:
            fetched_tournament = client.fetch(tournament_url)
            parsed_tournament = parse_tournament_page(fetched_tournament.text, fetched_tournament.final_url)

            excluded_marker = find_excluded_marker(
                parsed_tournament.tournament_name,
                parsed_tournament.subtitle_text,
                parsed_tournament.meta_description,
            )
            if excluded_marker is not None or not is_probably_tcg(
                parsed_tournament.tournament_name,
                parsed_tournament.subtitle_text,
                parsed_tournament.meta_description,
            ):
                reason = _skip_reason_for_marker(excluded_marker)
                self.storage.record_skipped_source(
                    SkippedSourceRecord(
                        run_id=run_id,
                        source_url=parsed_tournament.tournament_url,
                        source_type="tournament",
                        skip_reason=reason,
                        matched_text=excluded_marker,
                        seen_at=_utc_now(),
                    )
                )
                self.storage.finish_run(
                    run_id,
                    status="partial",
                    finished_at=_utc_now(),
                    discovered_tournament_count=0,
                    crawled_deck_count=0,
                    skipped_source_count=1,
                    note="Tournament skipped due to scope filter",
                )
                raise ValueError("Tournament is outside the configured TCG scope")

            self.storage.upsert_tournament(
                TournamentRecord(
                    tournament_site_id=parsed_tournament.tournament_site_id,
                    tournament_slug=parsed_tournament.tournament_slug,
                    tournament_name=parsed_tournament.tournament_name,
                    tournament_url=parsed_tournament.tournament_url,
                    tournament_date=parsed_tournament.tournament_date,
                    country=parsed_tournament.country,
                    tier=parsed_tournament.tier,
                    participants_count=parsed_tournament.participants_count,
                    last_seen_at=_utc_now(),
                    crawled_at=_utc_now(),
                    last_run_id=run_id,
                )
            )

            crawled_deck_count = 0
            skipped_source_count = 0

            for entry in parsed_tournament.entries:
                created_at = _utc_now()
                entry_id = self.storage.upsert_tournament_entry(
                    TournamentEntryRecord(
                        tournament_site_id=parsed_tournament.tournament_site_id,
                        deck_site_id=entry.deck_site_id,
                        placement_label=entry.placement_label,
                        placement_sort_value=entry.placement_sort_value,
                        placement_group_size=entry.placement_group_size,
                        player_name=entry.player_name,
                        archetype_text=entry.archetype_text,
                        tournament_participants_count=parsed_tournament.participants_count,
                        deck_price_usd=entry.deck_price_usd,
                        deck_url=entry.deck_url,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )

                if not entry.deck_url:
                    skipped_source_count += 1
                    self.storage.record_skipped_source(
                        SkippedSourceRecord(
                            run_id=run_id,
                            source_url=parsed_tournament.tournament_url,
                            source_type="tournament",
                            skip_reason="missing_deck_link",
                            matched_text=entry.player_name,
                            seen_at=_utc_now(),
                        )
                    )
                    continue

                fetched_deck = client.fetch(entry.deck_url)
                parsed_deck = parse_deck_page(fetched_deck.text, fetched_deck.final_url)
                deck_marker = find_excluded_marker(parsed_deck.deck_name, *parsed_deck.tags)
                if deck_marker is not None or not is_allowed_deck(parsed_deck.deck_name, *parsed_deck.tags):
                    skipped_source_count += 1
                    self.storage.record_skipped_source(
                        SkippedSourceRecord(
                            run_id=run_id,
                            source_url=parsed_deck.deck_url,
                            source_type="deck",
                            skip_reason=_skip_reason_for_marker(deck_marker),
                            matched_text=deck_marker,
                            seen_at=_utc_now(),
                        )
                    )
                    continue

                self.storage.upsert_deck(
                    DeckRecord(
                        deck_site_id=parsed_deck.deck_site_id,
                        entry_id=entry_id,
                        tournament_site_id=parsed_tournament.tournament_site_id,
                        deck_slug=parsed_deck.deck_slug,
                        deck_name=parsed_deck.deck_name,
                        deck_url=parsed_deck.deck_url,
                        placement_label=entry.placement_label,
                        placement_sort_value=entry.placement_sort_value,
                        tournament_participants_count=parsed_tournament.participants_count,
                        player_name=entry.player_name,
                        archetype_text=entry.archetype_text,
                        author_name=parsed_deck.author_name,
                        uploaded_at=parsed_deck.uploaded_at,
                        tcg_price_usd=parsed_deck.tcg_price_usd or entry.deck_price_usd,
                        primer=parsed_deck.primer,
                        fetched_at=_utc_now(),
                        last_run_id=run_id,
                    )
                )

                named_cards = [
                    CardRecord(card_passcode=card.card_passcode, canonical_name=card.card_name)
                    for card in parsed_deck.cards
                    if card.card_name
                ]
                self.storage.upsert_cards(named_cards)
                self.storage.replace_deck_cards(
                    parsed_deck.deck_site_id,
                    [
                        DeckCardRecord(
                            deck_site_id=parsed_deck.deck_site_id,
                            section=card.section,
                            card_passcode=card.card_passcode,
                            card_name=card.card_name,
                            quantity=card.quantity,
                        )
                        for card in parsed_deck.cards
                    ],
                )
                crawled_deck_count += 1

            self.storage.finish_run(
                run_id,
                status="success",
                finished_at=_utc_now(),
                discovered_tournament_count=1,
                crawled_deck_count=crawled_deck_count,
                skipped_source_count=skipped_source_count,
                note=None,
            )

            return CrawlSummary(
                run_id=run_id,
                tournament_site_id=parsed_tournament.tournament_site_id,
                tournament_name=parsed_tournament.tournament_name,
                tournament_url=parsed_tournament.tournament_url,
                discovered_entry_count=len(parsed_tournament.entries),
                crawled_deck_count=crawled_deck_count,
                skipped_source_count=skipped_source_count,
            )
        except Exception as exc:
            self.storage.finish_run(
                run_id,
                status="failed",
                finished_at=_utc_now(),
                note=str(exc),
            )
            raise
        finally:
            if owns_client:
                client.close()

    def crawl_meta_category(
        self,
        category_url: str = DEFAULT_META_DECK_CATEGORY_URL,
        *,
        page_count: int = 1,
        page_size: int = DEFAULT_CATEGORY_PAGE_SIZE,
    ) -> CategoryCrawlSummary:
        owns_client = self.client is None
        client = self.client or YGOProDeckClient()
        run_id = self.storage.insert_run(
            CrawlRunRecord(
                run_mode="full-crawl",
                started_at=_utc_now(),
            )
        )

        try:
            fetched_category = client.fetch(category_url)
            crawled_deck_count = 0
            skipped_source_count = 0
            discovered_deck_count = 0
            crawled_page_count = 0
            seen_tournament_names: set[str] = set()
            tournament_participants_cache: dict[str, int | None] = {}

            normalized_page_count = max(page_count, 1)
            normalized_page_size = max(page_size, 1)

            for page_index in range(normalized_page_count):
                api_url = _build_meta_deck_api_url(offset=page_index * normalized_page_size, limit=normalized_page_size)
                fetched_listing_page = client.fetch(api_url)
                listings = parse_meta_deck_api_page(fetched_listing_page.text)
                if not listings:
                    break

                crawled_page_count += 1
                discovered_deck_count += len(listings)

                for listing in listings:
                    try:
                        fetched_deck = client.fetch(listing.deck_url)
                        parsed_deck = parse_deck_page(fetched_deck.text, fetched_deck.final_url)
                    except Exception as exc:
                        skipped_source_count += 1
                        self.storage.record_skipped_source(
                            SkippedSourceRecord(
                                run_id=run_id,
                                source_url=listing.deck_url,
                                source_type="search_result",
                                skip_reason="parse_error",
                                matched_text=str(exc),
                                seen_at=_utc_now(),
                            )
                        )
                        continue

                    deck_marker = find_excluded_marker(parsed_deck.deck_name, *parsed_deck.tags)
                    if deck_marker is not None or not is_allowed_deck(parsed_deck.deck_name, *parsed_deck.tags):
                        skipped_source_count += 1
                        self.storage.record_skipped_source(
                            SkippedSourceRecord(
                                run_id=run_id,
                                source_url=parsed_deck.deck_url,
                                source_type="deck",
                                skip_reason=_skip_reason_for_marker(deck_marker),
                                matched_text=deck_marker,
                                seen_at=_utc_now(),
                            )
                        )
                        continue

                    fallback_participants_count = listing.participants_count
                    if fallback_participants_count is None and parsed_deck.tournament_url is not None:
                        fallback_participants_count = _load_tournament_participants_count(
                            client,
                            parsed_deck.tournament_url,
                            tournament_participants_cache,
                        )

                    resolved_entry = _resolve_category_entry(
                        listing,
                        parsed_deck,
                        fallback_participants_count=fallback_participants_count,
                    )
                    if resolved_entry is None:
                        skipped_source_count += 1
                        self.storage.record_skipped_source(
                            SkippedSourceRecord(
                                run_id=run_id,
                                source_url=parsed_deck.deck_url,
                                source_type="lookup_hit",
                                skip_reason="parse_error",
                                matched_text="missing tournament metadata",
                                seen_at=_utc_now(),
                            )
                        )
                        continue

                    seen_tournament_names.add(resolved_entry.tournament_name)

                    timestamp = _utc_now()
                    self.storage.upsert_tournament(
                        TournamentRecord(
                            tournament_site_id=resolved_entry.tournament_site_id,
                            tournament_slug=resolved_entry.tournament_slug,
                            tournament_name=resolved_entry.tournament_name,
                            tournament_url=resolved_entry.tournament_url,
                            tournament_date=resolved_entry.tournament_date,
                            participants_count=resolved_entry.participants_count,
                            country=None,
                            tier=None,
                            last_seen_at=timestamp,
                            crawled_at=timestamp,
                            last_run_id=run_id,
                        )
                    )

                    entry_id = self.storage.upsert_tournament_entry(
                        TournamentEntryRecord(
                            tournament_site_id=resolved_entry.tournament_site_id,
                            deck_site_id=parsed_deck.deck_site_id,
                            placement_label=resolved_entry.placement_label,
                            placement_sort_value=resolved_entry.placement_sort_value,
                            placement_group_size=resolved_entry.placement_group_size,
                            player_name=resolved_entry.player_name,
                            archetype_text=resolved_entry.archetype_text,
                            tournament_participants_count=resolved_entry.participants_count,
                            deck_price_usd=parsed_deck.tcg_price_usd,
                            deck_url=parsed_deck.deck_url,
                            entry_source="deck_search_lookup",
                            created_at=timestamp,
                            updated_at=timestamp,
                        )
                    )

                    self.storage.upsert_deck(
                        DeckRecord(
                            deck_site_id=parsed_deck.deck_site_id,
                            entry_id=entry_id,
                            tournament_site_id=resolved_entry.tournament_site_id,
                            deck_slug=parsed_deck.deck_slug,
                            deck_name=parsed_deck.deck_name,
                            deck_url=parsed_deck.deck_url,
                            placement_label=resolved_entry.placement_label,
                            placement_sort_value=resolved_entry.placement_sort_value,
                            tournament_participants_count=resolved_entry.participants_count,
                            player_name=resolved_entry.player_name,
                            archetype_text=resolved_entry.archetype_text,
                            author_name=parsed_deck.author_name,
                            uploaded_at=parsed_deck.uploaded_at,
                            tcg_price_usd=parsed_deck.tcg_price_usd,
                            primer=parsed_deck.primer,
                            fetched_at=timestamp,
                            last_run_id=run_id,
                        )
                    )

                    named_cards = [
                        CardRecord(card_passcode=card.card_passcode, canonical_name=card.card_name)
                        for card in parsed_deck.cards
                        if card.card_name
                    ]
                    self.storage.upsert_cards(named_cards)
                    self.storage.replace_deck_cards(
                        parsed_deck.deck_site_id,
                        [
                            DeckCardRecord(
                                deck_site_id=parsed_deck.deck_site_id,
                                section=card.section,
                                card_passcode=card.card_passcode,
                                card_name=card.card_name,
                                quantity=card.quantity,
                            )
                            for card in parsed_deck.cards
                        ],
                    )
                    crawled_deck_count += 1

                if len(listings) < normalized_page_size:
                    break

            self.storage.finish_run(
                run_id,
                status="success",
                finished_at=_utc_now(),
                discovered_tournament_count=len(seen_tournament_names),
                crawled_deck_count=crawled_deck_count,
                skipped_source_count=skipped_source_count,
                note=None if crawled_deck_count else "No deck pages stored from category crawl",
            )

            return CategoryCrawlSummary(
                run_id=run_id,
                category_url=fetched_category.final_url,
                requested_page_count=normalized_page_count,
                crawled_page_count=crawled_page_count,
                discovered_tournament_count=len(seen_tournament_names),
                discovered_deck_count=discovered_deck_count,
                crawled_deck_count=crawled_deck_count,
                skipped_source_count=skipped_source_count,
            )
        except Exception as exc:
            self.storage.finish_run(
                run_id,
                status="failed",
                finished_at=_utc_now(),
                note=str(exc),
            )
            raise
        finally:
            if owns_client:
                client.close()


def _skip_reason_for_marker(marker: str | None) -> str:
    if marker == "ocg":
        return "ocg_marker"
    if marker == "genyssis":
        return "genyssis_marker"
    if marker == "genesis":
        return "genesis_marker"
    return "not_tcg"


def _build_meta_deck_api_url(*, offset: int, limit: int) -> str:
    query = urlencode(
        {
            "limit": limit,
            "offset": offset,
        }
    )
    return f"{DEFAULT_META_DECK_API_URL}?&{query}&format={DEFAULT_META_DECK_API_FORMAT}&tournament"


def _resolve_category_entry(
    listing: ParsedMetaDeckListing,
    parsed_deck: ParsedDeckPage,
    *,
    fallback_participants_count: int | None = None,
) -> _ResolvedCategoryEntry | None:
    tournament_site_id = parsed_deck.tournament_site_id
    tournament_slug = parsed_deck.tournament_slug
    tournament_url = parsed_deck.tournament_url
    tournament_date = parsed_deck.tournament_date
    if tournament_site_id is None or tournament_slug is None or tournament_url is None or tournament_date is None:
        return None

    placement_label = parsed_deck.placement_label or listing.placement_label
    placement_sort_value = parsed_deck.placement_sort_value or listing.placement_sort_value
    placement_group_size = parsed_deck.placement_group_size
    if placement_label is None or placement_sort_value is None:
        return None
    if placement_group_size is None:
        placement_group_size = listing.placement_group_size

    player_name = parsed_deck.player_name or listing.player_name
    if player_name is None:
        return None

    participants_count = listing.participants_count or fallback_participants_count
    if participants_count is None:
        return None

    tournament_name = parsed_deck.tournament_name or listing.tournament_name
    if tournament_name is None:
        return None
    archetype_text = parsed_deck.deck_name or listing.deck_name

    return _ResolvedCategoryEntry(
        tournament_site_id=tournament_site_id,
        tournament_slug=tournament_slug,
        tournament_name=tournament_name,
        tournament_url=tournament_url,
        tournament_date=tournament_date,
        participants_count=participants_count,
        placement_label=placement_label,
        placement_sort_value=placement_sort_value,
        placement_group_size=placement_group_size,
        player_name=player_name,
        archetype_text=archetype_text,
    )


def _load_tournament_participants_count(
    client: YGOProDeckClient,
    tournament_url: str,
    cache: dict[str, int | None],
) -> int | None:
    if tournament_url not in cache:
        try:
            fetched_tournament = client.fetch(tournament_url)
            parsed_tournament = parse_tournament_page(fetched_tournament.text, fetched_tournament.final_url)
        except Exception:
            cache[tournament_url] = None
        else:
            cache[tournament_url] = parsed_tournament.participants_count
    return cache[tournament_url]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_storage(database_path: str | Path) -> SQLiteStorage:
    storage = SQLiteStorage(database_path)
    storage.initialize()
    return storage