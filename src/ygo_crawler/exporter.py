from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from .config import DEFAULT_DATABASE_PATH


_DECK_CARDS_EXPORT_SQL = """
    SELECT
        t.tournament_date,
        t.tournament_name,
        t.participants_count,
        d.deck_name,
        d.deck_site_id,
        d.placement_label AS placement,
        d.placement_sort_value,
        d.player_name,
        dc.section,
        dc.card_passcode,
        COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT)) AS card_name,
        dc.quantity,
        c.card_archetype,
        c.card_type,
        c.card_race,
        c.card_attribute,
        c.frame_type
    FROM deck_cards dc
    JOIN decks d ON d.deck_site_id = dc.deck_site_id
    JOIN tournaments t ON t.tournament_site_id = d.tournament_site_id
    LEFT JOIN cards c ON c.card_passcode = dc.card_passcode
    ORDER BY t.tournament_date DESC, d.deck_name ASC, dc.section ASC, card_name ASC
"""


def export_deck_cards_csv(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    output_path: str | Path = Path("exports/deck_cards_flat.csv"),
) -> Path:
    source_path = Path(database_path)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(source_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(_DECK_CARDS_EXPORT_SQL).fetchall()

    with destination.open("w", encoding="utf-8", newline="") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))

    return destination
