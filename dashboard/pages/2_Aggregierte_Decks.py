from __future__ import annotations

from pathlib import Path
from statistics import median

import streamlit as st

from ygo_crawler.dashboard_cache import load_aggregate_plot_data, load_deck_name_aggregates_extended
from ygo_crawler.dashboard_filters import render_dashboard_date_filter
from ygo_crawler.dashboard_queries import DashboardRepository, resolve_dashboard_db_path


DECK_NAME_STATE_KEY = "decklisten_selected_deck_name"
DECK_INSTANCE_STATE_KEY = "decklisten_selected_deck_id"
DETAIL_NAVIGATION_STATE_KEY = "aggregate_detail_navigation_deck_name"
QUERY_PARAM_DECK_NAME = "deck_name"
DECKLIST_PAGE_PATH = Path(__file__).with_name("1_Decklisten.py")


def _format_cardmarket_range(row: dict[str, object]) -> str:
    p25_value = row.get("cardmarket_deck_price_p25_eur")
    p75_value = row.get("cardmarket_deck_price_p75_eur")
    if p25_value is None or p75_value is None:
        return "-"
    return f"EUR {float(p25_value):.2f} - EUR {float(p75_value):.2f}"


def _latest_trend_delta(series: list[float]) -> float | None:
    if len(series) < 2:
        return None
    return round(float(series[-1]) - float(series[-2]), 2)


def _numeric_median(rows: list[dict[str, object]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    if not values:
        return None
    return float(median(values))


def _open_decklist_detail(deck_name: str) -> None:
    st.session_state[DECK_NAME_STATE_KEY] = deck_name
    st.session_state.pop(DECK_INSTANCE_STATE_KEY, None)
    st.switch_page(DECKLIST_PAGE_PATH, query_params={QUERY_PARAM_DECK_NAME: deck_name})


def _build_aggregate_table_rows(
    rows: list[dict[str, object]],
    *,
    show_extended_metrics: bool,
    trend_series_by_deck_name: dict[str, dict[str, list[float]]] | None = None,
) -> list[dict[str, object]]:
    table_rows: list[dict[str, object]] = []
    for row in rows:
        deck_name = str(row["deck_name"])
        trend_series = trend_series_by_deck_name.get(deck_name, {}) if trend_series_by_deck_name is not None else {}
        meta_trend = trend_series.get("meta_share_pct", [])
        performance_trend = trend_series.get("median_placement_percentile", [])
        price_trend = trend_series.get("median_cardmarket_deck_price_eur", [])
        table_row = {
            "Deckname": deck_name,
            "Meta-Trend": meta_trend,
            "Meta Δ MoM": _latest_trend_delta(meta_trend),
            "Performance-Trend": performance_trend,
            "Performance Δ MoM": _latest_trend_delta(performance_trend),
            "Preis Δ MoM": _latest_trend_delta(price_trend),
            "Meta-Anteil %": row["meta_share_pct"],
            "Decks absolut": row["deck_count"],
            "Turnierabdeckung %": row["tournament_coverage_pct"],
            "Spielerdiversitaet %": round(float(row["player_diversity_ratio"]) * 100.0, 2),
            "Ø Platzierungs-Perzentil": row["average_placement_percentile"],
            "Median Platzierungs-Perzentil": row["median_placement_percentile"],
            "Top-25 %": row["top_25_finish_rate_pct"],
            "Ø Main Deck": row["average_main_card_total"],
            "Ø Engine Main": row["average_engine_card_total"],
            "Ø Handtraps Main": row["average_handtrap_card_total"],
            "Ø Boardbreaker Main": row["average_boardbreaker_card_total"],
            "Ø Handtraps Side %": row["average_side_handtrap_share_pct"],
            "Ø Boardbreaker Side %": row["average_side_boardbreaker_share_pct"],
            "Ø Weitere Non-Engine Side %": row["average_side_non_engine_other_share_pct"],
            "Median Cardmarket €": row["median_cardmarket_deck_price_eur"],
            "P25-P75 Cardmarket €": _format_cardmarket_range(row),
        }
        if show_extended_metrics:
            table_row.update(
                {
                    "Preis-Trend": price_trend,
                    "Turniere": row["tournament_count"],
                    "Spieler": row["player_count"],
                    "Ø Platzierung": row["average_placement"],
                    "Ø Teilnehmer": row["average_participants_count"],
                    "Ø Side Non-Engine %": row["average_side_non_engine_share_pct"],
                    "Perzentil-IQR": row["placement_percentile_iqr"],
                    "Preis-IQR €": row["cardmarket_deck_price_iqr_eur"],
                    "Erstes Auftreten": row["first_seen_date"],
                    "Letztes Auftreten": row["last_seen_date"],
                    "Resultate letzte 30 Tage %": row["recent_30d_result_share_pct"],
                }
            )
        table_rows.append(table_row)
    return table_rows


def _aggregate_column_config() -> dict[str, object]:
    return {
        "Meta-Trend": st.column_config.LineChartColumn(
            "Meta-Trend",
            help="Monatlicher Meta-Anteil des Decknamens im gefilterten Zeitraum.",
            y_min=0.0,
            y_max=100.0,
        ),
        "Meta Δ MoM": st.column_config.NumberColumn(
            "Meta Δ MoM",
            help="Letzter verfuegbarer Monat minus vorheriger verfuegbarer Monat beim Meta-Anteil.",
            format="%+.2f",
        ),
        "Performance-Trend": st.column_config.LineChartColumn(
            "Performance-Trend",
            help="Monatliches Median Platzierungs-Perzentil des Decknamens.",
            y_min=0.0,
            y_max=100.0,
        ),
        "Performance Δ MoM": st.column_config.NumberColumn(
            "Performance Δ MoM",
            help="Letzter verfuegbarer Monat minus vorheriger verfuegbarer Monat beim Median Platzierungs-Perzentil.",
            format="%+.2f",
        ),
        "Preis Δ MoM": st.column_config.NumberColumn(
            "Preis Δ MoM",
            help="Letzter verfuegbarer Monat minus vorheriger verfuegbarer Monat beim Median Cardmarket-Preis.",
            format="%+.2f",
        ),
        "Meta-Anteil %": st.column_config.NumberColumn("Meta-Anteil %", format="%.2f"),
        "Decks absolut": st.column_config.NumberColumn("Decks absolut", format="%d"),
        "Turnierabdeckung %": st.column_config.NumberColumn("Turnierabdeckung %", format="%.2f"),
        "Spielerdiversitaet %": st.column_config.NumberColumn("Spielerdiversitaet %", format="%.2f"),
        "Ø Platzierungs-Perzentil": st.column_config.NumberColumn("Ø Platzierungs-Perzentil", format="%.2f"),
        "Median Platzierungs-Perzentil": st.column_config.NumberColumn(
            "Median Platzierungs-Perzentil",
            format="%.2f",
        ),
        "Top-25 %": st.column_config.NumberColumn("Top-25 %", format="%.2f"),
        "Ø Main Deck": st.column_config.NumberColumn("Ø Main Deck", format="%.2f"),
        "Ø Engine Main": st.column_config.NumberColumn("Ø Engine Main", format="%.2f"),
        "Ø Handtraps Main": st.column_config.NumberColumn("Ø Handtraps Main", format="%.2f"),
        "Ø Boardbreaker Main": st.column_config.NumberColumn("Ø Boardbreaker Main", format="%.2f"),
        "Ø Handtraps Side %": st.column_config.NumberColumn("Ø Handtraps Side %", format="%.2f"),
        "Ø Boardbreaker Side %": st.column_config.NumberColumn("Ø Boardbreaker Side %", format="%.2f"),
        "Ø Weitere Non-Engine Side %": st.column_config.NumberColumn(
            "Ø Weitere Non-Engine Side %",
            format="%.2f",
        ),
        "Median Cardmarket €": st.column_config.NumberColumn("Median Cardmarket €", format="%.2f"),
        "Turniere": st.column_config.NumberColumn("Turniere", format="%d"),
        "Spieler": st.column_config.NumberColumn("Spieler", format="%d"),
        "Ø Platzierung": st.column_config.NumberColumn("Ø Platzierung", format="%.2f"),
        "Ø Teilnehmer": st.column_config.NumberColumn("Ø Teilnehmer", format="%.1f"),
        "Preis-Trend": st.column_config.LineChartColumn(
            "Preis-Trend",
            help="Monatlicher Median der Cardmarket-Deckkosten.",
            y_min=0.0,
        ),
        "Ø Side Non-Engine %": st.column_config.NumberColumn("Ø Side Non-Engine %", format="%.2f"),
        "Perzentil-IQR": st.column_config.NumberColumn("Perzentil-IQR", format="%.2f"),
        "Preis-IQR €": st.column_config.NumberColumn("Preis-IQR €", format="%.2f"),
        "Resultate letzte 30 Tage %": st.column_config.NumberColumn("Resultate letzte 30 Tage %", format="%.2f"),
    }


def _build_trend_series_by_deck_name(rows: list[dict[str, object]]) -> dict[str, dict[str, list[float]]]:
    trend_series_by_deck_name: dict[str, dict[str, list[float]]] = {}
    for row in sorted(rows, key=lambda item: (str(item["deck_name"]), str(item["month_start"]))):
        deck_name = str(row["deck_name"])
        deck_series = trend_series_by_deck_name.setdefault(
            deck_name,
            {
                "meta_share_pct": [],
                "median_placement_percentile": [],
                "median_cardmarket_deck_price_eur": [],
            },
        )

        meta_share_pct = row.get("meta_share_pct")
        if meta_share_pct is not None:
            deck_series["meta_share_pct"].append(float(meta_share_pct))

        median_placement_percentile = row.get("median_placement_percentile")
        if median_placement_percentile is not None:
            deck_series["median_placement_percentile"].append(float(median_placement_percentile))

        median_cardmarket_deck_price_eur = row.get("median_cardmarket_deck_price_eur")
        if median_cardmarket_deck_price_eur is not None:
            deck_series["median_cardmarket_deck_price_eur"].append(float(median_cardmarket_deck_price_eur))

    return trend_series_by_deck_name


def _value_efficiency_score(row: dict[str, object]) -> float | None:
    median_placement_percentile = row.get("median_placement_percentile")
    median_cardmarket_deck_price_eur = row.get("median_cardmarket_deck_price_eur")
    if median_placement_percentile is None or median_cardmarket_deck_price_eur is None:
        return None
    normalized_price = float(median_cardmarket_deck_price_eur)
    if normalized_price <= 0:
        return None
    return round(float(median_placement_percentile) * 100.0 / normalized_price, 2)


def _sort_aggregate_rows(rows: list[dict[str, object]], ranking_label: str) -> list[dict[str, object]]:
    ranking_field_by_label = {
        "Meta-Anteil": "meta_share_pct",
        "Median Platzierungs-Perzentil": "median_placement_percentile",
        "Top-25 %": "top_25_finish_rate_pct",
        "Median Cardmarket €": "median_cardmarket_deck_price_eur",
        "Resultate letzte 30 Tage": "recent_30d_result_share_pct",
    }
    if ranking_label == "Preis-Leistung":
        return sorted(
            rows,
            key=lambda row: (
                -(_value_efficiency_score(row) or -1.0),
                -float(row.get("meta_share_pct") or 0.0),
                str(row["deck_name"]),
            ),
        )

    ranking_field = ranking_field_by_label.get(ranking_label, "meta_share_pct")
    return sorted(
        rows,
        key=lambda row: (
            -float(row.get(ranking_field) or 0.0),
            -int(row.get("deck_count") or 0),
            str(row["deck_name"]),
        ),
    )


def _select_highlight_rows(rows: list[dict[str, object]]) -> dict[str, dict[str, object] | None]:
    most_played = max(
        rows,
        key=lambda row: (
            int(row.get("deck_count") or 0),
            float(row.get("meta_share_pct") or 0.0),
            str(row["deck_name"]),
        ),
        default=None,
    )
    best_median_performance = max(
        rows,
        key=lambda row: (
            float(row.get("median_placement_percentile") or -1.0),
            int(row.get("deck_count") or 0),
            str(row["deck_name"]),
        ),
        default=None,
    )
    best_value = max(
        rows,
        key=lambda row: (
            _value_efficiency_score(row) or -1.0,
            int(row.get("deck_count") or 0),
            str(row["deck_name"]),
        ),
        default=None,
    )
    return {
        "most_played": most_played,
        "best_median_performance": best_median_performance,
        "best_value": best_value,
    }


def _render_highlight_card(
    column: st.delta_generator.DeltaGenerator,
    *,
    title: str,
    row: dict[str, object] | None,
    delta_text: str,
    supporting_text: str,
) -> None:
    with column.container(border=True):
        if row is None:
            st.metric(title, "-", delta="-", border=True)
            st.caption("Keine Daten verfuegbar.")
            return
        st.metric(title, str(row["deck_name"]), delta=delta_text, delta_color="off", border=True)
        st.caption(supporting_text)


def _profile_component_color(component_type: str, component_index: int) -> str:
    if component_type == "non_engine_handtrap":
        return "#E76F51"
    if component_type == "non_engine_boardbreaker":
        return "#F4A261"
    if component_type == "non_engine_other":
        return "#E9C46A"
    if component_type == "rest_engine":
        return "#8E9AAF"

    engine_palette = ["#1D3557", "#2A9D8F", "#457B9D", "#6D597A", "#264653"]
    return engine_palette[component_index % len(engine_palette)]


def _render_popularity_performance_scatter(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info("Fuer die aktuellen Filter konnten keine Popularitaet-versus-Performance-Daten berechnet werden.")
        return

    st.vega_lite_chart(
        {
            "data": {"values": rows},
            "height": 360,
            "mark": {"type": "circle", "tooltip": True, "opacity": 0.8},
            "encoding": {
                "x": {
                    "field": "meta_share_pct",
                    "type": "quantitative",
                    "axis": {"title": "Meta-Anteil (%)"},
                },
                "y": {
                    "field": "average_placement_percentile",
                    "type": "quantitative",
                    "axis": {"title": "Ø Platzierungs-Perzentil"},
                    "scale": {"zero": False},
                },
                "size": {
                    "field": "deck_count",
                    "type": "quantitative",
                    "legend": {"title": "Decks absolut"},
                    "scale": {"range": [80, 1600]},
                },
                "color": {
                    "field": "median_cardmarket_deck_price_eur",
                    "type": "quantitative",
                    "legend": {"title": "Median Cardmarket EUR"},
                    "scale": {"range": ["#A8DADC", "#1D3557"]},
                },
                "tooltip": [
                    {"field": "deck_name", "type": "nominal", "title": "Deckname"},
                    {"field": "meta_share_pct", "type": "quantitative", "format": ".2f", "title": "Meta-Anteil %"},
                    {"field": "average_placement_percentile", "type": "quantitative", "format": ".2f", "title": "Ø Platzierungs-Perzentil"},
                    {"field": "median_placement_percentile", "type": "quantitative", "format": ".2f", "title": "Median Platzierungs-Perzentil"},
                    {"field": "top_25_finish_rate_pct", "type": "quantitative", "format": ".2f", "title": "Top-25 %"},
                    {"field": "deck_count", "type": "quantitative", "format": ".0f", "title": "Decks absolut"},
                    {"field": "tournament_coverage_pct", "type": "quantitative", "format": ".2f", "title": "Turnierabdeckung %"},
                    {"field": "median_cardmarket_deck_price_eur", "type": "quantitative", "format": ".2f", "title": "Median Cardmarket EUR"},
                ],
            },
        },
        width="stretch",
    )


def _render_cost_performance_scatter(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info("Fuer die aktuellen Filter konnten keine Kosten-versus-Performance-Daten berechnet werden.")
        return

    st.vega_lite_chart(
        {
            "data": {"values": rows},
            "height": 360,
            "mark": {"type": "circle", "tooltip": True, "opacity": 0.8},
            "encoding": {
                "x": {
                    "field": "median_cardmarket_deck_price_eur",
                    "type": "quantitative",
                    "axis": {"title": "Median Cardmarket EUR"},
                },
                "y": {
                    "field": "average_placement_percentile",
                    "type": "quantitative",
                    "axis": {"title": "Ø Platzierungs-Perzentil"},
                    "scale": {"zero": False},
                },
                "size": {
                    "field": "meta_share_pct",
                    "type": "quantitative",
                    "legend": {"title": "Meta-Anteil %"},
                    "scale": {"range": [80, 1400]},
                },
                "color": {
                    "field": "meta_share_pct",
                    "type": "quantitative",
                    "legend": {"title": "Meta-Anteil %"},
                    "scale": {"range": ["#D8F3DC", "#1B4332"]},
                },
                "tooltip": [
                    {"field": "deck_name", "type": "nominal", "title": "Deckname"},
                    {"field": "median_cardmarket_deck_price_eur", "type": "quantitative", "format": ".2f", "title": "Median Cardmarket EUR"},
                    {"field": "cardmarket_deck_price_p25_eur", "type": "quantitative", "format": ".2f", "title": "P25 EUR"},
                    {"field": "cardmarket_deck_price_p75_eur", "type": "quantitative", "format": ".2f", "title": "P75 EUR"},
                    {"field": "average_placement_percentile", "type": "quantitative", "format": ".2f", "title": "Ø Platzierungs-Perzentil"},
                    {"field": "top_25_finish_rate_pct", "type": "quantitative", "format": ".2f", "title": "Top-25 %"},
                    {"field": "meta_share_pct", "type": "quantitative", "format": ".2f", "title": "Meta-Anteil %"},
                    {"field": "deck_count", "type": "quantitative", "format": ".0f", "title": "Decks absolut"},
                ],
            },
        },
        width="stretch",
    )


def _render_deck_profile_chart(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info("Fuer die aktuellen Filter konnten keine Profil-Daten berechnet werden.")
        return

    chart_rows: list[dict[str, object]] = []
    domain: list[str] = []
    color_range: list[str] = []
    seen_components: set[str] = set()
    engine_index = 0
    section_labels = {"main": "Main Deck", "side": "Side Deck"}

    for row in sorted(rows, key=lambda item: (int(item["type_rank"]), str(item["component_name"]))):
        component_name = str(row["component_name"])
        component_type = str(row["component_type"])
        if component_name not in seen_components:
            domain.append(component_name)
            color_range.append(_profile_component_color(component_type, engine_index))
            seen_components.add(component_name)
            if component_type == "main_engine":
                engine_index += 1

    for row in rows:
        section_label = section_labels.get(str(row["section"]), str(row["section"]))
        chart_rows.append(
            {
                "Profil": f"{row['deck_name']} | {section_label}",
                "Deckname": str(row["deck_name"]),
                "Deckbereich": section_label,
                "Baustein": str(row["component_name"]),
                "Anteil %": float(row["share_pct"]),
                "Ø Kopien / Gruppendeck": float(row["average_copies_per_group_deck"]),
                "Deck-Rang": int(row["deck_rank"]),
                "Sortierung": int(row["type_rank"]),
                "Meta-Anteil %": float(row["meta_share_pct"]),
                "Ø Platzierungs-Perzentil": row["average_placement_percentile"],
                "Median Cardmarket EUR": row["median_cardmarket_deck_price_eur"],
            }
        )

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": {"step": 28},
            "mark": {"type": "bar", "tooltip": True},
            "encoding": {
                "y": {
                    "field": "Profil",
                    "type": "nominal",
                    "axis": {"title": None, "labelAngle": 0},
                    "sort": {"field": "Deck-Rang", "op": "min", "order": "ascending"},
                },
                "x": {
                    "field": "Anteil %",
                    "type": "quantitative",
                    "stack": "zero",
                    "axis": {"title": "Anteil am durchschnittlichen Deckbereich (%)"},
                },
                "color": {
                    "field": "Baustein",
                    "type": "nominal",
                    "scale": {"domain": domain, "range": color_range},
                    "legend": {"title": None, "orient": "bottom"},
                },
                "order": {"field": "Sortierung", "type": "quantitative"},
                "tooltip": [
                    {"field": "Deckname", "type": "nominal"},
                    {"field": "Deckbereich", "type": "nominal"},
                    {"field": "Baustein", "type": "nominal"},
                    {"field": "Anteil %", "type": "quantitative", "format": ".2f"},
                    {"field": "Ø Kopien / Gruppendeck", "type": "quantitative", "format": ".2f"},
                    {"field": "Meta-Anteil %", "type": "quantitative", "format": ".2f"},
                    {"field": "Ø Platzierungs-Perzentil", "type": "quantitative", "format": ".2f"},
                    {"field": "Median Cardmarket EUR", "type": "quantitative", "format": ".2f"},
                ],
            },
        },
        width="stretch",
    )


def _trend_color_range(deck_count: int) -> list[str]:
    palette = ["#1D3557", "#2A9D8F", "#E76F51", "#F4A261", "#6D597A", "#457B9D", "#264653", "#E9C46A"]
    if deck_count <= len(palette):
        return palette[:deck_count]
    return [palette[index % len(palette)] for index in range(deck_count)]


def _render_deck_name_meta_heatmap(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info("Fuer die aktuellen Filter konnten keine monatlichen Meta-Anteile berechnet werden.")
        return

    chart_rows: list[dict[str, object]] = []
    deck_domain: list[str] = []
    for row in sorted(rows, key=lambda item: (int(item["deck_rank"]), str(item["deck_name"]))):
        deck_name = str(row["deck_name"])
        if deck_name not in deck_domain:
            deck_domain.append(deck_name)

    for row in rows:
        meta_share_pct = row.get("meta_share_pct")
        if meta_share_pct is None:
            continue
        chart_rows.append(
            {
                "Monat": str(row["month_start"])[:7],
                "Deckname": str(row["deck_name"]),
                "Deck-Rang": int(row["deck_rank"]),
                "Meta-Anteil %": float(meta_share_pct),
                "Decks": int(row["deck_count"]),
                "Monatsdecks": int(row["month_total_deck_count"]),
                "Median Platzierungs-Perzentil": row.get("median_placement_percentile"),
                "Median Cardmarket EUR": row.get("median_cardmarket_deck_price_eur"),
            }
        )

    if not chart_rows:
        st.info("Fuer die aktuellen Filter konnten keine monatlichen Meta-Anteile berechnet werden.")
        return

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": {"step": 34},
            "mark": {"type": "rect", "tooltip": True},
            "encoding": {
                "x": {
                    "field": "Monat",
                    "type": "ordinal",
                    "axis": {"title": "Monat", "labelAngle": -35},
                },
                "y": {
                    "field": "Deckname",
                    "type": "nominal",
                    "sort": deck_domain,
                    "axis": {"title": None},
                },
                "color": {
                    "field": "Meta-Anteil %",
                    "type": "quantitative",
                    "legend": {"title": "Meta-Anteil %"},
                    "scale": {"range": ["#E0FBFC", "#1D3557"]},
                },
                "tooltip": [
                    {"field": "Deckname", "type": "nominal"},
                    {"field": "Monat", "type": "nominal"},
                    {"field": "Meta-Anteil %", "type": "quantitative", "format": ".2f"},
                    {"field": "Decks", "type": "quantitative", "format": ".0f", "title": "Decks des Decknamens"},
                    {"field": "Monatsdecks", "type": "quantitative", "format": ".0f", "title": "Decks im Monat gesamt"},
                    {
                        "field": "Median Platzierungs-Perzentil",
                        "type": "quantitative",
                        "format": ".2f",
                    },
                    {"field": "Median Cardmarket EUR", "type": "quantitative", "format": ".2f"},
                ],
            },
        },
        width="stretch",
    )


def _render_deck_name_performance_drift(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info("Fuer die aktuellen Filter konnten keine monatlichen Performance-Werte berechnet werden.")
        return

    deck_domain: list[str] = []
    for row in sorted(rows, key=lambda item: (int(item["deck_rank"]), str(item["deck_name"]))):
        deck_name = str(row["deck_name"])
        if deck_name not in deck_domain:
            deck_domain.append(deck_name)

    chart_rows = [
        {
            "Monat": str(row["month_start"]),
            "Deckname": str(row["deck_name"]),
            "Deck-Rang": int(row["deck_rank"]),
            "Median Platzierungs-Perzentil": float(row["median_placement_percentile"]),
            "Perzentil-IQR": row.get("placement_percentile_iqr"),
            "Meta-Anteil %": row.get("meta_share_pct"),
            "Decks": int(row["deck_count"]),
            "Median Cardmarket EUR": row.get("median_cardmarket_deck_price_eur"),
        }
        for row in rows
        if row.get("median_placement_percentile") is not None
    ]

    if not chart_rows:
        st.info("Fuer die aktuellen Filter konnten keine monatlichen Performance-Werte berechnet werden.")
        return

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": 360,
            "mark": {"type": "line", "point": True, "tooltip": True},
            "encoding": {
                "x": {
                    "field": "Monat",
                    "type": "temporal",
                    "axis": {"title": "Monat", "format": "%Y-%m"},
                },
                "y": {
                    "field": "Median Platzierungs-Perzentil",
                    "type": "quantitative",
                    "axis": {"title": "Median Platzierungs-Perzentil"},
                    "scale": {"zero": False},
                },
                "color": {
                    "field": "Deckname",
                    "type": "nominal",
                    "scale": {"domain": deck_domain, "range": _trend_color_range(len(deck_domain))},
                    "legend": {"title": None, "orient": "bottom"},
                },
                "tooltip": [
                    {"field": "Deckname", "type": "nominal"},
                    {"field": "Monat", "type": "temporal", "format": "%Y-%m"},
                    {"field": "Median Platzierungs-Perzentil", "type": "quantitative", "format": ".2f"},
                    {"field": "Perzentil-IQR", "type": "quantitative", "format": ".2f"},
                    {"field": "Meta-Anteil %", "type": "quantitative", "format": ".2f"},
                    {"field": "Decks", "type": "quantitative", "format": ".0f"},
                    {"field": "Median Cardmarket EUR", "type": "quantitative", "format": ".2f"},
                ],
            },
        },
        width="stretch",
    )


def _render_deck_name_price_drift(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info("Fuer die aktuellen Filter konnten keine monatlichen Preiswerte berechnet werden.")
        return

    deck_domain: list[str] = []
    for row in sorted(rows, key=lambda item: (int(item["deck_rank"]), str(item["deck_name"]))):
        deck_name = str(row["deck_name"])
        if deck_name not in deck_domain:
            deck_domain.append(deck_name)

    chart_rows = [
        {
            "Monat": str(row["month_start"]),
            "Deckname": str(row["deck_name"]),
            "Deck-Rang": int(row["deck_rank"]),
            "Median Cardmarket EUR": float(row["median_cardmarket_deck_price_eur"]),
            "Preis-IQR EUR": row.get("cardmarket_deck_price_iqr_eur"),
            "Meta-Anteil %": row.get("meta_share_pct"),
            "Median Platzierungs-Perzentil": row.get("median_placement_percentile"),
            "Decks": int(row["deck_count"]),
        }
        for row in rows
        if row.get("median_cardmarket_deck_price_eur") is not None
    ]

    if not chart_rows:
        st.info("Fuer die aktuellen Filter konnten keine monatlichen Preiswerte berechnet werden.")
        return

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": 340,
            "mark": {"type": "line", "point": True, "tooltip": True},
            "encoding": {
                "x": {
                    "field": "Monat",
                    "type": "temporal",
                    "axis": {"title": "Monat", "format": "%Y-%m"},
                },
                "y": {
                    "field": "Median Cardmarket EUR",
                    "type": "quantitative",
                    "axis": {"title": "Median Cardmarket EUR"},
                    "scale": {"zero": False},
                },
                "color": {
                    "field": "Deckname",
                    "type": "nominal",
                    "scale": {"domain": deck_domain, "range": _trend_color_range(len(deck_domain))},
                    "legend": {"title": None, "orient": "bottom"},
                },
                "tooltip": [
                    {"field": "Deckname", "type": "nominal"},
                    {"field": "Monat", "type": "temporal", "format": "%Y-%m"},
                    {"field": "Median Cardmarket EUR", "type": "quantitative", "format": ".2f"},
                    {"field": "Preis-IQR EUR", "type": "quantitative", "format": ".2f"},
                    {"field": "Meta-Anteil %", "type": "quantitative", "format": ".2f"},
                    {"field": "Median Platzierungs-Perzentil", "type": "quantitative", "format": ".2f"},
                    {"field": "Decks", "type": "quantitative", "format": ".0f"},
                ],
            },
        },
        width="stretch",
    )


def _render_deck_name_stability_chart(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info("Fuer die aktuellen Filter konnten keine monatlichen Stabilitaetswerte berechnet werden.")
        return

    deck_domain: list[str] = []
    for row in sorted(rows, key=lambda item: (int(item["deck_rank"]), str(item["deck_name"]))):
        deck_name = str(row["deck_name"])
        if deck_name not in deck_domain:
            deck_domain.append(deck_name)

    chart_rows = [
        {
            "Monat": str(row["month_start"]),
            "Deckname": str(row["deck_name"]),
            "Deck-Rang": int(row["deck_rank"]),
            "Perzentil-IQR": float(row["placement_percentile_iqr"]),
            "Median Platzierungs-Perzentil": row.get("median_placement_percentile"),
            "Meta-Anteil %": row.get("meta_share_pct"),
            "Decks": int(row["deck_count"]),
            "Median Cardmarket EUR": row.get("median_cardmarket_deck_price_eur"),
        }
        for row in rows
        if row.get("placement_percentile_iqr") is not None
    ]

    if not chart_rows:
        st.info("Fuer die aktuellen Filter konnten keine monatlichen Stabilitaetswerte berechnet werden.")
        return

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": 340,
            "mark": {"type": "line", "point": True, "tooltip": True},
            "encoding": {
                "x": {
                    "field": "Monat",
                    "type": "temporal",
                    "axis": {"title": "Monat", "format": "%Y-%m"},
                },
                "y": {
                    "field": "Perzentil-IQR",
                    "type": "quantitative",
                    "axis": {"title": "Perzentil-IQR (niedriger = stabiler)"},
                    "scale": {"zero": True},
                },
                "color": {
                    "field": "Deckname",
                    "type": "nominal",
                    "scale": {"domain": deck_domain, "range": _trend_color_range(len(deck_domain))},
                    "legend": {"title": None, "orient": "bottom"},
                },
                "tooltip": [
                    {"field": "Deckname", "type": "nominal"},
                    {"field": "Monat", "type": "temporal", "format": "%Y-%m"},
                    {"field": "Perzentil-IQR", "type": "quantitative", "format": ".2f"},
                    {"field": "Median Platzierungs-Perzentil", "type": "quantitative", "format": ".2f"},
                    {"field": "Meta-Anteil %", "type": "quantitative", "format": ".2f"},
                    {"field": "Decks", "type": "quantitative", "format": ".0f"},
                    {"field": "Median Cardmarket EUR", "type": "quantitative", "format": ".2f"},
                ],
            },
        },
        width="stretch",
    )


def _build_bump_chart_rows(rows: list[dict[str, object]], ranking_label: str) -> list[dict[str, object]]:
    ranking_value_field = {
        "Meta-Anteil": "meta_share_pct",
        "Median Platzierungs-Perzentil": "median_placement_percentile",
    }[ranking_label]

    rows_by_month: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        ranking_value = row.get(ranking_value_field)
        if ranking_value is None:
            continue
        month_start = str(row["month_start"])
        rows_by_month.setdefault(month_start, []).append(row)

    chart_rows: list[dict[str, object]] = []
    for month_start in sorted(rows_by_month.keys()):
        month_rows = rows_by_month[month_start]
        if ranking_label == "Meta-Anteil":
            month_rows = sorted(
                month_rows,
                key=lambda row: (
                    -float(row.get("meta_share_pct") or 0.0),
                    -int(row.get("deck_count") or 0),
                    str(row["deck_name"]),
                ),
            )
        else:
            month_rows = sorted(
                month_rows,
                key=lambda row: (
                    -float(row.get("median_placement_percentile") or 0.0),
                    -float(row.get("meta_share_pct") or 0.0),
                    -int(row.get("deck_count") or 0),
                    str(row["deck_name"]),
                ),
            )

        for rank, row in enumerate(month_rows, start=1):
            chart_rows.append(
                {
                    "Monat": month_start,
                    "Deckname": str(row["deck_name"]),
                    "Deck-Rang": int(row["deck_rank"]),
                    "Rang": rank,
                    "Rangtyp": ranking_label,
                    "Meta-Anteil %": row.get("meta_share_pct"),
                    "Median Platzierungs-Perzentil": row.get("median_placement_percentile"),
                    "Perzentil-IQR": row.get("placement_percentile_iqr"),
                    "Decks": int(row["deck_count"]),
                    "Median Cardmarket EUR": row.get("median_cardmarket_deck_price_eur"),
                }
            )
    return chart_rows


def _render_deck_name_bump_chart(rows: list[dict[str, object]], ranking_label: str) -> None:
    if not rows:
        st.info("Fuer die aktuellen Filter konnten keine Rangverlaeufe berechnet werden.")
        return

    deck_domain: list[str] = []
    for row in sorted(rows, key=lambda item: (int(item["deck_rank"]), str(item["deck_name"]))):
        deck_name = str(row["deck_name"])
        if deck_name not in deck_domain:
            deck_domain.append(deck_name)

    chart_rows = _build_bump_chart_rows(rows, ranking_label)
    if not chart_rows:
        st.info("Fuer die aktuellen Filter konnten keine Rangverlaeufe berechnet werden.")
        return

    max_rank = max(int(row["Rang"]) for row in chart_rows)
    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": 360,
            "mark": {"type": "line", "point": {"filled": True, "size": 80}, "tooltip": True},
            "encoding": {
                "x": {
                    "field": "Monat",
                    "type": "temporal",
                    "axis": {"title": "Monat", "format": "%Y-%m"},
                },
                "y": {
                    "field": "Rang",
                    "type": "quantitative",
                    "axis": {"title": f"{ranking_label}-Rang", "tickMinStep": 1},
                    "scale": {"domain": [max_rank, 1], "nice": False},
                },
                "color": {
                    "field": "Deckname",
                    "type": "nominal",
                    "scale": {"domain": deck_domain, "range": _trend_color_range(len(deck_domain))},
                    "legend": {"title": None, "orient": "bottom"},
                },
                "detail": {"field": "Deckname", "type": "nominal"},
                "tooltip": [
                    {"field": "Deckname", "type": "nominal"},
                    {"field": "Monat", "type": "temporal", "format": "%Y-%m"},
                    {"field": "Rang", "type": "quantitative", "format": ".0f", "title": "Rang"},
                    {"field": "Meta-Anteil %", "type": "quantitative", "format": ".2f"},
                    {"field": "Median Platzierungs-Perzentil", "type": "quantitative", "format": ".2f"},
                    {"field": "Perzentil-IQR", "type": "quantitative", "format": ".2f"},
                    {"field": "Decks", "type": "quantitative", "format": ".0f"},
                    {"field": "Median Cardmarket EUR", "type": "quantitative", "format": ".2f"},
                ],
            },
        },
        width="stretch",
    )


def _render_control_section() -> tuple[int, str, int, str, str, bool]:
    st.info(
        "Die Detailtabellen für Kartenliste und Einzeldecks liegen auf der separaten Detailseite."
    )
    with st.container(border=True):
        st.subheader("Steuerung")
        st.caption(
            "Die Uebersicht wird ueber Stichprobengroesse, Ranking und Profilauswahl gesteuert. Tabelle und Plots lesen immer dieselbe gefilterte Deckmenge."
        )

        control_panel_1, control_panel_2 = st.columns((1.2, 1))

        with control_panel_1.container(border=True):
            st.markdown("**Stichprobe und Ranking**")
            sample_col_1, sample_col_2, sample_col_3 = st.columns(3)
            minimum_deck_count = sample_col_1.selectbox(
                "Mindestanzahl",
                options=[1, 3, 5, 10, 20],
                index=2,
            )
            table_ranking_label = sample_col_2.selectbox(
                "Tabellen-Ranking",
                options=["Meta-Anteil", "Median Platzierungs-Perzentil", "Top-25 %", "Preis-Leistung", "Resultate letzte 30 Tage"],
                index=0,
            )
            profile_top_n = sample_col_3.selectbox(
                "Top-N Profilplot",
                options=[3, 5, 8, 10],
                index=1,
            )

        with control_panel_2.container(border=True):
            st.markdown("**Visualisierung und Tabelle**")
            view_col_1, view_col_2 = st.columns(2)
            profile_sort_label = view_col_1.selectbox(
                "Profilplot sortieren nach",
                options=["Meta-Anteil", "Deckanzahl", "Ø Platzierungs-Perzentil", "Median Cardmarket €"],
                index=0,
            )
            bump_ranking_label = view_col_2.selectbox(
                "Bump-Chart nach",
                options=["Meta-Anteil", "Median Platzierungs-Perzentil"],
                index=0,
            )
            show_extended_metrics = st.toggle("Erweiterte Kennzahlen", value=False)
            st.caption("Schaltet Zusatzspalten wie IQR, Teilnehmermittel, Rohplatzierung und Recency in der Tabelle frei.")
    return int(minimum_deck_count), str(table_ranking_label), int(profile_top_n), str(profile_sort_label), str(bump_ranking_label), bool(show_extended_metrics)


def _load_filtered_rows(
    aggregate_rows: list[dict[str, object]],
    minimum_deck_count: int,
    table_ranking_label: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, dict[str, object] | None]]:
    filtered_rows = [row for row in aggregate_rows if int(row["deck_count"]) >= minimum_deck_count]
    if not filtered_rows:
        st.warning("Mit der aktuellen Mindestanzahl an Listen bleiben keine Decknamen uebrig.")
        st.stop()

    ranked_rows = _sort_aggregate_rows(filtered_rows, table_ranking_label)
    highlight_rows = _select_highlight_rows(filtered_rows)
    return filtered_rows, ranked_rows, highlight_rows


def _load_plot_data(
    repository: DashboardRepository,
    ranked_rows: list[dict[str, object]],
    minimum_deck_count: int,
    profile_top_n: int,
    profile_sort_label: str,
    start_date: object,
    end_date: object,
) -> dict[str, object]:
    profile_sort_field_by_label = {
        "Meta-Anteil": "meta_share_pct",
        "Deckanzahl": "deck_count",
        "Ø Platzierungs-Perzentil": "average_placement_percentile",
        "Median Cardmarket €": "median_cardmarket_deck_price_eur",
    }
    selected_sort_field = profile_sort_field_by_label[profile_sort_label]
    plot_data = load_aggregate_plot_data(
        repository,
        ranked_deck_names=tuple(str(row["deck_name"]) for row in ranked_rows),
        minimum_deck_count=minimum_deck_count,
        profile_top_n=profile_top_n,
        sort_field=selected_sort_field,
        start_date=start_date,
        end_date=end_date,
    )
    return {
        "scatter_rows": plot_data["scatter_rows"],
        "cost_rows": plot_data["cost_rows"],
        "profile_rows": plot_data["profile_rows"],
        "trend_rows": plot_data["trend_rows"],
        "trend_series_by_deck_name": _build_trend_series_by_deck_name(plot_data["table_trend_rows"]),
    }


def _render_highlight_section(
    highlight_rows: dict[str, dict[str, object] | None],
    filtered_rows: list[dict[str, object]],
) -> None:
    st.caption(
        "Die Tabelle priorisiert normalisierte Vergleichswerte. In der erweiterten Ansicht kommen Sekundaerkennzahlen wie Rohplatzierung, IQRs, Teilnehmermittel und Recency hinzu."
    )
    with st.container(border=True):
        st.subheader("Schnelle Einordnung")
        st.caption(
            "Die drei Karten verdichten die aktuelle Filterlage. Preis-Leistung nutzt hier Median Platzierungs-Perzentil pro 100 EUR Median Cardmarket als einfache Heuristik."
        )

        summary_col_1, summary_col_2, summary_col_3, summary_col_4 = st.columns(4)
        summary_col_1.metric("Decknamen im Filter", len(filtered_rows), border=True)
        summary_col_2.metric(
            "Listen im Filter",
            sum(int(row.get("deck_count") or 0) for row in filtered_rows),
            border=True,
        )
        median_meta_share = _numeric_median(filtered_rows, "meta_share_pct")
        summary_col_3.metric(
            "Median Meta %",
            f"{median_meta_share:.2f}" if median_meta_share is not None else "-",
            border=True,
        )
        median_price = _numeric_median(filtered_rows, "median_cardmarket_deck_price_eur")
        summary_col_4.metric(
            "Median Cardmarket €",
            f"EUR {median_price:.2f}" if median_price is not None else "-",
            border=True,
        )

        highlight_col_1, highlight_col_2, highlight_col_3 = st.columns(3)
        most_played_row = highlight_rows["most_played"]
        best_median_performance_row = highlight_rows["best_median_performance"]
        best_value_row = highlight_rows["best_value"]

        _render_highlight_card(
            highlight_col_1,
            title="Meistgespieltes Deck",
            row=most_played_row,
            delta_text=(
                f"{int(most_played_row['deck_count'])} Listen | {float(most_played_row['meta_share_pct']):.2f}% Meta"
                if most_played_row is not None
                else "-"
            ),
            supporting_text=(
                f"Median Perzentil: {float(most_played_row['median_placement_percentile']):.2f} | Median Cardmarket: EUR {float(most_played_row['median_cardmarket_deck_price_eur']):.2f}"
                if most_played_row is not None
                and most_played_row.get("median_placement_percentile") is not None
                and most_played_row.get("median_cardmarket_deck_price_eur") is not None
                else "Median Perzentil oder Medianpreis fehlt."
            ),
        )
        _render_highlight_card(
            highlight_col_2,
            title="Bestes Median-Perzentil",
            row=best_median_performance_row,
            delta_text=(
                f"{float(best_median_performance_row['median_placement_percentile']):.2f} Median-Perzentil"
                if best_median_performance_row is not None and best_median_performance_row.get("median_placement_percentile") is not None
                else "-"
            ),
            supporting_text=(
                f"Meta-Anteil: {float(best_median_performance_row['meta_share_pct']):.2f}% | Decks: {int(best_median_performance_row['deck_count'])}"
                if best_median_performance_row is not None
                else "Keine Daten verfuegbar."
            ),
        )
        _render_highlight_card(
            highlight_col_3,
            title="Bestes Preis-Leistungs-Verhaeltnis",
            row=best_value_row,
            delta_text=(
                f"{_value_efficiency_score(best_value_row):.2f} Perzentilpunkte / 100 EUR"
                if best_value_row is not None and _value_efficiency_score(best_value_row) is not None
                else "-"
            ),
            supporting_text=(
                f"Median Perzentil: {float(best_value_row['median_placement_percentile']):.2f} | Median Cardmarket: EUR {float(best_value_row['median_cardmarket_deck_price_eur']):.2f}"
                if best_value_row is not None
                and best_value_row.get("median_placement_percentile") is not None
                and best_value_row.get("median_cardmarket_deck_price_eur") is not None
                else "Median Perzentil oder Medianpreis fehlt."
            ),
        )


def _render_plot_section(plot_data: dict[str, object]) -> None:
    st.subheader("Vergleichsplots")
    st.caption(
        "Die Scatterplots stellen Popularitaet, Performance und Kosten gegenueber. Der Profilplot darunter verdichtet das Main- und Side-Profil der wichtigsten Decknamen nach dem gewaehlten Ranking-Kriterium."
    )

    plot_col_1, plot_col_2 = st.columns(2)
    with plot_col_1.container(border=True):
        st.markdown("**Popularitaet versus Performance**")
        st.caption(
            "X ist der Meta-Anteil, Y das durchschnittliche Platzierungs-Perzentil. Die Bubble-Groesse zeigt die absolute Zahl an Listen, die Farbe den Median der Cardmarket-Kosten."
        )
        _render_popularity_performance_scatter(plot_data["scatter_rows"])

    with plot_col_2.container(border=True):
        st.markdown("**Kosten versus Performance**")
        st.caption(
            "X ist der Median der Cardmarket-Kosten, Y das durchschnittliche Platzierungs-Perzentil. Bubble-Groesse und Farbe zeigen hier den Meta-Anteil."
        )
        _render_cost_performance_scatter(plot_data["cost_rows"])

    with st.container(border=True):
        st.markdown("**Deckprofil der wichtigsten Decknamen**")
        st.caption(
            "Der Profilplot kombiniert Main Deck und Side Deck fuer die aktuell wichtigsten Decknamen und zeigt pro Deckbereich die durchschnittlichen Engine- und Non-Engine-Anteile."
        )
        _render_deck_profile_chart(plot_data["profile_rows"])


def _render_trend_section(plot_data: dict[str, object], bump_ranking_label: str) -> None:
    trend_rows = plot_data["trend_rows"]
    st.subheader("Monatliche Entwicklung")
    st.caption(
        "Die Trendansicht verfolgt dieselben Top-N Decknamen wie der Profilplot ueber die Zeit. Sie zeigt Meta-Anteil, Performance, Preis-Drift und Stabilitaet in einer gemeinsamen Monatsansicht."
    )

    trend_col_1, trend_col_2 = st.columns(2)
    with trend_col_1:
        st.markdown("**Meta-Anteile nach Monat**")
        st.caption(
            "Jede Zelle zeigt, wie stark ein Deckname innerhalb des jeweiligen Monats im gefilterten Feld vertreten war. So werden Aufstieg, Rueckgang und saisonale Luecken sofort sichtbar."
        )
        _render_deck_name_meta_heatmap(trend_rows)

    with trend_col_2:
        st.markdown("**Performance-Drift nach Monat**")
        st.caption(
            "Die Linien zeigen das Median Platzierungs-Perzentil pro Monat. Der Tooltip enthaelt zusaetzlich IQR, Monatsanteil und Median Cardmarket, um stabile von swingigen Decks besser zu trennen."
        )
        _render_deck_name_performance_drift(trend_rows)

    trend_col_3, trend_col_4 = st.columns(2)
    with trend_col_3:
        st.markdown("**Preis-Drift nach Monat**")
        st.caption(
            "Die Linien zeigen den monatlichen Median der Cardmarket-Kosten. Der Tooltip enthaelt zusaetzlich Preis-IQR, Meta-Anteil und Median-Perzentil, damit Preisspruenge direkt eingeordnet werden koennen."
        )
        _render_deck_name_price_drift(trend_rows)

    with trend_col_4:
        st.markdown("**Stabilitaet nach Monat**")
        st.caption(
            "Hier steht die Streuung der Ergebnisse im Fokus. Niedrigere Perzentil-IQR-Werte bedeuten, dass ein Deck in diesem Monat konstanter performt hat."
        )
        _render_deck_name_stability_chart(trend_rows)

    st.markdown("**Rangverlauf der wichtigsten Decknamen**")
    st.caption(
        "Der Bump-Chart ordnet dieselben Decknamen pro Monat neu ein. Je nach Steuerung basiert der Rang entweder auf Meta-Anteil oder auf dem Median Platzierungs-Perzentil. Rang 1 liegt oben."
    )
    _render_deck_name_bump_chart(trend_rows, bump_ranking_label)


def _render_table_section(
    ranked_rows: list[dict[str, object]],
    show_extended_metrics: bool,
    trend_series_by_deck_name: dict[str, dict[str, list[float]]],
) -> None:
    st.subheader("Alle aggregierten Decknamen")
    st.caption(
        "Die Tabelle bleibt die Uebersicht. Fuer konkrete Turnierlisten kannst du einen Decknamen direkt an die Decklisten-Seite uebergeben."
    )

    with st.container(border=True):
        detail_nav_col_1, detail_nav_col_2 = st.columns((3, 1))
        visible_deck_names = [str(row["deck_name"]) for row in ranked_rows]
        if st.session_state.get(DETAIL_NAVIGATION_STATE_KEY) not in visible_deck_names:
            st.session_state[DETAIL_NAVIGATION_STATE_KEY] = visible_deck_names[0]

        selected_detail_deck_name = detail_nav_col_1.selectbox(
            "Deckname zur Detailseite",
            options=visible_deck_names,
            key=DETAIL_NAVIGATION_STATE_KEY,
        )
        if detail_nav_col_2.button("Decklisten-Details oeffnen"):
            _open_decklist_detail(selected_detail_deck_name)

    st.dataframe(
        _build_aggregate_table_rows(
            ranked_rows,
            show_extended_metrics=show_extended_metrics,
            trend_series_by_deck_name=trend_series_by_deck_name,
        ),
        hide_index=True,
        width="stretch",
        column_config=_aggregate_column_config(),
    )


def main() -> None:
    st.set_page_config(page_title="Aggregierte Decks", layout="wide")

    database_path = resolve_dashboard_db_path()
    repository = DashboardRepository(database_path)

    st.title("Aggregierte Decknamen")

    status_message = repository.status_message()
    if status_message is not None:
        st.warning(status_message)
        st.stop()

    start_date, end_date = render_dashboard_date_filter(repository)
    aggregate_rows = load_deck_name_aggregates_extended(
        repository,
        limit=1000,
        start_date=start_date,
        end_date=end_date,
    )
    if not aggregate_rows:
        st.warning("Es sind noch keine aggregierbaren Deckdaten vorhanden.")
        st.stop()

    minimum_deck_count, table_ranking_label, profile_top_n, profile_sort_label, bump_ranking_label, show_extended_metrics = _render_control_section()
    filtered_rows, ranked_rows, highlight_rows = _load_filtered_rows(aggregate_rows, minimum_deck_count, table_ranking_label)
    plot_data = _load_plot_data(
        repository,
        ranked_rows,
        minimum_deck_count,
        profile_top_n,
        profile_sort_label,
        start_date,
        end_date,
    )

    _render_highlight_section(highlight_rows, filtered_rows)
    _render_plot_section(plot_data)
    _render_trend_section(plot_data, bump_ranking_label)
    _render_table_section(
        ranked_rows,
        show_extended_metrics,
        plot_data["trend_series_by_deck_name"],
    )


main()