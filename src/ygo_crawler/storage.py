from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from .config import CARD_METADATA_VERSION
from .models import (
    CardRecord,
    CrawlRunRecord,
    DeckCardRecord,
    DeckRecord,
    SkippedSourceRecord,
    TournamentEntryRecord,
    TournamentRecord,
)


class SQLiteStorage:
    def __init__(
        self, database_path: str | Path, schema_path: str | Path | None = None
    ) -> None:
        self.database_path = Path(database_path)
        self.schema_path = (
            Path(schema_path)
            if schema_path is not None
            else self._default_schema_path()
        )
        self._connection: sqlite3.Connection | None = None

    def _default_schema_path(self) -> Path:
        return (
            Path(__file__).resolve().parents[2] / "plans" / "ygoprodeck-tcg-schema.sql"
        )

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.database_path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            self._connection = connection
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> SQLiteStorage:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connection
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()

    def initialize(self) -> None:
        schema_sql = self.schema_path.read_text(encoding="utf-8")
        with self.transaction() as connection:
            connection.executescript(schema_sql)
            self._ensure_cards_metadata_columns(connection)

    def fetch_all(
        self, query: str, parameters: Sequence[Any] | None = None
    ) -> list[sqlite3.Row]:
        cursor = self.connection.execute(query, parameters or ())
        return cursor.fetchall()

    def fetch_one(
        self, query: str, parameters: Sequence[Any] | None = None
    ) -> sqlite3.Row | None:
        cursor = self.connection.execute(query, parameters or ())
        return cursor.fetchone()

    def insert_run(self, record: CrawlRunRecord) -> int:
        values = asdict(record)
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO crawl_runs (
                    run_mode,
                    started_at,
                    finished_at,
                    status,
                    discovered_tournament_count,
                    crawled_deck_count,
                    skipped_source_count,
                    note
                ) VALUES (
                    :run_mode,
                    :started_at,
                    :finished_at,
                    :status,
                    :discovered_tournament_count,
                    :crawled_deck_count,
                    :skipped_source_count,
                    :note
                )
                """,
                values,
            )
            return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        finished_at: str,
        discovered_tournament_count: int | None = None,
        crawled_deck_count: int | None = None,
        skipped_source_count: int | None = None,
        note: str | None = None,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE crawl_runs
                SET status = :status,
                    finished_at = :finished_at,
                    discovered_tournament_count = COALESCE(:discovered_tournament_count, discovered_tournament_count),
                    crawled_deck_count = COALESCE(:crawled_deck_count, crawled_deck_count),
                    skipped_source_count = COALESCE(:skipped_source_count, skipped_source_count),
                    note = COALESCE(:note, note)
                WHERE run_id = :run_id
                """,
                {
                    "run_id": run_id,
                    "status": status,
                    "finished_at": finished_at,
                    "discovered_tournament_count": discovered_tournament_count,
                    "crawled_deck_count": crawled_deck_count,
                    "skipped_source_count": skipped_source_count,
                    "note": note,
                },
            )

    def upsert_tournament(self, record: TournamentRecord) -> None:
        values = asdict(record)
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO tournaments (
                    tournament_site_id,
                    tournament_slug,
                    tournament_name,
                    tournament_url,
                    tournament_date,
                    country,
                    tier,
                    participants_count,
                    format,
                    source_confidence,
                    last_seen_at,
                    crawled_at,
                    last_run_id
                ) VALUES (
                    :tournament_site_id,
                    :tournament_slug,
                    :tournament_name,
                    :tournament_url,
                    :tournament_date,
                    :country,
                    :tier,
                    :participants_count,
                    :format,
                    :source_confidence,
                    :last_seen_at,
                    :crawled_at,
                    :last_run_id
                )
                ON CONFLICT(tournament_site_id) DO UPDATE SET
                    tournament_slug = excluded.tournament_slug,
                    tournament_name = excluded.tournament_name,
                    tournament_url = excluded.tournament_url,
                    tournament_date = excluded.tournament_date,
                    country = excluded.country,
                    tier = excluded.tier,
                    participants_count = excluded.participants_count,
                    format = excluded.format,
                    source_confidence = excluded.source_confidence,
                    last_seen_at = excluded.last_seen_at,
                    crawled_at = excluded.crawled_at,
                    last_run_id = excluded.last_run_id
                """,
                values,
            )

    def upsert_tournament_entry(self, record: TournamentEntryRecord) -> int:
        values = asdict(record)
        with self.transaction() as connection:
            identity_row = connection.execute(
                """
                SELECT entry_id
                FROM tournament_entries
                WHERE tournament_site_id = ?
                  AND placement_sort_value = ?
                  AND player_name = ?
                """,
                (
                    record.tournament_site_id,
                    record.placement_sort_value,
                    record.player_name,
                ),
            ).fetchone()
            deck_row = None
            if record.deck_site_id is not None:
                deck_row = connection.execute(
                    """
                    SELECT entry_id
                    FROM tournament_entries
                    WHERE deck_site_id = ?
                    """,
                    (record.deck_site_id,),
                ).fetchone()

            target_entry_id: int | None = None
            if deck_row is not None:
                target_entry_id = int(deck_row["entry_id"])
            elif identity_row is not None:
                target_entry_id = int(identity_row["entry_id"])

            if deck_row is not None and identity_row is not None:
                deck_entry_id = int(deck_row["entry_id"])
                identity_entry_id = int(identity_row["entry_id"])
                if deck_entry_id != identity_entry_id:
                    keep_entry_id = deck_entry_id
                    drop_entry_id = identity_entry_id
                    keep_has_deck = connection.execute(
                        "SELECT 1 FROM decks WHERE entry_id = ?",
                        (keep_entry_id,),
                    ).fetchone()
                    if keep_has_deck is None:
                        connection.execute(
                            "UPDATE decks SET entry_id = ? WHERE entry_id = ?",
                            (keep_entry_id, drop_entry_id),
                        )
                    connection.execute(
                        "DELETE FROM tournament_entries WHERE entry_id = ?",
                        (drop_entry_id,),
                    )
                    target_entry_id = keep_entry_id

            if target_entry_id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO tournament_entries (
                        tournament_site_id,
                        deck_site_id,
                        placement_label,
                        placement_sort_value,
                        placement_group_size,
                        player_name,
                        archetype_text,
                        tournament_participants_count,
                        deck_price_usd,
                        deck_url,
                        entry_source,
                        created_at,
                        updated_at
                    ) VALUES (
                        :tournament_site_id,
                        :deck_site_id,
                        :placement_label,
                        :placement_sort_value,
                        :placement_group_size,
                        :player_name,
                        :archetype_text,
                        :tournament_participants_count,
                        :deck_price_usd,
                        :deck_url,
                        :entry_source,
                        :created_at,
                        :updated_at
                    )
                    """,
                    values,
                )
                return int(cursor.lastrowid)

            connection.execute(
                """
                UPDATE tournament_entries
                SET tournament_site_id = :tournament_site_id,
                    deck_site_id = :deck_site_id,
                    placement_label = :placement_label,
                    placement_sort_value = :placement_sort_value,
                    placement_group_size = :placement_group_size,
                    player_name = :player_name,
                    archetype_text = :archetype_text,
                    tournament_participants_count = :tournament_participants_count,
                    deck_price_usd = :deck_price_usd,
                    deck_url = :deck_url,
                    entry_source = :entry_source,
                    updated_at = :updated_at
                WHERE entry_id = :entry_id
                """,
                values | {"entry_id": target_entry_id},
            )
            return target_entry_id

    def upsert_deck(self, record: DeckRecord) -> None:
        values = asdict(record)
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO decks (
                    deck_site_id,
                    entry_id,
                    tournament_site_id,
                    deck_slug,
                    deck_name,
                    deck_url,
                    placement_label,
                    placement_sort_value,
                    tournament_participants_count,
                    player_name,
                    archetype_text,
                    author_name,
                    uploaded_at,
                    tcg_price_usd,
                    primer,
                    fetched_at,
                    last_run_id
                ) VALUES (
                    :deck_site_id,
                    :entry_id,
                    :tournament_site_id,
                    :deck_slug,
                    :deck_name,
                    :deck_url,
                    :placement_label,
                    :placement_sort_value,
                    :tournament_participants_count,
                    :player_name,
                    :archetype_text,
                    :author_name,
                    :uploaded_at,
                    :tcg_price_usd,
                    :primer,
                    :fetched_at,
                    :last_run_id
                )
                ON CONFLICT(deck_site_id) DO UPDATE SET
                    entry_id = excluded.entry_id,
                    tournament_site_id = excluded.tournament_site_id,
                    deck_slug = excluded.deck_slug,
                    deck_name = excluded.deck_name,
                    deck_url = excluded.deck_url,
                    placement_label = excluded.placement_label,
                    placement_sort_value = excluded.placement_sort_value,
                    tournament_participants_count = excluded.tournament_participants_count,
                    player_name = excluded.player_name,
                    archetype_text = excluded.archetype_text,
                    author_name = excluded.author_name,
                    uploaded_at = excluded.uploaded_at,
                    tcg_price_usd = excluded.tcg_price_usd,
                    primer = excluded.primer,
                    fetched_at = excluded.fetched_at,
                    last_run_id = excluded.last_run_id
                """,
                values,
            )
            connection.execute(
                """
                UPDATE tournament_entries
                SET deck_site_id = :deck_site_id,
                    deck_url = :deck_url,
                    updated_at = :fetched_at
                WHERE entry_id = :entry_id
                """,
                {
                    "deck_site_id": record.deck_site_id,
                    "deck_url": record.deck_url,
                    "fetched_at": record.fetched_at,
                    "entry_id": record.entry_id,
                },
            )

    def upsert_cards(self, records: Iterable[CardRecord]) -> None:
        payload = [asdict(record) for record in records]
        if not payload:
            return
        with self.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO cards (
                    card_passcode,
                    canonical_name,
                    card_archetype,
                    card_type,
                    card_race,
                    card_attribute,
                    frame_type,
                    effect_text,
                    cardmarket_price_eur,
                    image_url_small,
                    last_enriched_at,
                    metadata_version
                )
                VALUES (
                    :card_passcode,
                    :canonical_name,
                    :card_archetype,
                    :card_type,
                    :card_race,
                    :card_attribute,
                    :frame_type,
                    :effect_text,
                    :cardmarket_price_eur,
                    :image_url_small,
                    :last_enriched_at,
                    :metadata_version
                )
                ON CONFLICT(card_passcode) DO UPDATE SET
                    canonical_name = excluded.canonical_name,
                    card_archetype = COALESCE(excluded.card_archetype, cards.card_archetype),
                    card_type = COALESCE(excluded.card_type, cards.card_type),
                    card_race = COALESCE(excluded.card_race, cards.card_race),
                    card_attribute = COALESCE(excluded.card_attribute, cards.card_attribute),
                    frame_type = COALESCE(excluded.frame_type, cards.frame_type),
                    effect_text = CASE
                        WHEN excluded.effect_text IS NOT NULL THEN excluded.effect_text
                        WHEN cards.effect_text IS NOT NULL AND LOWER(TRIM(cards.effect_text)) IN ('none', 'null', 'n/a', 'na') THEN NULL
                        ELSE cards.effect_text
                    END,
                    cardmarket_price_eur = COALESCE(excluded.cardmarket_price_eur, cards.cardmarket_price_eur),
                    image_url_small = COALESCE(excluded.image_url_small, cards.image_url_small),
                    last_enriched_at = COALESCE(excluded.last_enriched_at, cards.last_enriched_at),
                    metadata_version = CASE
                        WHEN excluded.metadata_version > cards.metadata_version THEN excluded.metadata_version
                        ELSE cards.metadata_version
                    END
                """,
                payload,
            )

    def list_cards_missing_metadata(
        self, limit: int | None = None
    ) -> list[sqlite3.Row]:
        query = """
            SELECT
                card_passcode,
                canonical_name
            FROM cards
            WHERE COALESCE(metadata_version, 0) < ?
            ORDER BY card_passcode ASC
        """
        parameters: Sequence[Any] | None = (CARD_METADATA_VERSION,)
        if limit is not None:
            query += " LIMIT ?"
            parameters = (CARD_METADATA_VERSION, limit)
        return self.fetch_all(query, parameters)

    def replace_deck_cards(
        self, deck_site_id: int, records: Iterable[DeckCardRecord]
    ) -> None:
        payload = [asdict(record) for record in records]
        mismatched = [row for row in payload if row["deck_site_id"] != deck_site_id]
        if mismatched:
            raise ValueError("All deck card records must target the same deck_site_id")

        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM deck_cards WHERE deck_site_id = ?", (deck_site_id,)
            )
            if payload:
                connection.executemany(
                    """
                    INSERT INTO deck_cards (
                        deck_site_id,
                        section,
                        card_passcode,
                        card_name,
                        quantity
                    ) VALUES (
                        :deck_site_id,
                        :section,
                        :card_passcode,
                        :card_name,
                        :quantity
                    )
                    """,
                    payload,
                )

    def record_skipped_source(self, record: SkippedSourceRecord) -> int:
        values = asdict(record)
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO skipped_sources (
                    run_id,
                    source_url,
                    source_type,
                    skip_reason,
                    matched_text,
                    seen_at
                ) VALUES (
                    :run_id,
                    :source_url,
                    :source_type,
                    :skip_reason,
                    :matched_text,
                    :seen_at
                )
                """,
                values,
            )
            return int(cursor.lastrowid)

    def list_tables_and_views(self) -> list[str]:
        rows = self.fetch_all("""
            SELECT name
            FROM sqlite_master
            WHERE type IN ('table', 'view')
              AND name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """)
        return [str(row["name"]) for row in rows]

    def _ensure_cards_metadata_columns(self, connection: sqlite3.Connection) -> None:
        existing_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(cards)").fetchall()
        }
        required_columns = {
            "card_archetype": "TEXT",
            "card_type": "TEXT",
            "card_race": "TEXT",
            "card_attribute": "TEXT",
            "frame_type": "TEXT",
            "effect_text": "TEXT",
            "cardmarket_price_eur": "REAL",
            "image_url_small": "TEXT",
        }
        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE cards ADD COLUMN {column_name} {column_type}"
                )
        if "metadata_version" not in existing_columns:
            connection.execute(
                "ALTER TABLE cards ADD COLUMN metadata_version INTEGER NOT NULL DEFAULT 0"
            )
