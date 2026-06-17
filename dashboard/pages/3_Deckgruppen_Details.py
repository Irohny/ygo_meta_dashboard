from __future__ import annotations

from pathlib import Path

import streamlit as st

from ygo_crawler.dashboard_cache import (
    load_deck_name_aggregates_extended,
    load_group_page_data,
)
from ygo_crawler.dashboard_filters import render_dashboard_date_filter
from ygo_crawler.dashboard_queries import DashboardRepository, resolve_dashboard_db_path

DECK_NAME_STATE_KEY = "decklisten_selected_deck_name"
DECK_INSTANCE_STATE_KEY = "decklisten_selected_deck_id"
QUERY_PARAM_DECK_NAME = "deck_name"
QUERY_PARAM_DECK_ID = "deck_id"
DECKLIST_PAGE_PATH = Path(__file__).with_name("1_Decklisten.py")
DECKBUILDER_PAGE_PATH = Path(__file__).with_name("6_Deckbuilder.py")
DECKGROUP_DRILLDOWN_STATE_KEY = "deckgruppen_details_selected_deck_site_id"
DECKBUILDER_DECK_GROUP_STATE_KEY = "deckbuilder_deck_group"


def _drop_columns(
    rows: list[dict[str, object]], columns: set[str]
) -> list[dict[str, object]]:
    return [
        {key: value for key, value in row.items() if key not in columns} for row in rows
    ]


def _card_table_config() -> dict[str, object]:
    return {
        "Bild": st.column_config.ImageColumn(
            "Bild",
            help="Kleines Kartenbild aus der YGOPRODeck-API.",
            width="small",
        ),
        "Klasse": st.column_config.TextColumn(
            "Klasse",
            help="Automatisch bestimmte Rolle der Karte innerhalb der gewaehlten Deckgruppe.",
            width="medium",
        ),
    }


def _component_color(component_type: str, component_index: int) -> str:
    if component_type == "non_engine_handtrap":
        return "#E76F51"
    if component_type == "non_engine_boardbreaker":
        return "#F4A261"
    if component_type == "non_engine_other":
        return "#E9C46A"
    if component_type == "rest_engine":
        return "#8E9AAF"

    engine_palette = ["#1D3557", "#2A9D8F", "#F4A261", "#457B9D", "#6D597A"]
    return engine_palette[component_index % len(engine_palette)]


def _render_deck_section_share_chart(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info(
            "Fuer diese Deckgruppe konnte keine Deckbereich-Komposition berechnet werden."
        )
        return

    chart_rows: list[dict[str, object]] = []
    color_range: list[str] = []
    domain: list[str] = []
    engine_index = 0
    seen_components: set[str] = set()
    for sort_index, row in enumerate(rows):
        component_name = str(row["component_name"])
        component_type = str(row["component_type"])
        if component_name not in seen_components:
            domain.append(component_name)
            color_range.append(_component_color(component_type, engine_index))
            seen_components.add(component_name)
            if component_type == "main_engine":
                engine_index += 1
        chart_rows.append(
            {
                "Deckbereich": (
                    "Main Deck" if str(row["section"]) == "main" else "Side Deck"
                ),
                "Baustein": component_name,
                "Anteil %": float(row["share_pct"]),
                "Ø Kopien / Gruppendeck": float(row["average_copies_per_group_deck"]),
                "Sortierung": sort_index,
            }
        )

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": 180,
            "mark": {"type": "bar", "tooltip": True},
            "encoding": {
                "y": {
                    "field": "Deckbereich",
                    "type": "nominal",
                    "axis": {"title": None, "labelAngle": 0},
                    "sort": ["Main Deck", "Side Deck"],
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
                    "title": "Baustein",
                    "scale": {"domain": domain, "range": color_range},
                    "sort": domain,
                },
                "order": {"field": "Sortierung", "type": "quantitative"},
                "tooltip": [
                    {"field": "Deckbereich", "type": "nominal"},
                    {"field": "Baustein", "type": "nominal"},
                    {"field": "Anteil %", "type": "quantitative", "format": ".1f"},
                    {
                        "field": "Ø Kopien / Gruppendeck",
                        "type": "quantitative",
                        "format": ".2f",
                    },
                ],
            },
        },
        width="stretch",
    )


def _format_number(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _format_percent(value: object) -> str:
    if value is None:
        return "-"
    return f"{float(value):.2f}%"


def _format_ratio_percent(value: object) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100.0:.2f}%"


def _format_currency(value: object, symbol: str) -> str:
    if value is None:
        return "-"
    return f"{symbol}{float(value):.2f}"


def _format_cardmarket_range(row: dict[str, object]) -> str:
    p25_value = row.get("cardmarket_deck_price_p25_eur")
    p75_value = row.get("cardmarket_deck_price_p75_eur")
    if p25_value is None or p75_value is None:
        return "-"
    return f"EUR {float(p25_value):.2f} - EUR {float(p75_value):.2f}"


def _placement_percentile(
    participants_count: object, placement_sort_value: object
) -> float | None:
    if participants_count is None or placement_sort_value is None:
        return None
    participants_total = int(participants_count)
    placement_value = int(placement_sort_value)
    if participants_total <= 0 or placement_value <= 0:
        return None
    return round(
        (participants_total - placement_value + 1) * 100.0 / participants_total, 2
    )


def _date_sort_value(value: object) -> int:
    if value is None:
        return 0
    return int(str(value).replace("-", ""))


def _sorted_deck_instances(
    rows: list[dict[str, object]], sort_mode: str
) -> list[dict[str, object]]:
    if sort_mode == "Bestes Platzierungs-Perzentil":
        return sorted(
            rows,
            key=lambda row: (
                -(
                    _placement_percentile(
                        row.get("participants_count"), row.get("placement_sort_value")
                    )
                    or -1.0
                ),
                -_date_sort_value(row.get("tournament_date")),
                int(row.get("placement_sort_value") or 99_999),
                str(row.get("player_name") or ""),
            ),
        )
    if sort_mode == "Niedrigste Cardmarket Summe":
        return sorted(
            rows,
            key=lambda row: (
                row.get("cardmarket_deck_price_eur") is None,
                float(row.get("cardmarket_deck_price_eur") or 0.0),
                -_date_sort_value(row.get("tournament_date")),
                int(row.get("placement_sort_value") or 99_999),
            ),
        )
    if sort_mode == "Hoechste Cardmarket Summe":
        return sorted(
            rows,
            key=lambda row: (
                row.get("cardmarket_deck_price_eur") is None,
                -(float(row.get("cardmarket_deck_price_eur") or -1.0)),
                -_date_sort_value(row.get("tournament_date")),
                int(row.get("placement_sort_value") or 99_999),
            ),
        )
    return sorted(
        rows,
        key=lambda row: (
            -_date_sort_value(row.get("tournament_date")),
            int(row.get("placement_sort_value") or 99_999),
            str(row.get("player_name") or ""),
        ),
    )


def _prepare_deck_instance_rows(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    prepared_rows: list[dict[str, object]] = []
    for row in rows:
        prepared_rows.append(
            {
                "Deckname": row["deck_name"],
                "Spieler": row["player_name"],
                "Platzierung": row["placement"],
                "Platzierungs-Perzentil": _placement_percentile(
                    row.get("participants_count"),
                    row.get("placement_sort_value"),
                ),
                "Teilnehmer": row["participants_count"],
                "Turnier": row["tournament_name"],
                "Datum": row["tournament_date"],
                "Main": row["main_card_total"],
                "Extra": row["extra_card_total"],
                "Side": row["side_card_total"],
                "Cardmarket Summe €": row["cardmarket_deck_price_eur"],
                "Deck URL": row["deck_url"],
            }
        )
    return prepared_rows


def _deck_instance_drilldown_label(row: dict[str, object]) -> str:
    return " | ".join(
        [
            str(row.get("tournament_date") or "-"),
            f"Platz {row.get('placement') or '-'}",
            _format_percent(
                _placement_percentile(
                    row.get("participants_count"), row.get("placement_sort_value")
                )
            ),
            str(row.get("tournament_name") or "-"),
            str(row.get("player_name") or "-"),
        ]
    )


def _open_decklist_instance(deck_name: str, deck_site_id: int) -> None:
    st.session_state[DECK_NAME_STATE_KEY] = deck_name
    st.session_state[DECK_INSTANCE_STATE_KEY] = deck_site_id
    st.switch_page(
        DECKLIST_PAGE_PATH,
        query_params={
            QUERY_PARAM_DECK_NAME: deck_name,
            QUERY_PARAM_DECK_ID: str(deck_site_id),
        },
    )


def _render_metric(
    column: st.delta_generator.DeltaGenerator,
    label: str,
    value: str,
    delta: str | None = None,
) -> None:
    if delta is None:
        column.metric(label, value, border=True)
        return
    column.metric(label, value, delta=delta, delta_color="off", border=True)


def _render_metric_group(
    column: st.delta_generator.DeltaGenerator,
    title: str,
    metrics: list[tuple[str, str, str | None]],
    *,
    columns: int,
    description: str | None = None,
) -> None:
    with column.container(border=True):
        st.markdown(f"**{title}**")
        if description:
            st.caption(description)

        for offset in range(0, len(metrics), columns):
            metric_columns = st.columns(columns)
            for metric_column, (label, value, delta) in zip(
                metric_columns, metrics[offset : offset + columns]
            ):
                _render_metric(metric_column, label, value, delta)


def _render_section_header(title: str, description: str | None = None) -> None:
    st.subheader(title)
    if description:
        st.caption(description)


def _render_aggregated_card_section(
    rows: list[dict[str, object]],
    *,
    section_label: str,
    columns_to_drop: set[str],
    empty_message: str,
) -> None:
    if not rows:
        st.info(empty_message)
        return

    consensus_rows = _rows_above_inclusion(rows, 80.0)
    flex_rows = _rows_in_inclusion_band(rows, 20.0, 80.0)
    average_inclusion = (
        round(sum(float(row.get("Anteil %") or 0.0) for row in rows) / len(rows), 2)
        if rows
        else 0.0
    )
    highest_inclusion_row = max(
        rows,
        key=lambda row: (
            float(row.get("Anteil %") or 0.0),
            float(row.get("Ø Kopien / Deck") or 0.0),
            str(row["Karte"]),
        ),
    )
    highest_cost_row = max(
        rows,
        key=lambda row: (
            float(row.get("Ø Kosten / Deck €") or 0.0),
            float(row.get("Ø Cardmarket €") or 0.0),
            str(row["Karte"]),
        ),
    )

    metric_cols = st.columns(4)
    metric_cols[0].metric(f"Karten im {section_label}", len(rows))
    metric_cols[1].metric("Konsens-Karten", len(consensus_rows))
    metric_cols[2].metric("Flex-Karten", len(flex_rows))
    metric_cols[3].metric("Ø Inklusion %", _format_percent(average_inclusion))

    st.caption(
        f"Hoechste Inklusion: {highest_inclusion_row['Karte']} ({_format_percent(highest_inclusion_row.get('Anteil %'))}) | "
        f"Teuerste Karte pro Deck: {highest_cost_row['Karte']} ({_format_currency(highest_cost_row.get('Ø Kosten / Deck €'), '€')}) | "
        f"Core-Beispiele: {_slot_examples(consensus_rows)}"
    )
    st.dataframe(
        _drop_columns(rows, columns_to_drop),
        hide_index=True,
        width="stretch",
        column_config=_card_table_config(),
    )


def _top_non_engine_row(
    rows: list[dict[str, object]],
    *,
    role_label: str | None = None,
    sort_field: str,
) -> dict[str, object] | None:
    filtered_rows = rows
    if role_label is not None:
        filtered_rows = [
            row for row in rows if str(row.get("Rolle") or "-") == role_label
        ]
    if not filtered_rows:
        return None
    return max(
        filtered_rows,
        key=lambda row: (
            float(row.get(sort_field) or 0.0),
            float(row.get("Gruppen-Inklusion %") or 0.0),
            float(row.get("Ø Kopien bei Nutzung") or 0.0),
            str(row.get("Karte") or ""),
        ),
    )


def _non_engine_metric_value(
    row: dict[str, object] | None, *, value_field: str, formatter: callable
) -> str:
    if row is None:
        return "-"
    return str(row.get("Karte") or "-")


def _non_engine_metric_delta(
    row: dict[str, object] | None, *, value_field: str, formatter: callable
) -> str:
    if row is None:
        return "-"
    return formatter(row.get(value_field))


def _render_non_engine_summary(rows: list[dict[str, object]]) -> None:
    top_inclusion_row = _top_non_engine_row(rows, sort_field="Gruppen-Inklusion %")
    top_side_row = _top_non_engine_row(rows, sort_field="Side >=1 %")
    top_handtrap_row = _top_non_engine_row(
        rows, role_label="Handtrap", sort_field="Gruppen-Inklusion %"
    )
    top_boardbreaker_row = _top_non_engine_row(
        rows, role_label="Boardbreaker", sort_field="Gruppen-Inklusion %"
    )

    summary_cols = st.columns(4)
    summary_cols[0].metric(
        "Hoechste Inklusion",
        _non_engine_metric_value(
            top_inclusion_row,
            value_field="Gruppen-Inklusion %",
            formatter=_format_percent,
        ),
        _non_engine_metric_delta(
            top_inclusion_row,
            value_field="Gruppen-Inklusion %",
            formatter=_format_percent,
        ),
        delta_color="off",
    )
    summary_cols[1].metric(
        "Staerkster Side-Staple",
        _non_engine_metric_value(
            top_side_row, value_field="Side >=1 %", formatter=_format_percent
        ),
        _non_engine_metric_delta(
            top_side_row, value_field="Side >=1 %", formatter=_format_percent
        ),
        delta_color="off",
    )
    summary_cols[2].metric(
        "Meistgespielte Handtrap",
        _non_engine_metric_value(
            top_handtrap_row,
            value_field="Gruppen-Inklusion %",
            formatter=_format_percent,
        ),
        _non_engine_metric_delta(
            top_handtrap_row,
            value_field="Gruppen-Inklusion %",
            formatter=_format_percent,
        ),
        delta_color="off",
    )
    summary_cols[3].metric(
        "Meistgespielter Boardbreaker",
        _non_engine_metric_value(
            top_boardbreaker_row,
            value_field="Gruppen-Inklusion %",
            formatter=_format_percent,
        ),
        _non_engine_metric_delta(
            top_boardbreaker_row,
            value_field="Gruppen-Inklusion %",
            formatter=_format_percent,
        ),
        delta_color="off",
    )

    st.caption(
        "Die Summary fokussiert auf lokale Relevanz in der aktuell gewaehlten Deckgruppe: Gruppen-Inklusion fuer generelle Verbreitung und `Side >=1 %` fuer echte Side-Staples."
    )


def _render_non_engine_table(rows: list[dict[str, object]], empty_message: str) -> None:
    if not rows:
        st.info(empty_message)
        return

    _render_non_engine_summary(rows)

    metric_col_1, metric_col_2, metric_col_3 = st.columns(3)
    metric_col_1.metric("Karten", len(rows))
    metric_col_2.metric(
        "Mit Main-Anteil",
        sum(1 for row in rows if row["average_main_copies_per_group_deck"] > 0),
    )
    metric_col_3.metric(
        "Mit Side-Anteil",
        sum(1 for row in rows if row["average_side_copies_per_group_deck"] > 0),
    )

    st.dataframe(
        [
            {
                "Bild": row["image_url_small"],
                "Karte": row["card_name"],
                "Rolle": row["non_engine_role_label"],
                "Sicherheit": row["role_confidence"] or "-",
                "Archetype": row["card_archetype"] or "-",
                "Gruppen-Inklusion %": row["group_inclusion_rate_pct"],
                "Ø Main / Gruppendeck": row["average_main_copies_per_group_deck"],
                "Ø Side / Gruppendeck": row["average_side_copies_per_group_deck"],
                "Main >=1 %": row["main_presence_pct"],
                "Side >=1 %": row["side_presence_pct"],
                "Ø Kopien bei Nutzung": row["average_copies_when_present"],
                "Ø Cardmarket €": row["average_cardmarket_price_eur"],
            }
            for row in rows
        ],
        hide_index=True,
        width="stretch",
        column_config=_card_table_config(),
    )


def _rows_above_inclusion(
    rows: list[dict[str, object]], threshold: float
) -> list[dict[str, object]]:
    return [row for row in rows if float(row.get("Anteil %") or 0.0) >= threshold]


def _rows_in_inclusion_band(
    rows: list[dict[str, object]], lower_bound: float, upper_bound: float
) -> list[dict[str, object]]:
    return [
        row
        for row in rows
        if lower_bound <= float(row.get("Anteil %") or 0.0) < upper_bound
    ]


def _slot_examples(
    rows: list[dict[str, object]], *, prefix: str | None = None, limit: int = 3
) -> str:
    if not rows:
        return "-"
    labels = [
        f"{prefix}: {row['Karte']}" if prefix else str(row["Karte"])
        for row in rows[:limit]
    ]
    return ", ".join(labels)


def _render_group_profile_summary(
    benchmarks: dict[str, object] | None,
    aggregated_cards: dict[str, list[dict[str, object]]],
) -> None:
    if benchmarks is None:
        st.info("Fuer diese Deckgruppe konnten keine Profil-KPIs berechnet werden.")
        return

    main_rows = aggregated_cards.get("main", [])
    side_rows = aggregated_cards.get("side", [])
    core_threshold = 80.0
    flex_lower_bound = 20.0

    main_core_rows = _rows_above_inclusion(main_rows, core_threshold)
    side_core_rows = _rows_above_inclusion(side_rows, core_threshold)
    main_flex_rows = _rows_in_inclusion_band(
        main_rows, flex_lower_bound, core_threshold
    )
    side_flex_rows = _rows_in_inclusion_band(
        side_rows, flex_lower_bound, core_threshold
    )

    _render_metric_group(
        st.container(),
        "Main- und Side-Verteilung",
        [
            (
                "Main Engine %",
                _format_percent(benchmarks.get("average_main_engine_share_pct")),
                None,
            ),
            (
                "Main Non-Engine %",
                _format_percent(benchmarks.get("average_main_non_engine_share_pct")),
                None,
            ),
            (
                "Side Non-Engine %",
                _format_percent(benchmarks.get("average_side_non_engine_share_pct")),
                None,
            ),
            (
                "Side Handtraps %",
                _format_percent(benchmarks.get("average_side_handtrap_share_pct")),
                None,
            ),
            (
                "Side Boardbreaker %",
                _format_percent(benchmarks.get("average_side_boardbreaker_share_pct")),
                None,
            ),
            (
                "Side Weitere NE %",
                _format_percent(
                    benchmarks.get("average_side_non_engine_other_share_pct")
                ),
                None,
            ),
        ],
        columns=3,
    )
    _render_metric_group(
        st.container(),
        "Core und Flex",
        [
            ("Main-Core-Karten", str(len(main_core_rows)), None),
            ("Side-Core-Karten", str(len(side_core_rows)), None),
            (
                "Flex-Slots Main+Side",
                str(len(main_flex_rows) + len(side_flex_rows)),
                None,
            ),
        ],
        columns=3,
    )

    st.caption(
        "Core wird hier als mindestens 80 % Gruppen-Inklusion gelesen, Flex als 20 % bis unter 80 %. "
        f"Main-Core-Beispiele: {_slot_examples(main_core_rows)} | "
        f"Side-Core-Beispiele: {_slot_examples(side_core_rows)} | "
        f"Flex-Beispiele: {_slot_examples(main_flex_rows, prefix='Main')}"
        f"{'' if not side_flex_rows else ' | ' + _slot_examples(side_flex_rows, prefix='Side')}"
    )


def _trend_delta_points(current_value: object, previous_value: object) -> str | None:
    if current_value is None or previous_value is None:
        return None
    return f"{float(current_value) - float(previous_value):+.2f} pp vs. Vormonat"


def _trend_delta_currency(current_value: object, previous_value: object) -> str | None:
    if current_value is None or previous_value is None:
        return None
    return f"{float(current_value) - float(previous_value):+.2f} EUR vs. Vormonat"


def _trend_delta_count(current_value: object, previous_value: object) -> str | None:
    if current_value is None or previous_value is None:
        return None
    return f"{int(current_value) - int(previous_value):+d} vs. Vormonat"


def _render_group_trend_chart(
    rows: list[dict[str, object]],
    *,
    value_field: str,
    value_label: str,
    axis_title: str,
    value_format: str,
    color: str,
    empty_message: str,
) -> None:
    chart_rows = [
        {
            "Monat": str(row["month_start"]),
            value_label: float(row[value_field]),
            "Decks der Gruppe": int(row["deck_count"]),
            "Decks im Monat gesamt": int(row.get("month_total_deck_count") or 0),
            "Meta-Anteil %": row.get("meta_share_pct"),
            "Median Platzierungs-Perzentil": row.get("median_placement_percentile"),
            "Median Cardmarket EUR": row.get("median_cardmarket_deck_price_eur"),
        }
        for row in rows
        if row.get(value_field) is not None
    ]

    if not chart_rows:
        st.info(empty_message)
        return

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": 260,
            "mark": {"type": "line", "point": True, "tooltip": True, "color": color},
            "encoding": {
                "x": {
                    "field": "Monat",
                    "type": "temporal",
                    "axis": {"title": "Monat", "format": "%Y-%m"},
                },
                "y": {
                    "field": value_label,
                    "type": "quantitative",
                    "axis": {"title": axis_title},
                    "scale": {"zero": False},
                },
                "tooltip": [
                    {"field": "Monat", "type": "temporal", "format": "%Y-%m"},
                    {
                        "field": value_label,
                        "type": "quantitative",
                        "format": value_format,
                    },
                    {
                        "field": "Decks der Gruppe",
                        "type": "quantitative",
                        "format": ".0f",
                    },
                    {
                        "field": "Decks im Monat gesamt",
                        "type": "quantitative",
                        "format": ".0f",
                    },
                    {"field": "Meta-Anteil %", "type": "quantitative", "format": ".2f"},
                    {
                        "field": "Median Platzierungs-Perzentil",
                        "type": "quantitative",
                        "format": ".2f",
                    },
                    {
                        "field": "Median Cardmarket EUR",
                        "type": "quantitative",
                        "format": ".2f",
                    },
                ],
            },
        },
        width="stretch",
    )


def _render_group_trend_section(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info(
            "Fuer die aktuelle Deckgruppe konnten im aktiven Zeitraum keine Monats-Trends berechnet werden."
        )
        return

    latest_row = rows[-1]
    previous_row = rows[-2] if len(rows) > 1 else None

    st.caption(
        f"Beobachtete Monate: {len(rows)}. Letzter ausgewerteter Monat: {str(latest_row['month_start'])[:7]}. "
        "Die Deltas vergleichen immer mit dem direkt vorherigen Monat, sofern Daten vorhanden sind."
    )

    trend_cols = st.columns(5)
    trend_cols[0].metric(
        "Decks der Gruppe im Monat",
        int(latest_row["deck_count"]),
        _trend_delta_count(
            latest_row.get("deck_count"),
            previous_row.get("deck_count") if previous_row else None,
        ),
        delta_color="off",
    )
    trend_cols[1].metric(
        "Meta-Anteil im Monat",
        _format_percent(latest_row.get("meta_share_pct")),
        _trend_delta_points(
            latest_row.get("meta_share_pct"),
            previous_row.get("meta_share_pct") if previous_row else None,
        ),
        delta_color="off",
    )
    trend_cols[2].metric(
        "Median Platzierungs-Perzentil",
        _format_percent(latest_row.get("median_placement_percentile")),
        _trend_delta_points(
            latest_row.get("median_placement_percentile"),
            previous_row.get("median_placement_percentile") if previous_row else None,
        ),
        delta_color="off",
    )
    trend_cols[3].metric(
        "Median Cardmarket €",
        _format_currency(latest_row.get("median_cardmarket_deck_price_eur"), "€"),
        _trend_delta_currency(
            latest_row.get("median_cardmarket_deck_price_eur"),
            (
                previous_row.get("median_cardmarket_deck_price_eur")
                if previous_row
                else None
            ),
        ),
        delta_color="off",
    )
    trend_cols[4].metric(
        "Monatsdecks gesamt",
        int(latest_row.get("month_total_deck_count") or 0),
        _trend_delta_count(
            latest_row.get("month_total_deck_count"),
            previous_row.get("month_total_deck_count") if previous_row else None,
        ),
        delta_color="off",
    )

    meta_tab, performance_tab, price_tab = st.tabs(
        ["Meta-Anteil", "Performance", "Cardmarket"]
    )

    with meta_tab:
        _render_group_trend_chart(
            rows,
            value_field="meta_share_pct",
            value_label="Meta-Anteil %",
            axis_title="Meta-Anteil %",
            value_format=".2f",
            color="#1D3557",
            empty_message="Fuer die aktuelle Deckgruppe konnten keine monatlichen Meta-Anteile berechnet werden.",
        )

    with performance_tab:
        _render_group_trend_chart(
            rows,
            value_field="median_placement_percentile",
            value_label="Median Platzierungs-Perzentil",
            axis_title="Median Platzierungs-Perzentil",
            value_format=".2f",
            color="#2A9D8F",
            empty_message="Fuer die aktuelle Deckgruppe konnten keine monatlichen Performance-Werte berechnet werden.",
        )

    with price_tab:
        _render_group_trend_chart(
            rows,
            value_field="median_cardmarket_deck_price_eur",
            value_label="Median Cardmarket EUR",
            axis_title="Median Cardmarket EUR",
            value_format=".2f",
            color="#F4A261",
            empty_message="Fuer die aktuelle Deckgruppe konnten keine monatlichen Preiswerte berechnet werden.",
        )


def _render_selection_section(aggregate_options: list[str]) -> str:
    default_deck_name = st.session_state.get("selected_aggregated_deck_name")
    default_index = (
        aggregate_options.index(default_deck_name)
        if default_deck_name in aggregate_options
        else 0
    )

    with st.container(border=True):
        st.markdown("**Deckgruppe**")
        st.caption(
            "Die Auswahl steuert alle Kennzahlen, Profile und Drilldowns fuer die gewaehlte Gruppe im aktuellen Zeitraum."
        )
        selected_deck_name = st.selectbox(
            "Deckgruppe auswählen",
            options=aggregate_options,
            index=default_index,
        )
    st.session_state["selected_aggregated_deck_name"] = selected_deck_name
    return str(selected_deck_name)


def _load_group_page_data(
    repository: DashboardRepository,
    selected_deck_name: str,
    start_date: object,
    end_date: object,
) -> dict[str, object]:
    return load_group_page_data(
        repository,
        selected_deck_name=selected_deck_name,
        start_date=start_date,
        end_date=end_date,
    )


def _render_overview_section(selected_aggregate: dict[str, object]) -> None:
    st.subheader(selected_aggregate["deck_name"])
    st.caption(
        "Der Kopfbereich kombiniert rohe Gruppen-Groesse mit normalisierten Vergleichswerten fuer Reichweite, Performance, Preisniveau und Recency."
    )

    _render_section_header(
        "🏆 Uebersicht",
        "Die wichtigsten Gruppenkennzahlen stehen zuerst im Fokus. Rohwerte, normalisierte Performance und Preisniveau werden bewusst getrennt dargestellt.",
    )

    overview_col_1, overview_col_2 = st.columns(2)
    _render_metric_group(
        overview_col_1,
        "Reichweite und Feld",
        [
            ("Decks absolut", str(int(selected_aggregate["deck_count"])), None),
            ("Turniere", str(int(selected_aggregate["tournament_count"])), None),
            ("Spieler", str(int(selected_aggregate["player_count"])), None),
            (
                "Meta-Anteil %",
                _format_percent(selected_aggregate.get("meta_share_pct")),
                None,
            ),
            (
                "Turnierabdeckung %",
                _format_percent(selected_aggregate.get("tournament_coverage_pct")),
                None,
            ),
            (
                "Diversitaet %",
                _format_ratio_percent(selected_aggregate.get("player_diversity_ratio")),
                None,
            ),
        ],
        columns=2,
    )
    _render_metric_group(
        overview_col_2,
        "Performance und Resultate",
        [
            (
                "Median Perzentil",
                _format_percent(selected_aggregate.get("median_placement_percentile")),
                None,
            ),
            (
                "Ø Perzentil",
                _format_percent(selected_aggregate.get("average_placement_percentile")),
                None,
            ),
            (
                "Top-25 %",
                _format_percent(selected_aggregate.get("top_25_finish_rate_pct")),
                None,
            ),
            (
                "Performance-IQR",
                _format_percent(selected_aggregate.get("placement_percentile_iqr")),
                None,
            ),
            (
                "Ø Platzierung",
                _format_number(selected_aggregate.get("average_placement")),
                None,
            ),
            (
                "30-Tage-Resultate %",
                _format_percent(selected_aggregate.get("recent_30d_result_share_pct")),
                None,
            ),
        ],
        columns=2,
    )

    detail_col_1, detail_col_2 = st.columns(2)
    _render_metric_group(
        detail_col_1,
        "Deckstruktur und Kosten",
        [
            (
                "Ø Teilnehmer",
                _format_number(selected_aggregate.get("average_participants_count")),
                None,
            ),
            (
                "Ø Main",
                _format_number(selected_aggregate.get("average_main_card_total")),
                None,
            ),
            (
                "Ø Extra",
                _format_number(selected_aggregate.get("average_extra_card_total")),
                None,
            ),
            (
                "Ø Side",
                _format_number(selected_aggregate.get("average_side_card_total")),
                None,
            ),
            (
                "Median Cardmarket €",
                _format_currency(
                    selected_aggregate.get("median_cardmarket_deck_price_eur"), "€"
                ),
                None,
            ),
            (
                "P25-P75 Cardmarket €",
                _format_cardmarket_range(selected_aggregate),
                None,
            ),
            (
                "Ø TCG Preis",
                _format_currency(selected_aggregate.get("average_tcg_price_usd"), "$"),
                None,
            ),
        ],
        columns=2,
    )
    _render_metric_group(
        detail_col_2,
        "Historie und Kontext",
        [
            (
                "Erstes Auftreten",
                str(selected_aggregate.get("first_seen_date") or "-"),
                None,
            ),
            (
                "Letztes Auftreten",
                str(selected_aggregate.get("last_seen_date") or "-"),
                None,
            ),
            (
                "Beste Platzierung",
                _format_number(selected_aggregate.get("best_placement")),
                None,
            ),
            (
                "Schlechteste Platzierung",
                _format_number(selected_aggregate.get("worst_placement")),
                None,
            ),
        ],
        columns=2,
    )


def _render_card_profile_section(
    group_role_benchmarks: list[dict[str, object]],
    deck_section_composition: list[dict[str, object]],
    aggregated_cards: dict[str, list[dict[str, object]]],
) -> None:
    st.divider()
    _render_section_header(
        "📋 Kartenprofil",
        "Zuerst die Gruppenzusammensetzung, darunter die konsolidierten Main-, Extra- und Side-Karten. Die Kartenlisten sind in Tabs getrennt, damit die Seite nicht in drei parallelen Volltabellen zerfaellt.",
    )
    st.markdown("**Profil-KPIs**")
    _render_group_profile_summary(group_role_benchmarks, aggregated_cards)

    st.markdown("**Deckbereich-Komposition**")
    st.caption(
        "Der erste Balken bezieht sich nur auf das Main Deck, der zweite nur auf das Side Deck. Innerhalb der Non-Engine werden `Handtraps` und `Boardbreaker` separat gezeigt; `Weitere Non-Engine` buendelt Floodgates, Protection, Draw Engine und unklare Faelle. Hauptengines werden weiter ueber Karten-Archetypes gebildet, deren Name fragmentweise in der Deckgruppe vorkommt."
    )
    _render_deck_section_share_chart(deck_section_composition)

    st.markdown("**Aggregierte Kartenliste**")
    main_tab, extra_tab, side_tab = st.tabs(["Main Deck", "Extra Deck", "Side Deck"])

    with main_tab:
        _render_aggregated_card_section(
            aggregated_cards["main"],
            section_label="Main Deck",
            columns_to_drop={"In Decks", "Gesamtkopien"},
            empty_message="Fuer das Main Deck konnten keine aggregierten Karten berechnet werden.",
        )

    with extra_tab:
        _render_aggregated_card_section(
            aggregated_cards["extra"],
            section_label="Extra Deck",
            columns_to_drop={"In Decks", "Gesamtkopien", "Klasse"},
            empty_message="Fuer das Extra Deck konnten keine aggregierten Karten berechnet werden.",
        )

    with side_tab:
        _render_aggregated_card_section(
            aggregated_cards["side"],
            section_label="Side Deck",
            columns_to_drop={"In Decks", "Gesamtkopien"},
            empty_message="Fuer das Side Deck konnten keine aggregierten Karten berechnet werden.",
        )


def _render_generic_cards_section(
    group_non_engine_cards: list[dict[str, object]],
    group_candidate_splash_cards: list[dict[str, object]],
) -> None:
    st.divider()
    _render_section_header(
        "🔍 Generische Karten",
        "Diese Analyse zeigt nur global als generisch erkannte Karten, deren Kennzahlen aber ausschliesslich auf der aktuell gewaehlten Deckgruppe basieren.",
    )
    with st.expander("Wie die Kennzahlen in dieser Sektion zu lesen sind"):
        st.markdown(
            "`Ø Main / Gruppendeck` und `Ø Side / Gruppendeck` mitteln ueber alle Decks der gewaehlten Gruppe, fehlende Vorkommen zaehlen also als 0. `Main >=1 %` und `Side >=1 %` zeigen den Anteil der Gruppendecks, in denen die Karte im jeweiligen Bereich mindestens einmal vorkommt. `Ø Kopien bei Nutzung` mittelt dagegen nur ueber Decks, die die Karte ueberhaupt spielen."
        )

    non_engine_tab, splash_tab = st.tabs(["Non-Engine", "Candidate Splash"])

    with non_engine_tab:
        _render_non_engine_table(
            group_non_engine_cards,
            "In dieser Deckgruppe wurden noch keine Karten als Non-Engine klassifiziert.",
        )

    with splash_tab:
        _render_non_engine_table(
            group_candidate_splash_cards,
            "In dieser Deckgruppe wurden noch keine Karten als Candidate Splash klassifiziert.",
        )


def _render_trend_section(deck_group_trend_rows: list[dict[str, object]]) -> None:
    st.divider()
    _render_section_header(
        "📈 Monatlicher Trend",
        "Diese optionale Sektion zeigt die Entwicklung der aktuell gewaehlten Deckgruppe ueber den gefilterten Zeitraum, ohne den Kopfbereich weiter aufzublaehen.",
    )
    _render_group_trend_section(deck_group_trend_rows)


def _render_deck_instances_section(
    selected_deck_name: str, deck_instances: list[dict[str, object]]
) -> None:
    st.divider()
    _render_section_header(
        "📋 Einzeldecks",
        "Am Ende stehen die konkreten Turnierlisten der Gruppe als Drilldown. Die Tabelle bleibt bewusst roh genug, um direkt zu Performance, Datum und Preis zu springen.",
    )
    control_col_1, control_col_2 = st.columns((1, 1))
    with control_col_1.container(border=True):
        st.markdown("**Sortierung**")
        deck_instance_sort_mode = st.selectbox(
            "Einzeldecks sortieren nach",
            options=[
                "Neueste Listen",
                "Bestes Platzierungs-Perzentil",
                "Niedrigste Cardmarket Summe",
                "Hoechste Cardmarket Summe",
            ],
            index=0,
        )
        st.caption(
            "Steuert nur die Reihenfolge der folgenden Listen, nicht die zugrunde liegende Filtermenge."
        )

    sorted_deck_instances = _sorted_deck_instances(
        deck_instances, deck_instance_sort_mode
    )
    prepared_deck_instances = _prepare_deck_instance_rows(sorted_deck_instances)

    deck_instance_option_ids = [
        int(row["deck_site_id"]) for row in sorted_deck_instances
    ]
    with control_col_2.container(border=True):
        st.markdown("**Decklisten-Drilldown**")
        if deck_instance_option_ids:
            if (
                st.session_state.get(DECKGROUP_DRILLDOWN_STATE_KEY)
                not in deck_instance_option_ids
            ):
                st.session_state[DECKGROUP_DRILLDOWN_STATE_KEY] = (
                    deck_instance_option_ids[0]
                )

            selected_drilldown_deck_id = st.selectbox(
                "Instanz fuer Decklisten-Drilldown",
                options=deck_instance_option_ids,
                format_func=lambda deck_id: _deck_instance_drilldown_label(
                    next(
                        row
                        for row in sorted_deck_instances
                        if int(row["deck_site_id"]) == int(deck_id)
                    )
                ),
                key=DECKGROUP_DRILLDOWN_STATE_KEY,
            )
            if st.button("Zur Deckliste"):
                _open_decklist_instance(
                    selected_deck_name, int(selected_drilldown_deck_id)
                )
        else:
            st.info("Keine Deckinstanzen im aktuellen Zeitraum verfuegbar.")

    st.caption(
        f"Konkrete Listen im aktiven Zeitraum: {len(deck_instances)}. Die Tabelle ist aktuell nach '{deck_instance_sort_mode}' geordnet."
    )
    st.dataframe(
        prepared_deck_instances,
        hide_index=True,
        width="stretch",
    )


def main() -> None:
    database_path = resolve_dashboard_db_path()
    repository = DashboardRepository(database_path)

    st.title("🔍 Deckgruppen Details")

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

    selected_deck_name = _render_selection_section(
        [str(row["deck_name"]) for row in aggregate_rows]
    )
    link_col_1, link_col_2 = st.columns((2, 3))
    link_col_1.markdown("**Deckgruppen Details**")
    if link_col_2.button("Deckbuilder fuer diese Deckgruppe oeffnen"):
        st.session_state[DECKBUILDER_DECK_GROUP_STATE_KEY] = selected_deck_name
        st.switch_page(str(DECKBUILDER_PAGE_PATH))

    page_data = _load_group_page_data(
        repository, selected_deck_name, start_date, end_date
    )
    selected_aggregate = page_data["selected_aggregate"]
    if selected_aggregate is None:
        st.error("Die ausgewählte Deckgruppe konnte nicht geladen werden.")
        st.stop()

    _render_overview_section(selected_aggregate)
    _render_card_profile_section(
        page_data["group_role_benchmarks"],
        page_data["deck_section_composition"],
        page_data["aggregated_cards"],
    )
    _render_generic_cards_section(
        page_data["group_non_engine_cards"],
        page_data["group_candidate_splash_cards"],
    )
    _render_trend_section(page_data["deck_group_trend_rows"])
    _render_deck_instances_section(selected_deck_name, page_data["deck_instances"])


main()
