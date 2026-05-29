from __future__ import annotations

import streamlit as st

from ygo_crawler.dashboard_filters import render_dashboard_date_filter
from ygo_crawler.dashboard_queries import DashboardRepository, resolve_dashboard_db_path


def _drop_columns(rows: list[dict[str, object]], columns: set[str]) -> list[dict[str, object]]:
    return [{key: value for key, value in row.items() if key not in columns} for row in rows]


st.set_page_config(page_title="YGOPRODeck Dashboard", layout="wide")

database_path = resolve_dashboard_db_path()
repository = DashboardRepository(database_path)

st.title("YGOPRODeck TCG Dashboard")

status_message = repository.status_message()
if status_message is not None:
    st.warning(status_message)
    st.stop()

start_date, end_date = render_dashboard_date_filter(repository)

kpis = repository.get_kpis(start_date, end_date)
database_summary = repository.get_database_summary(start_date, end_date)
metric_col_1, metric_col_2 = st.columns(2)
metric_col_1.metric("Gecrawlte Decks", kpis.crawled_decks)
metric_col_2.metric("Unterschiedliche Decknamen", kpis.distinct_deck_names)

st.subheader("Häufigste Decknamen")
aggregate_rows = repository.list_deck_name_aggregates(limit=15, start_date=start_date, end_date=end_date)
if aggregate_rows:
    st.dataframe(
        [
            {
                "Deckname": row["deck_name"],
                "Turniere": row["tournament_count"],
                "Ø Platzierung": row["average_placement"],
                "Beste Platzierung": row["best_placement"],
                "Ø Main Deck": row["average_main_card_total"],
                "Ø Engine Main": row["average_engine_card_total"],
                "Ø Handtraps Main": row["average_handtrap_card_total"],
                "Ø Boardbreaker Main": row["average_boardbreaker_card_total"],
                "Ø Cardmarket Summe €": row["average_cardmarket_deck_price_eur"],
            }
            for row in aggregate_rows
        ],
        hide_index=True,
        width="stretch",
    )

st.subheader("Zuletzt geladene Decks")
deck_rows = repository.list_deck_summaries(limit=15, start_date=start_date, end_date=end_date)
if not deck_rows:
    st.warning("Aktuell sind noch keine Decks gespeichert. Die Datenbank enthaelt zwar Crawl-Daten, aber keine persistierten Deckseiten.")

    info_col_1, info_col_2, info_col_3, info_col_4 = st.columns(4)
    info_col_1.metric("Turniere", database_summary.tournaments)
    info_col_2.metric("Entries", database_summary.entries)
    info_col_3.metric("Skip-Quellen", database_summary.skipped_sources)
    info_col_4.metric("Deck-Karten", database_summary.deck_cards)

    tournaments = repository.list_tournaments(limit=10, start_date=start_date, end_date=end_date)
    if tournaments:
        st.markdown("**Gespeicherte Turniere**")
        st.dataframe(_drop_columns(tournaments, {"country"}), hide_index=True, width="stretch")

    skip_summary = repository.list_skip_reason_summary()
    if skip_summary:
        st.markdown("**Warum keine Decks gespeichert wurden**")
        st.dataframe(skip_summary, hide_index=True, width="stretch")

    skipped_sources = repository.list_skipped_sources(limit=20)
    if skipped_sources:
        with st.expander("Zuletzt verworfene Quellen anzeigen"):
            st.dataframe(skipped_sources, hide_index=True, width="stretch")
else:
    st.dataframe(
        [
            {
                "Deckname": row["deck_name"],
                "Spieler": row["player_name"],
                "Platzierung": row["placement"],
                "Teilnehmer": row["participants_count"],
                "Archetyp": row["archetype_text"],
                "Turnier": row["tournament_name"],
                "Datum": row["tournament_date"],
                "Main": row["main_card_total"],
                "Extra": row["extra_card_total"],
                "Side": row["side_card_total"],
                "Cardmarket Summe €": row["cardmarket_deck_price_eur"],
                "Deck URL": row["deck_url"],
            }
            for row in deck_rows
        ],
        hide_index=True,
        width="stretch",
    )