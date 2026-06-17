from __future__ import annotations

from html import escape

import streamlit as st

from ygo_crawler.dashboard_cache import load_deck_summaries, load_selected_deck_data
from ygo_crawler.dashboard_filters import render_dashboard_date_filter
from ygo_crawler.dashboard_queries import DashboardRepository, resolve_dashboard_db_path

DECK_NAME_STATE_KEY = "decklisten_selected_deck_name"
DECK_INSTANCE_STATE_KEY = "decklisten_selected_deck_id"
QUERY_PARAM_DECK_NAME = "deck_name"
QUERY_PARAM_DECK_ID = "deck_id"


def _query_param_text(key: str) -> str | None:
    value = st.query_params.get(key)
    if value is None:
        return None
    if isinstance(value, list):
        return str(value[0]) if value else None
    value_text = str(value).strip()
    return value_text or None


def _query_param_int(key: str) -> int | None:
    value_text = _query_param_text(key)
    if value_text is None:
        return None
    try:
        return int(value_text)
    except ValueError:
        return None


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
        "Komponente": st.column_config.TextColumn("Komponente", width="small"),
        "Rolle": st.column_config.TextColumn("Rolle", width="medium"),
        "Cardmarket €": st.column_config.NumberColumn("Cardmarket €", format="%.2f"),
        "Gesamt €": st.column_config.NumberColumn("Gesamt €", format="%.2f"),
        "Kostenklasse": st.column_config.TextColumn("Kostenklasse", width="small"),
    }


def _sorted_card_rows(
    rows: list[dict[str, object]], sort_mode: str
) -> list[dict[str, object]]:
    if sort_mode == "Gesamtpreis":
        return sorted(
            rows,
            key=lambda row: (
                row.get("Gesamt €") is None,
                -(float(row["Gesamt €"]) if row.get("Gesamt €") is not None else 0.0),
                str(row["Karte"]),
            ),
        )
    if sort_mode == "Rolle":
        component_order = {
            "Engine": 1,
            "Non-Engine": 2,
            "Extra Deck": 3,
        }
        role_order = {
            "Engine": 1,
            "Handtrap": 2,
            "Boardbreaker": 3,
            "Floodgate": 4,
            "Protection": 5,
            "Draw Engine": 6,
            "Weitere Non-Engine": 7,
            "-": 8,
        }
        return sorted(
            rows,
            key=lambda row: (
                component_order.get(str(row.get("Komponente") or ""), 99),
                role_order.get(str(row.get("Rolle") or "-"), 99),
                str(row["Karte"]),
            ),
        )
    return sorted(rows, key=lambda row: str(row["Karte"]))


def _prepare_card_table_rows(
    rows: list[dict[str, object]],
    *,
    show_detailed_columns: bool,
    sort_mode: str,
) -> list[dict[str, object]]:
    normalized_rows: list[dict[str, object]] = []
    for row in _sorted_card_rows(rows, sort_mode):
        normalized_row = dict(row)
        if normalized_row.get("Rolle") is None:
            normalized_row["Rolle"] = "-"
        normalized_rows.append(normalized_row)

    if show_detailed_columns:
        return _drop_columns(normalized_rows, {"Passcode"})
    return _drop_columns(
        normalized_rows,
        {"Passcode", "Komponente", "Rolle", "Cardmarket €", "Gesamt €", "Kostenklasse"},
    )


def _format_count(value: object) -> str:
    if value is None:
        return "-"
    numeric_value = float(value)
    if numeric_value.is_integer():
        return str(int(numeric_value))
    return f"{numeric_value:.1f}"


def _format_percent(value: object) -> str:
    if value is None:
        return "-"
    return f"{float(value):.1f}%"


def _format_delta_pp(value: object) -> str | None:
    if value is None:
        return None
    return f"{float(value):+.1f} pp"


def _format_eur(value: object) -> str:
    if value is None:
        return "-"
    return f"EUR {float(value):.2f}"


def _format_text(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, str) and not value.strip():
        return "-"
    return str(value)


def _format_side_profile_value(copies: object, share_pct: object) -> str:
    if copies is None and share_pct is None:
        return "-"
    return f"{_format_count(copies)} | {_format_percent(share_pct)}"


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


def _render_context_panel(
    column: st.delta_generator.DeltaGenerator,
    title: str,
    rows: list[tuple[str, str]],
) -> None:
    with column.container(border=True):
        st.markdown(f"**{title}**")
        for label, value in rows:
            st.markdown(f"**{label}:** {value}")


def _render_badge_row(items: list[tuple[str, str]]) -> None:
    badge_html = "".join(
        (
            "<span style='display:inline-flex;align-items:center;gap:0.35rem;padding:0.32rem 0.72rem;"
            "margin:0 0.45rem 0.45rem 0;border:1px solid rgba(49, 51, 63, 0.20);border-radius:999px;"
            "background:rgba(49, 51, 63, 0.06);font-size:0.9rem;'>"
            f"<span style='font-weight:600'>{escape(label)}</span>"
            f"<span>{escape(value)}</span>"
            "</span>"
        )
        for label, value in items
    )
    st.markdown(badge_html, unsafe_allow_html=True)


def _render_section_header(title: str, description: str | None = None) -> None:
    st.subheader(title)
    if description:
        st.caption(description)


def _render_deck_context(selected_deck: dict[str, object]) -> None:
    deck_url = selected_deck.get("deck_url")
    detail_col_1, detail_col_2, detail_col_3 = st.columns(3)
    _render_context_panel(
        detail_col_1,
        "Turnier",
        [
            ("Turnier", _format_text(selected_deck.get("tournament_name"))),
            ("Datum", _format_text(selected_deck.get("tournament_date"))),
            ("Tier", _format_text(selected_deck.get("tier"))),
        ],
    )
    _render_context_panel(
        detail_col_2,
        "Personen",
        [
            ("Spieler", _format_text(selected_deck.get("player_name"))),
            ("Autor", _format_text(selected_deck.get("author_name"))),
            ("Archetyp", _format_text(selected_deck.get("archetype_text"))),
        ],
    )
    _render_context_panel(
        detail_col_3,
        "Quelle",
        [
            ("Deckname", _format_text(selected_deck.get("deck_name"))),
            ("Land", _format_text(selected_deck.get("country"))),
            ("Deck URL", f"[Oeffnen]({deck_url})" if deck_url else "-"),
        ],
    )


def _deck_instance_label(row: dict[str, object]) -> str:
    label_parts = [
        str(row["placement"]),
        f"{row['tournament_name']} ({row['tournament_date']})",
    ]
    player_name = row.get("player_name")
    if player_name:
        label_parts.append(str(player_name))
    return " | ".join(label_parts)


def _sum_component_copies(rows: list[dict[str, object]], component_type: str) -> float:
    return sum(
        float(row["copies_in_section"])
        for row in rows
        if str(row["component_type"]) == component_type
    )


def _render_kpi_header(
    selected_deck: dict[str, object], role_metrics: dict[str, object]
) -> None:
    group_deck_count = role_metrics.get("group_deck_count")
    if group_deck_count is not None:
        st.caption(
            f"Deltas zeigen die Abweichung zum Deckgruppen-Mittel im aktiven Zeitraum auf Basis von {int(group_deck_count)} Listen."
        )
    else:
        st.caption(
            "Deltas zeigen die Abweichung zum Deckgruppen-Mittel im aktiven Zeitraum."
        )

    top_row_col_1, top_row_col_2 = st.columns((1.05, 1.2))
    _render_metric_group(
        top_row_col_1,
        "Turnierresultat",
        [
            ("Platzierung", str(selected_deck["placement"]), None),
            (
                "Perzentil",
                _format_percent(selected_deck.get("placement_percentile")),
                None,
            ),
            (
                "Teilnehmer",
                _format_count(selected_deck.get("participants_count")),
                None,
            ),
            ("Main Slots", _format_count(role_metrics.get("main_card_total")), None),
        ],
        columns=2,
    )
    _render_metric_group(
        top_row_col_2,
        "Deckprofil",
        [
            (
                "Main Engine",
                _format_percent(role_metrics.get("main_engine_share_pct")),
                _format_delta_pp(
                    role_metrics.get("delta_vs_group_main_engine_share_pct")
                ),
            ),
            (
                "Main Non-Engine",
                _format_percent(role_metrics.get("main_non_engine_share_pct")),
                _format_delta_pp(
                    role_metrics.get("delta_vs_group_main_non_engine_share_pct")
                ),
            ),
            (
                "Side Non-Engine",
                _format_percent(role_metrics.get("side_non_engine_share_pct")),
                _format_delta_pp(
                    role_metrics.get("delta_vs_group_side_non_engine_share_pct")
                ),
            ),
        ],
        columns=2,
    )

    second_row_col_1, second_row_col_2 = st.columns((1.25, 1.05))
    _render_metric_group(
        second_row_col_1,
        "Deckkosten",
        [
            (
                "Gesamt EUR",
                _format_eur(selected_deck.get("cardmarket_deck_price_eur")),
                None,
            ),
            (
                "Main EUR",
                _format_eur(role_metrics.get("main_cardmarket_cost_eur")),
                None,
            ),
            (
                "Extra EUR",
                _format_eur(role_metrics.get("extra_cardmarket_cost_eur")),
                None,
            ),
            (
                "Side EUR",
                _format_eur(role_metrics.get("side_cardmarket_cost_eur")),
                None,
            ),
        ],
        columns=2,
    )
    _render_metric_group(
        second_row_col_2,
        "Side-Profil",
        [
            (
                "Handtraps Side",
                _format_side_profile_value(
                    role_metrics.get("side_handtrap_copies"),
                    role_metrics.get("side_handtrap_share_pct"),
                ),
                _format_delta_pp(
                    role_metrics.get("delta_vs_group_side_handtrap_share_pct")
                ),
            ),
            (
                "Boardbreaker Side",
                _format_side_profile_value(
                    role_metrics.get("side_boardbreaker_copies"),
                    role_metrics.get("side_boardbreaker_share_pct"),
                ),
                _format_delta_pp(
                    role_metrics.get("delta_vs_group_side_boardbreaker_share_pct")
                ),
            ),
            (
                "Weitere NE Side",
                _format_side_profile_value(
                    role_metrics.get("side_non_engine_other_copies"),
                    role_metrics.get("side_non_engine_other_share_pct"),
                ),
                _format_delta_pp(
                    role_metrics.get("delta_vs_group_side_non_engine_other_share_pct")
                ),
            ),
        ],
        columns=2,
    )

    role_cost_container = st.container()
    _render_metric_group(
        role_cost_container,
        "Rollenkosten",
        [
            (
                "Engine",
                _format_eur(role_metrics.get("engine_cardmarket_cost_eur")),
                None,
            ),
            (
                "Handtraps",
                _format_eur(role_metrics.get("handtrap_cardmarket_cost_eur")),
                None,
            ),
            (
                "Boardbreaker",
                _format_eur(role_metrics.get("boardbreaker_cardmarket_cost_eur")),
                None,
            ),
            (
                "Weitere NE",
                _format_eur(role_metrics.get("non_engine_other_cardmarket_cost_eur")),
                None,
            ),
        ],
        columns=4,
        description="Rollenpreise beziehen sich auf Main und Side; das Extra Deck fliesst hier bewusst nicht ein.",
    )


def _component_color(component_type: str, component_index: int) -> str:
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


def _component_color_scale(
    rows: list[dict[str, object]],
) -> tuple[list[str], list[str]]:
    color_range: list[str] = []
    domain: list[str] = []
    engine_index = 0
    seen_components: set[str] = set()

    for row in sorted(
        rows,
        key=lambda item: (int(item.get("type_rank", 99)), str(item["component_name"])),
    ):
        component_name = str(row["component_name"])
        component_type = str(row["component_type"])
        if component_name in seen_components:
            continue
        domain.append(component_name)
        color_range.append(_component_color(component_type, engine_index))
        seen_components.add(component_name)
        if component_type == "main_engine":
            engine_index += 1

    return (domain, color_range)


def _render_deck_section_share_chart(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info(
            "Fuer dieses Deck konnte keine Deckbereich-Komposition berechnet werden."
        )
        return

    chart_rows: list[dict[str, object]] = []
    domain, color_range = _component_color_scale(rows)
    for sort_index, row in enumerate(rows):
        component_name = str(row["component_name"])
        chart_rows.append(
            {
                "Deckbereich": (
                    "Main Deck" if str(row["section"]) == "main" else "Side Deck"
                ),
                "Baustein": component_name,
                "Anteil %": float(row["share_pct"]),
                "Kopien im Bereich": float(row["copies_in_section"]),
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
                    "axis": {"title": "Anteil am Deckbereich (%)"},
                },
                "color": {
                    "field": "Baustein",
                    "type": "nominal",
                    "scale": {"domain": domain, "range": color_range},
                    "legend": {"title": None, "orient": "bottom"},
                },
                "order": {"field": "Sortierung", "type": "quantitative"},
                "tooltip": [
                    {"field": "Deckbereich", "type": "nominal"},
                    {"field": "Baustein", "type": "nominal"},
                    {"field": "Anteil %", "type": "quantitative", "format": ".1f"},
                    {
                        "field": "Kopien im Bereich",
                        "type": "quantitative",
                        "format": ".0f",
                    },
                ],
            },
        },
        width="stretch",
    )


def _render_role_cost_distribution_chart(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info(
            "Fuer dieses Deck konnten keine rollenbasierten Cardmarket-Kosten berechnet werden."
        )
        return

    domain, color_range = _component_color_scale(rows)
    chart_rows = [
        {
            "Bereich": "Main + Side",
            "Baustein": str(row["component_name"]),
            "Anteil %": float(row["share_pct"]),
            "Cardmarket EUR": float(row["cardmarket_cost_eur"]),
            "Sortierung": int(row["type_rank"]),
        }
        for row in rows
    ]

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": 120,
            "mark": {"type": "bar", "tooltip": True},
            "encoding": {
                "y": {
                    "field": "Bereich",
                    "type": "nominal",
                    "axis": {"title": None, "labelAngle": 0},
                },
                "x": {
                    "field": "Anteil %",
                    "type": "quantitative",
                    "stack": "zero",
                    "axis": {"title": "Anteil an den Main-und-Side-Kosten (%)"},
                },
                "color": {
                    "field": "Baustein",
                    "type": "nominal",
                    "scale": {"domain": domain, "range": color_range},
                    "legend": {"title": None, "orient": "bottom"},
                },
                "order": {"field": "Sortierung", "type": "quantitative"},
                "tooltip": [
                    {"field": "Baustein", "type": "nominal"},
                    {
                        "field": "Cardmarket EUR",
                        "type": "quantitative",
                        "format": ".2f",
                    },
                    {"field": "Anteil %", "type": "quantitative", "format": ".1f"},
                ],
            },
        },
        width="stretch",
    )


def _render_deck_vs_group_comparison_chart(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info(
            "Fuer dieses Deck konnte kein Vergleich zur Deckgruppe berechnet werden."
        )
        return

    domain, color_range = _component_color_scale(rows)
    chart_rows: list[dict[str, object]] = []
    section_labels = {"main": "Main Deck", "side": "Side Deck"}
    scope_labels = {
        "deck": "Ausgewaehltes Deck",
        "group": "Deckgruppen-Mittel",
    }
    sort_order = {
        ("main", "deck"): 1,
        ("main", "group"): 2,
        ("side", "deck"): 3,
        ("side", "group"): 4,
    }

    for row in rows:
        section = str(row["section"])
        scope = str(row["scope"])
        chart_rows.append(
            {
                "Vergleich": f"{section_labels.get(section, section)} | {scope_labels.get(scope, scope)}",
                "Baustein": str(row["component_name"]),
                "Anteil %": float(row["share_pct"]),
                "Kopien pro Deck": float(row["copies_per_deck"]),
                "Sortierung": int(row["type_rank"]),
                "Vergleichsreihenfolge": sort_order.get((section, scope), 99),
            }
        )

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": 220,
            "mark": {"type": "bar", "tooltip": True},
            "encoding": {
                "y": {
                    "field": "Vergleich",
                    "type": "nominal",
                    "axis": {"title": None, "labelAngle": 0},
                    "sort": {
                        "field": "Vergleichsreihenfolge",
                        "op": "min",
                        "order": "ascending",
                    },
                },
                "x": {
                    "field": "Anteil %",
                    "type": "quantitative",
                    "stack": "zero",
                    "axis": {"title": "Anteil am jeweiligen Deckbereich (%)"},
                },
                "color": {
                    "field": "Baustein",
                    "type": "nominal",
                    "scale": {"domain": domain, "range": color_range},
                    "legend": {"title": None, "orient": "bottom"},
                },
                "order": {"field": "Sortierung", "type": "quantitative"},
                "tooltip": [
                    {"field": "Vergleich", "type": "nominal"},
                    {"field": "Baustein", "type": "nominal"},
                    {"field": "Anteil %", "type": "quantitative", "format": ".1f"},
                    {
                        "field": "Kopien pro Deck",
                        "type": "quantitative",
                        "format": ".2f",
                    },
                ],
            },
        },
        width="stretch",
    )


def _render_copy_count_histogram(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info("Fuer dieses Deck konnte keine Copy-Count-Verteilung berechnet werden.")
        return

    st.vega_lite_chart(
        {
            "data": {"values": rows},
            "height": 220,
            "mark": {
                "type": "bar",
                "cornerRadiusTopLeft": 6,
                "cornerRadiusTopRight": 6,
                "tooltip": True,
            },
            "encoding": {
                "x": {
                    "field": "label",
                    "type": "ordinal",
                    "axis": {"title": "Kopien im Main Deck"},
                    "sort": ["1x", "2x", "3x"],
                },
                "y": {
                    "field": "card_count",
                    "type": "quantitative",
                    "axis": {"title": "Unterschiedliche Main-Deck-Karten"},
                },
                "color": {
                    "field": "label",
                    "type": "nominal",
                    "legend": None,
                    "scale": {
                        "domain": ["1x", "2x", "3x"],
                        "range": ["#A8DADC", "#457B9D", "#1D3557"],
                    },
                },
                "tooltip": [
                    {"field": "label", "type": "nominal", "title": "Copy Count"},
                    {
                        "field": "card_count",
                        "type": "quantitative",
                        "format": ".0f",
                        "title": "Karten",
                    },
                    {
                        "field": "share_pct",
                        "type": "quantitative",
                        "format": ".1f",
                        "title": "Anteil %",
                    },
                ],
            },
        },
        width="stretch",
    )


def _render_deck_section_heatmap(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info("Fuer dieses Deck konnten keine Heatmap-Daten berechnet werden.")
        return

    chart_rows = [
        {
            "Deckbereich": str(row["section_label"]),
            "Karte": str(row["card_name"]),
            "Kopien": int(row["quantity"]),
            "Kopien Label": str(row["quantity_label"]),
            "Komponente": row.get("component_label") or "-",
            "Rolle": row.get("role_label") or "-",
            "Kostenklasse": row.get("cost_bucket") or "-",
            "Cardmarket EUR": row.get("cardmarket_price_eur"),
            "Gesamt EUR": row.get("total_cardmarket_price_eur"),
        }
        for row in rows
    ]

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": {"step": 20},
            "mark": {"type": "rect", "tooltip": True, "cornerRadius": 3},
            "encoding": {
                "x": {
                    "field": "Deckbereich",
                    "type": "nominal",
                    "sort": ["Main Deck", "Extra Deck", "Side Deck"],
                    "axis": {"title": None, "labelAngle": 0},
                },
                "y": {
                    "field": "Karte",
                    "type": "ordinal",
                    "sort": "-x",
                    "axis": {"title": None},
                },
                "color": {
                    "field": "Kopien",
                    "type": "quantitative",
                    "scale": {
                        "domain": [1, 3],
                        "range": ["#D8F3DC", "#40916C", "#1B4332"],
                    },
                    "legend": {"title": "Kopien"},
                },
                "tooltip": [
                    {"field": "Deckbereich", "type": "nominal"},
                    {"field": "Karte", "type": "nominal"},
                    {"field": "Kopien Label", "type": "nominal", "title": "Kopien"},
                    {"field": "Komponente", "type": "nominal"},
                    {"field": "Rolle", "type": "nominal"},
                    {"field": "Kostenklasse", "type": "nominal"},
                    {
                        "field": "Cardmarket EUR",
                        "type": "quantitative",
                        "format": ".2f",
                    },
                    {"field": "Gesamt EUR", "type": "quantitative", "format": ".2f"},
                ],
            },
            "config": {
                "view": {"stroke": None},
            },
        },
        width="stretch",
    )


def _render_empty_state(
    repository: DashboardRepository, start_date: object, end_date: object
) -> None:
    database_summary = repository.get_database_summary(start_date, end_date)
    st.warning(
        "Es sind noch keine Decklisten gespeichert. Deshalb kann auf dieser Seite aktuell keine Deckliste angezeigt werden."
    )

    info_col_1, info_col_2, info_col_3 = st.columns(3)
    info_col_1.metric("Turniere", database_summary.tournaments)
    info_col_2.metric("Entries", database_summary.entries)
    info_col_3.metric("Skip-Quellen", database_summary.skipped_sources)

    tournaments = repository.list_tournaments(
        limit=10, start_date=start_date, end_date=end_date
    )
    if tournaments:
        st.markdown("**Gespeicherte Turniere**")
        st.dataframe(
            _drop_columns(tournaments, {"country"}), hide_index=True, width="stretch"
        )

    skip_summary = repository.list_skip_reason_summary()
    if skip_summary:
        st.markdown("**Skip-Gründe**")
        st.dataframe(skip_summary, hide_index=True, width="stretch")

    skipped_sources = repository.list_skipped_sources(limit=20)
    if skipped_sources:
        with st.expander("Verworfene Quellen anzeigen"):
            st.dataframe(skipped_sources, hide_index=True, width="stretch")


def _build_deck_lookups(
    deck_rows: list[dict[str, object]],
) -> tuple[dict[str, list[dict[str, object]]], dict[int, dict[str, object]], list[str]]:
    deck_rows_by_name: dict[str, list[dict[str, object]]] = {}
    deck_row_by_id: dict[int, dict[str, object]] = {}
    for deck_row in deck_rows:
        deck_name = str(deck_row["deck_name"])
        deck_rows_by_name.setdefault(deck_name, []).append(deck_row)
        deck_row_by_id[int(deck_row["deck_site_id"])] = deck_row
    return deck_rows_by_name, deck_row_by_id, list(deck_rows_by_name.keys())


def _initialize_selection_state(
    deck_rows_by_name: dict[str, list[dict[str, object]]],
    deck_row_by_id: dict[int, dict[str, object]],
    deck_name_options: list[str],
) -> None:
    query_param_deck_name = _query_param_text(QUERY_PARAM_DECK_NAME)
    query_param_deck_id = _query_param_int(QUERY_PARAM_DECK_ID)
    selected_deck_name = st.session_state.get(DECK_NAME_STATE_KEY)
    selected_deck_id = st.session_state.get(DECK_INSTANCE_STATE_KEY)

    if query_param_deck_id in deck_row_by_id:
        query_param_deck_name = str(
            deck_row_by_id[int(query_param_deck_id)]["deck_name"]
        )
        if (
            query_param_deck_name != selected_deck_name
            or query_param_deck_id != selected_deck_id
        ):
            st.session_state[DECK_NAME_STATE_KEY] = query_param_deck_name
            st.session_state[DECK_INSTANCE_STATE_KEY] = int(query_param_deck_id)
            selected_deck_name = query_param_deck_name
            selected_deck_id = int(query_param_deck_id)
    elif (
        query_param_deck_name in deck_rows_by_name
        and query_param_deck_name != selected_deck_name
    ):
        st.session_state[DECK_NAME_STATE_KEY] = query_param_deck_name
        st.session_state.pop(DECK_INSTANCE_STATE_KEY, None)
        selected_deck_name = query_param_deck_name
        selected_deck_id = None

    if selected_deck_id not in deck_row_by_id:
        st.session_state.pop(DECK_INSTANCE_STATE_KEY, None)
        selected_deck_id = None

    if selected_deck_name not in deck_rows_by_name:
        if selected_deck_id is not None:
            selected_deck_name = str(deck_row_by_id[int(selected_deck_id)]["deck_name"])
        else:
            selected_deck_name = deck_name_options[0]
        st.session_state[DECK_NAME_STATE_KEY] = selected_deck_name


def _render_selection_section(
    deck_rows_by_name: dict[str, list[dict[str, object]]],
    deck_row_by_id: dict[int, dict[str, object]],
    deck_name_options: list[str],
) -> tuple[str, int, list[dict[str, object]]]:
    _render_section_header(
        "📋 Auswahl",
        "Waehle zuerst eine Deckgruppe und dann die konkrete Turnierliste. Die nachfolgenden Kennzahlen und Plots beziehen sich immer auf diese eine Liste.",
    )

    selection_container = st.container(border=True)
    with selection_container:
        selection_col_1, selection_col_2, selection_col_3 = st.columns((1, 2, 0.9))
        selected_deck_name = selection_col_1.selectbox(
            "Deckname auswählen",
            options=deck_name_options,
            key=DECK_NAME_STATE_KEY,
        )

        filtered_deck_rows = deck_rows_by_name[selected_deck_name]
        filtered_deck_ids = [int(row["deck_site_id"]) for row in filtered_deck_rows]
        if st.session_state.get(DECK_INSTANCE_STATE_KEY) not in filtered_deck_ids:
            st.session_state[DECK_INSTANCE_STATE_KEY] = filtered_deck_ids[0]

        filtered_option_labels = {
            int(row["deck_site_id"]): _deck_instance_label(row)
            for row in filtered_deck_rows
        }
        selected_deck_id = selection_col_2.selectbox(
            "Liste oder Turnierinstanz auswählen",
            options=filtered_deck_ids,
            format_func=lambda deck_id: filtered_option_labels[deck_id],
            key=DECK_INSTANCE_STATE_KEY,
        )

        with selection_col_3.container(border=True):
            st.markdown("**Auswahlkontext**")
            st.markdown(f"**Listen im Zeitraum:** {len(filtered_deck_rows)}")
            st.markdown(
                f"**Aktive Liste:** {_format_text(deck_row_by_id[int(selected_deck_id)].get('placement'))}"
            )

    if _query_param_text(QUERY_PARAM_DECK_NAME) != selected_deck_name:
        st.query_params[QUERY_PARAM_DECK_NAME] = selected_deck_name
    if _query_param_int(QUERY_PARAM_DECK_ID) != int(selected_deck_id):
        st.query_params[QUERY_PARAM_DECK_ID] = str(int(selected_deck_id))

    st.caption(
        f"Im aktiven Zeitraum sind fuer {selected_deck_name} {len(filtered_deck_rows)} konkrete Listen verfuegbar."
    )
    return selected_deck_name, int(selected_deck_id), filtered_deck_rows


def _load_selected_deck_data(
    repository: DashboardRepository,
    selected_deck_id: int,
    start_date: object,
    end_date: object,
) -> dict[str, object]:
    return load_selected_deck_data(
        repository,
        selected_deck_id=selected_deck_id,
        start_date=start_date,
        end_date=end_date,
    )


def _render_selected_deck_header(
    selected_deck: dict[str, object],
    role_metrics: dict[str, object],
) -> None:
    st.divider()
    _render_section_header(
        str(selected_deck["deck_name"]),
        "Basisdaten und normalisierte Kennzahlen der gewaehlten Turnierliste.",
    )
    _render_kpi_header(selected_deck, role_metrics)
    _render_deck_context(selected_deck)


def _render_analysis_section(
    deck_section_composition: list[dict[str, object]],
    deck_vs_group_comparison: list[dict[str, object]],
    role_cost_distribution: list[dict[str, object]],
    copy_count_histogram: list[dict[str, object]],
    deck_heatmap_rows: list[dict[str, object]],
) -> None:
    st.divider()
    _render_section_header(
        "🔍 Analyse",
        "Slot-Verteilungen, Kostenprofile, Vergleich zur Deckgruppe und Expertensicht sind in getrennte Arbeitsbereiche aufgeteilt.",
    )

    analysis_tab_1, analysis_tab_2, analysis_tab_3 = st.tabs(
        ["Verteilungen", "Vergleich", "Expertensicht"]
    )

    with analysis_tab_1:
        st.markdown("**Slot-Verteilung nach Deckbereich**")
        st.caption(
            "Der Plot zeigt Main Deck und Side Deck des ausgewaehlten Decks separat. Hauptengines werden ueber Karten-Archetypes gebildet, deren Name fragmentweise im Decknamen vorkommt. Innerhalb der Non-Engine werden Handtraps, Boardbreaker und Weitere Non-Engine getrennt ausgewiesen."
        )
        _render_deck_section_share_chart(deck_section_composition)

        plot_col_1, plot_col_2 = st.columns((2, 1))
        with plot_col_1:
            st.markdown("**Kostenverteilung nach Rolle**")
            st.caption(
                "Der gestapelte Balken zeigt die Cardmarket-Verteilung ueber Engine, Handtraps, Boardbreaker und Weitere Non-Engine fuer Main und Side zusammen."
            )
            _render_role_cost_distribution_chart(role_cost_distribution)

        with plot_col_2:
            st.markdown("**Copy-Count im Main Deck**")
            st.caption(
                "Das Histogramm zaehlt, wie viele unterschiedliche Main-Deck-Karten als 1-of, 2-of oder 3-of gespielt werden."
            )
            _render_copy_count_histogram(copy_count_histogram)

    with analysis_tab_2:
        st.markdown("**Deck versus Deckgruppe**")
        st.caption(
            "Der Vergleichsplot stellt Main Deck und Side Deck des ausgewaehlten Decks direkt dem Mittelwert aller Listen derselben Deckgruppe gegenueber."
        )
        _render_deck_vs_group_comparison_chart(deck_vs_group_comparison)

    with analysis_tab_3:
        st.markdown("**Heatmap nach Karte und Deckbereich**")
        st.caption(
            "Die Expertensicht legt pro Karte und Deckbereich die gespielte Kopienzahl ueber Farbe offen. Tooltips zeigen zusaetzlich Rolle, Komponente und Cardmarket-Kontext."
        )
        _render_deck_section_heatmap(deck_heatmap_rows)


def _render_card_list_section(
    selected_deck: dict[str, object],
    role_metrics: dict[str, object],
    deck_section_composition: list[dict[str, object]],
    deck_cards: dict[str, list[dict[str, object]]],
) -> None:
    st.divider()
    _render_section_header(
        "📋 Kartenlisten",
        "Die Badge-Zeile fasst Sofortwerte zusammen. Darunter kannst du zwischen kompakter und erweiterter Tabellensicht sowie verschiedenen Sortierungen wechseln.",
    )

    cards_summary_col, cards_control_col = st.columns((1.7, 1))
    with cards_summary_col.container(border=True):
        st.markdown("**Sofortwerte**")
        _render_badge_row(
            [
                ("Main", _format_count(role_metrics.get("main_card_total"))),
                (
                    "Handtraps",
                    _format_count(
                        _sum_component_copies(
                            deck_section_composition, "non_engine_handtrap"
                        )
                    ),
                ),
                (
                    "Boardbreaker",
                    _format_count(
                        _sum_component_copies(
                            deck_section_composition, "non_engine_boardbreaker"
                        )
                    ),
                ),
                (
                    "Cardmarket",
                    _format_eur(selected_deck.get("cardmarket_deck_price_eur")),
                ),
                ("1-of", _format_count(role_metrics.get("main_one_of_count"))),
                ("2-of", _format_count(role_metrics.get("main_two_of_count"))),
                ("3-of", _format_count(role_metrics.get("main_three_of_count"))),
            ]
        )

    with cards_control_col.container(border=True):
        st.markdown("**Tabellenansicht**")
        table_control_col_1, table_control_col_2 = st.columns((1, 1))
        show_detailed_card_tables = table_control_col_1.toggle("Erweitert", value=False)
        table_sort_mode = table_control_col_2.selectbox(
            "Sortierung",
            options=["Kartenname", "Gesamtpreis", "Rolle"],
            index=0,
        )
        st.caption(
            "Erweitert blendet Komponente, Rolle, Cardmarket-Stueckpreis, Gesamtpreis und Kostenklasse ein. Die Rollensortierung gruppiert Engine, Non-Engine und Extra Deck zuerst grob vor."  # noqa: E501
        )

    main_tab, extra_tab, side_tab = st.tabs(["Main Deck", "Extra Deck", "Side Deck"])

    with main_tab:
        st.dataframe(
            _prepare_card_table_rows(
                deck_cards["main"],
                show_detailed_columns=show_detailed_card_tables,
                sort_mode=table_sort_mode,
            ),
            hide_index=True,
            width="stretch",
            column_config=_card_table_config(),
        )

    with extra_tab:
        st.dataframe(
            _prepare_card_table_rows(
                deck_cards["extra"],
                show_detailed_columns=show_detailed_card_tables,
                sort_mode=table_sort_mode,
            ),
            hide_index=True,
            width="stretch",
            column_config=_card_table_config(),
        )

    with side_tab:
        st.dataframe(
            _prepare_card_table_rows(
                deck_cards["side"],
                show_detailed_columns=show_detailed_card_tables,
                sort_mode=table_sort_mode,
            ),
            hide_index=True,
            width="stretch",
            column_config=_card_table_config(),
        )


def main() -> None:
    database_path = resolve_dashboard_db_path()
    repository = DashboardRepository(database_path)

    st.title("📋 Decklisten")

    status_message = repository.status_message()
    if status_message is not None:
        st.warning(status_message)
        st.stop()

    start_date, end_date = render_dashboard_date_filter(repository)
    deck_rows = load_deck_summaries(
        repository, limit=2000, start_date=start_date, end_date=end_date
    )
    if not deck_rows:
        _render_empty_state(repository, start_date, end_date)
        st.stop()

    deck_rows_by_name, deck_row_by_id, deck_name_options = _build_deck_lookups(
        deck_rows
    )
    _initialize_selection_state(deck_rows_by_name, deck_row_by_id, deck_name_options)
    _, selected_deck_id, _ = _render_selection_section(
        deck_rows_by_name, deck_row_by_id, deck_name_options
    )

    page_data = _load_selected_deck_data(
        repository, selected_deck_id, start_date, end_date
    )
    selected_deck = page_data["selected_deck"]
    role_metrics = page_data["role_metrics"]

    if selected_deck is None or role_metrics is None:
        st.error("Das ausgewaehlte Deck konnte nicht geladen werden.")
        st.stop()

    _render_selected_deck_header(selected_deck, role_metrics)
    _render_analysis_section(
        page_data["deck_section_composition"],
        page_data["deck_vs_group_comparison"],
        page_data["role_cost_distribution"],
        page_data["copy_count_histogram"],
        page_data["deck_heatmap_rows"],
    )
    _render_card_list_section(
        selected_deck,
        role_metrics,
        page_data["deck_section_composition"],
        page_data["deck_cards"],
    )


main()
