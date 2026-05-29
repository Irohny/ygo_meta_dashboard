from __future__ import annotations

import argparse
from pathlib import Path

from .card_metadata import enrich_cards
from .config import (
    CARD_METADATA_BATCH_SIZE,
    DEFAULT_DATABASE_PATH,
    DEFAULT_INITIAL_CRAWL_PAGE_COUNT,
    DEFAULT_META_DECK_CATEGORY_URL,
)
from .crawler import TournamentCrawler, default_storage
from .exporter import export_deck_cards_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YGOPRODeck TCG crawler")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db = subparsers.add_parser("init-db", help="Initialize the SQLite database schema")
    init_db.add_argument("--db-path", type=Path, default=DEFAULT_DATABASE_PATH)

    crawl_tournament = subparsers.add_parser("crawl-tournament", help="Crawl a single tournament page and linked decks")
    crawl_tournament.add_argument("tournament_url")
    crawl_tournament.add_argument("--db-path", type=Path, default=DEFAULT_DATABASE_PATH)

    crawl_category = subparsers.add_parser(
        "crawl-category",
        help="Crawl the Tournament Meta Decks category page and linked deck pages",
    )
    crawl_category.add_argument("category_url", nargs="?", default=DEFAULT_META_DECK_CATEGORY_URL)
    crawl_category.add_argument("--pages", type=int, default=DEFAULT_INITIAL_CRAWL_PAGE_COUNT)
    crawl_category.add_argument("--db-path", type=Path, default=DEFAULT_DATABASE_PATH)

    enrich_cards_parser = subparsers.add_parser(
        "enrich-cards",
        help="Enrich stored cards with YGOPRODeck card metadata such as archetype and type",
    )
    enrich_cards_parser.add_argument("--db-path", type=Path, default=DEFAULT_DATABASE_PATH)
    enrich_cards_parser.add_argument("--batch-size", type=int, default=CARD_METADATA_BATCH_SIZE)
    enrich_cards_parser.add_argument("--limit", type=int)

    export_cards_csv_parser = subparsers.add_parser(
        "export-cards-csv",
        help="Export a flat CSV dump of deck cards plus card metadata for analysis",
    )
    export_cards_csv_parser.add_argument("--db-path", type=Path, default=DEFAULT_DATABASE_PATH)
    export_cards_csv_parser.add_argument("--output", type=Path, default=Path("exports/deck_cards_flat.csv"))

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init-db":
        with default_storage(args.db_path):
            pass
        print(f"Initialized database schema at {args.db_path}")
        return 0

    if args.command == "crawl-tournament":
        with default_storage(args.db_path) as storage:
            crawler = TournamentCrawler(storage)
            summary = crawler.crawl_tournament(args.tournament_url)
        print(
            "Crawled tournament "
            f"{summary.tournament_name} ({summary.tournament_site_id}) with "
            f"{summary.discovered_entry_count} entries, "
            f"{summary.crawled_deck_count} stored decks and "
            f"{summary.skipped_source_count} skipped sources."
        )
        return 0

    if args.command == "crawl-category":
        with default_storage(args.db_path) as storage:
            crawler = TournamentCrawler(storage)
            summary = crawler.crawl_meta_category(args.category_url, page_count=args.pages)
        print(
            "Crawled category "
            f"{summary.category_url} across "
            f"{summary.crawled_page_count}/{summary.requested_page_count} pages with "
            f"{summary.discovered_deck_count} discovered decks across "
            f"{summary.discovered_tournament_count} tournaments, "
            f"{summary.crawled_deck_count} stored decks and "
            f"{summary.skipped_source_count} skipped sources."
        )
        return 0

    if args.command == "enrich-cards":
        summary = enrich_cards(args.db_path, batch_size=args.batch_size, limit=args.limit)
        print(
            "Enriched card metadata for "
            f"{summary.enriched_count} cards from {summary.requested_count} requested passcodes "
            f"across {summary.batch_count} batches."
        )
        return 0

    if args.command == "export-cards-csv":
        output_path = export_deck_cards_csv(args.db_path, args.output)
        print(f"Exported flat deck-card CSV to {output_path}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())