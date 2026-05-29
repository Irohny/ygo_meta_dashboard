from __future__ import annotations

from pathlib import Path
from statistics import median

import streamlit as st

from ygo_crawler.dashboard_filters import render_dashboard_date_filter
from ygo_crawler.dashboard_queries import DashboardRepository, resolve_dashboard_db_path

DECKGROUP_STATE_KEY = "selected_aggregated_deck_name"
DECKGROUP_PAGE_PATH = Path(__file__).with_name("3_Deckgruppen_Details.py")
CARD_DRILLDOWN_STATE_KEY = "non_engine_selected_card_label"
CARD_GROUP_DRILLDOWN_STATE_KEY = "non_engine_selected_group_name"


def _format_percent(value: object) -> str:
    if value is None:
        return "-"
    return f"{float(value):.1f}%"


def _format_currency(value: object) -> str:
    if value is None:
        return "-"
    return f"EUR {float(value):.2f}"


def _format_delta_pp(value: object) -> str:
    if value is None:
        return "-"
    return f"{float(value):+.2f} pp"


def _format_count(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    numeric_value = float(value)
    if numeric_value.is_integer():
        return str(int(numeric_value))
    return f"{numeric_value:.1f}"


def _section_header(title: str, description: str | None = None) -> None:
    st.subheader(title)
    if description:
        st.caption(description)


def _classification_label(classification: str) -> str:
    return "Candidate Splash" if classification == "candidate_splash" else "Non-Engine"


def _role_color(role_label: str) -> str:
    palette = {
        "Handtrap": "#E76F51",
        "Boardbreaker": "#F4A261",
        "Protection": "#2A9D8F",
        "Floodgate": "#6D597A",
        "Draw Engine": "#457B9D",
        "Weitere Non-Engine": "#E9C46A",
        "-": "#8E9AAF",
    }
    return palette.get(role_label, "#8E9AAF")


def _usage_profile_label(main_presence_pct: object, side_presence_pct: object) -> str:
    main_presence = float(main_presence_pct or 0.0)
    side_presence = float(side_presence_pct or 0.0)
    if main_presence <= 0.0 and side_presence <= 0.0:
        return "-"
    if main_presence >= side_presence + 15.0:
        return "Main-first"
    if side_presence >= main_presence + 15.0:
        return "Side-first"
    return "Hybrid"


def _expected_deck_cost_contribution(row: dict[str, object]) -> float | None:
    price = row.get("average_cardmarket_price_eur")
    if price is None:
        return None
    average_main_copies = float(row.get("average_main_copies_per_deck") or 0.0)
    average_side_copies = float(row.get("average_side_copies_per_deck") or 0.0)
    return round((average_main_copies + average_side_copies) * float(price), 2)


def _normalize_global_rows(
    rows: list[dict[str, object]], classification: str
) -> list[dict[str, object]]:
    normalized_rows: list[dict[str, object]] = []
    for row in rows:
        normalized_rows.append(
            {
                "image_url_small": row.get("image_url_small"),
                "card_name": str(row.get("card_name") or "-"),
                "classification_key": classification,
                "classification_label": _classification_label(classification),
                "role_label": str(row.get("non_engine_role_label") or "-"),
                "confidence_label": str(row.get("role_confidence") or "-"),
                "usage_profile_label": _usage_profile_label(
                    row.get("main_presence_pct"), row.get("side_presence_pct")
                ),
                "card_archetype": str(row.get("card_archetype") or "-"),
                "total_decks_with_card": int(row.get("total_decks_with_card") or 0),
                "deck_group_count": int(row.get("deck_group_count") or 0),
                "global_inclusion_rate_pct": float(
                    row.get("global_inclusion_rate_pct") or 0.0
                ),
                "deck_group_spread_pct": float(row.get("deck_group_spread_pct") or 0.0),
                "max_group_share_pct": float(row.get("max_group_share_pct") or 0.0),
                "archetype_match_share_pct": float(
                    row.get("archetype_match_share_pct") or 0.0
                ),
                "average_main_copies_per_deck": float(
                    row.get("average_main_copies_per_deck") or 0.0
                ),
                "average_side_copies_per_deck": float(
                    row.get("average_side_copies_per_deck") or 0.0
                ),
                "main_presence_pct": float(row.get("main_presence_pct") or 0.0),
                "side_presence_pct": float(row.get("side_presence_pct") or 0.0),
                "average_copies_when_present": float(
                    row.get("average_copies_when_present") or 0.0
                ),
                "average_cardmarket_price_eur": float(
                    row.get("average_cardmarket_price_eur") or 0.0
                ),
                "expected_deck_cost_contribution_eur": _expected_deck_cost_contribution(
                    row
                ),
                "total_copies": int(row.get("total_copies") or 0),
                "average_placement_percentile": (
                    float(row.get("average_placement_percentile"))
                    if row.get("average_placement_percentile") is not None
                    else None
                ),
                "median_placement_percentile": (
                    float(row.get("median_placement_percentile"))
                    if row.get("median_placement_percentile") is not None
                    else None
                ),
                "placement_percentile_iqr": (
                    float(row.get("placement_percentile_iqr"))
                    if row.get("placement_percentile_iqr") is not None
                    else None
                ),
                "top_25_finish_rate_pct": (
                    float(row.get("top_25_finish_rate_pct"))
                    if row.get("top_25_finish_rate_pct") is not None
                    else None
                ),
                "valid_placement_percentile_count": int(
                    row.get("valid_placement_percentile_count") or 0
                ),
                "field_average_placement_percentile": (
                    float(row.get("field_average_placement_percentile"))
                    if row.get("field_average_placement_percentile") is not None
                    else None
                ),
                "delta_vs_field_average_placement_percentile": (
                    float(row.get("delta_vs_field_average_placement_percentile"))
                    if row.get("delta_vs_field_average_placement_percentile")
                    is not None
                    else None
                ),
            }
        )
    return normalized_rows


def _table_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "Bild": row["image_url_small"],
            "Karte": row["card_name"],
            "Klassifikation": row["classification_label"],
            "Rolle": row["role_label"],
            "Sicherheit": row["confidence_label"],
            "Nutzungsprofil": row["usage_profile_label"],
            "Archetype": row["card_archetype"],
            "Deckvorkommen": row["total_decks_with_card"],
            "Deckgruppen": row["deck_group_count"],
            "Kopien gesamt": row["total_copies"],
            "Globale Inklusion %": row["global_inclusion_rate_pct"],
            "Deckgruppen-Spread %": row["deck_group_spread_pct"],
            "Max Gruppenanteil %": row["max_group_share_pct"],
            "Archetype Match %": row["archetype_match_share_pct"],
            "Ø Main / Deck": row["average_main_copies_per_deck"],
            "Ø Side / Deck": row["average_side_copies_per_deck"],
            "Main >=1 %": row["main_presence_pct"],
            "Side >=1 %": row["side_presence_pct"],
            "Ø Kopien bei Nutzung": row["average_copies_when_present"],
            "Ø Cardmarket €": row["average_cardmarket_price_eur"],
            "Erwarteter Deckkostenbeitrag €": row[
                "expected_deck_cost_contribution_eur"
            ],
            "Median Platzierungs-Perzentil": row["median_placement_percentile"],
            "Delta vs Feld pp": row["delta_vs_field_average_placement_percentile"],
            "Performance-IQR": row["placement_percentile_iqr"],
            "Top-25 %": row["top_25_finish_rate_pct"],
            "Performance Stichprobe": row["valid_placement_percentile_count"],
        }
        for row in rows
    ]


def _numeric_median(rows: list[dict[str, object]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    if not values:
        return None
    return round(float(median(values)), 2)


def _card_table_config() -> dict[str, object]:
    return {
        "Bild": st.column_config.ImageColumn(
            "Bild",
            help="Kleines Kartenbild aus der YGOPRODeck-API.",
            width="small",
        ),
        "Deckvorkommen": st.column_config.NumberColumn("Deckvorkommen", format="%d"),
        "Deckgruppen": st.column_config.NumberColumn("Deckgruppen", format="%d"),
        "Kopien gesamt": st.column_config.NumberColumn("Kopien gesamt", format="%d"),
        "Globale Inklusion %": st.column_config.NumberColumn(
            "Globale Inklusion %", format="%.1f"
        ),
        "Deckgruppen-Spread %": st.column_config.NumberColumn(
            "Deckgruppen-Spread %", format="%.1f"
        ),
        "Max Gruppenanteil %": st.column_config.NumberColumn(
            "Max Gruppenanteil %", format="%.1f"
        ),
        "Archetype Match %": st.column_config.NumberColumn(
            "Archetype Match %", format="%.1f"
        ),
        "Ø Main / Deck": st.column_config.NumberColumn("Ø Main / Deck", format="%.2f"),
        "Ø Side / Deck": st.column_config.NumberColumn("Ø Side / Deck", format="%.2f"),
        "Main >=1 %": st.column_config.NumberColumn("Main >=1 %", format="%.1f"),
        "Side >=1 %": st.column_config.NumberColumn("Side >=1 %", format="%.1f"),
        "Ø Kopien bei Nutzung": st.column_config.NumberColumn(
            "Ø Kopien bei Nutzung", format="%.2f"
        ),
        "Ø Cardmarket €": st.column_config.NumberColumn(
            "Ø Cardmarket €", format="%.2f"
        ),
        "Erwarteter Deckkostenbeitrag €": st.column_config.NumberColumn(
            "Erwarteter Deckkostenbeitrag €", format="%.2f"
        ),
        "Median Platzierungs-Perzentil": st.column_config.NumberColumn(
            "Median Platzierungs-Perzentil", format="%.2f"
        ),
        "Delta vs Feld pp": st.column_config.NumberColumn(
            "Delta vs Feld pp", format="%.2f"
        ),
        "Performance-IQR": st.column_config.NumberColumn(
            "Performance-IQR", format="%.2f"
        ),
        "Top-25 %": st.column_config.NumberColumn("Top-25 %", format="%.2f"),
        "Performance Stichprobe": st.column_config.NumberColumn(
            "Performance Stichprobe", format="%d"
        ),
    }


def _render_global_table(rows: list[dict[str, object]], empty_message: str) -> None:
    if not rows:
        st.info(empty_message)
        return

    st.dataframe(
        _table_rows(rows),
        hide_index=True,
        width="stretch",
        column_config=_card_table_config(),
    )


def _count_usage_profile(rows: list[dict[str, object]], profile: str) -> int:
    return sum(
        1 for row in rows if str(row.get("usage_profile_label") or "-") == profile
    )


def _render_overview_metrics(
    non_engine_rows: list[dict[str, object]],
    candidate_splash_rows: list[dict[str, object]],
) -> None:
    total_rows = len(non_engine_rows) + len(candidate_splash_rows)
    candidate_share_pct = (
        round(len(candidate_splash_rows) * 100.0 / total_rows, 1)
        if total_rows > 0
        else None
    )

    primary_cols = st.columns(6)
    primary_cols[0].metric("Non-Engine Karten", len(non_engine_rows))
    primary_cols[1].metric("Candidate Splash Karten", len(candidate_splash_rows))
    primary_cols[2].metric(
        "Candidate-Anteil am Pool", _format_percent(candidate_share_pct)
    )
    primary_cols[3].metric(
        "Median Spread Non-Engine",
        _format_percent(_numeric_median(non_engine_rows, "deck_group_spread_pct")),
    )
    primary_cols[4].metric(
        "Median Max Gruppenanteil Splash",
        _format_percent(_numeric_median(candidate_splash_rows, "max_group_share_pct")),
    )
    primary_cols[5].metric(
        "Median Deckkostenbeitrag Non-Engine",
        _format_currency(
            _numeric_median(non_engine_rows, "expected_deck_cost_contribution_eur")
        ),
    )

    secondary_cols = st.columns(5)
    secondary_cols[0].metric(
        "Non-Engine Main-first", _count_usage_profile(non_engine_rows, "Main-first")
    )
    secondary_cols[1].metric(
        "Non-Engine Side-first", _count_usage_profile(non_engine_rows, "Side-first")
    )
    secondary_cols[2].metric(
        "Non-Engine Hybrid", _count_usage_profile(non_engine_rows, "Hybrid")
    )
    secondary_cols[3].metric(
        "Median Cardmarket Non-Engine",
        _format_currency(
            _numeric_median(non_engine_rows, "average_cardmarket_price_eur")
        ),
    )
    secondary_cols[4].metric(
        "Median Archetype Match Splash",
        _format_percent(
            _numeric_median(candidate_splash_rows, "archetype_match_share_pct")
        ),
    )


def _sort_global_rows(
    rows: list[dict[str, object]], sort_mode: str
) -> list[dict[str, object]]:
    field_by_sort_mode = {
        "Globale Inklusion": "global_inclusion_rate_pct",
        "Deckgruppen-Spread": "deck_group_spread_pct",
        "Erwarteter Deckkostenbeitrag": "expected_deck_cost_contribution_eur",
        "Ø Cardmarket": "average_cardmarket_price_eur",
        "Deckgruppen": "deck_group_count",
        "Deckvorkommen": "total_decks_with_card",
    }
    if sort_mode == "Karte":
        return sorted(rows, key=lambda row: str(row["card_name"]))

    sort_field = field_by_sort_mode.get(sort_mode, "global_inclusion_rate_pct")
    return sorted(
        rows,
        key=lambda row: (
            -(float(row.get(sort_field) or 0.0)),
            -float(row.get("deck_group_spread_pct") or 0.0),
            str(row["card_name"]),
        ),
    )


def _filter_global_rows(
    rows: list[dict[str, object]],
    *,
    roles: list[str],
    usage_profiles: list[str],
    confidence_levels: list[str],
    min_inclusion_pct: float,
    min_spread_pct: float,
    price_range: tuple[float, float],
) -> list[dict[str, object]]:
    filtered_rows: list[dict[str, object]] = []
    price_min, price_max = price_range

    for row in rows:
        if roles and str(row["role_label"]) not in roles:
            continue
        if usage_profiles and str(row["usage_profile_label"]) not in usage_profiles:
            continue
        if confidence_levels and str(row["confidence_label"]) not in confidence_levels:
            continue
        if float(row["global_inclusion_rate_pct"]) < min_inclusion_pct:
            continue
        if float(row["deck_group_spread_pct"]) < min_spread_pct:
            continue
        cardmarket_price = float(row.get("average_cardmarket_price_eur") or 0.0)
        if cardmarket_price < price_min or cardmarket_price > price_max:
            continue
        filtered_rows.append(row)

    return filtered_rows


def _render_role_mix_chart(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info("Fuer den aktuellen Filter konnten keine Rollenwerte berechnet werden.")
        return

    role_rows: list[dict[str, object]] = []
    role_labels = sorted({str(row["role_label"]) for row in rows})
    for role_label in role_labels:
        matching_rows = [row for row in rows if str(row["role_label"]) == role_label]
        role_rows.append(
            {
                "role_label": role_label,
                "card_count": len(matching_rows),
                "median_inclusion_pct": _numeric_median(
                    matching_rows, "global_inclusion_rate_pct"
                ),
                "median_spread_pct": _numeric_median(
                    matching_rows, "deck_group_spread_pct"
                ),
                "median_cardmarket_eur": _numeric_median(
                    matching_rows, "average_cardmarket_price_eur"
                ),
            }
        )

    domain = [
        row["role_label"]
        for row in sorted(
            role_rows, key=lambda row: (-int(row["card_count"]), str(row["role_label"]))
        )
    ]
    color_range = [_role_color(str(role_label)) for role_label in domain]

    st.vega_lite_chart(
        {
            "data": {"values": role_rows},
            "height": {"step": 34},
            "mark": {"type": "bar", "tooltip": True},
            "encoding": {
                "y": {
                    "field": "role_label",
                    "type": "nominal",
                    "title": None,
                    "sort": "-x",
                },
                "x": {
                    "field": "card_count",
                    "type": "quantitative",
                    "axis": {"title": "Karten im aktuellen Filter"},
                },
                "color": {
                    "field": "role_label",
                    "type": "nominal",
                    "scale": {"domain": domain, "range": color_range},
                    "legend": {"title": None, "orient": "bottom"},
                },
                "tooltip": [
                    {"field": "role_label", "type": "nominal", "title": "Rolle"},
                    {
                        "field": "card_count",
                        "type": "quantitative",
                        "format": ".0f",
                        "title": "Karten",
                    },
                    {
                        "field": "median_inclusion_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Median Inklusion %",
                    },
                    {
                        "field": "median_spread_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Median Spread %",
                    },
                    {
                        "field": "median_cardmarket_eur",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Median Cardmarket EUR",
                    },
                ],
            },
        },
        width="stretch",
    )


def _render_universal_vs_concentrated_scatter(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info(
            "Fuer den aktuellen Filter konnten keine Verteilungsdaten berechnet werden."
        )
        return

    chart_rows = [
        {
            "card_name": row["card_name"],
            "classification_label": row["classification_label"],
            "role_label": row["role_label"],
            "spread_pct": row["deck_group_spread_pct"],
            "max_group_share_pct": row["max_group_share_pct"],
            "inclusion_pct": row["global_inclusion_rate_pct"],
            "deck_count": row["total_decks_with_card"],
            "deck_group_count": row["deck_group_count"],
            "average_cardmarket_eur": row["average_cardmarket_price_eur"],
        }
        for row in rows
    ]
    domain = sorted({str(row["role_label"]) for row in rows})
    color_range = [_role_color(str(role_label)) for role_label in domain]

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": 360,
            "mark": {"type": "circle", "tooltip": True, "opacity": 0.82},
            "encoding": {
                "x": {
                    "field": "spread_pct",
                    "type": "quantitative",
                    "axis": {"title": "Deckgruppen-Spread %"},
                    "scale": {"zero": True},
                },
                "y": {
                    "field": "max_group_share_pct",
                    "type": "quantitative",
                    "axis": {"title": "Max Gruppenanteil %"},
                    "scale": {"zero": True},
                },
                "size": {
                    "field": "inclusion_pct",
                    "type": "quantitative",
                    "legend": {"title": "Globale Inklusion %"},
                    "scale": {"range": [80, 1500]},
                },
                "color": {
                    "field": "role_label",
                    "type": "nominal",
                    "scale": {"domain": domain, "range": color_range},
                    "legend": {"title": "Rolle", "orient": "bottom"},
                },
                "tooltip": [
                    {"field": "card_name", "type": "nominal", "title": "Karte"},
                    {
                        "field": "classification_label",
                        "type": "nominal",
                        "title": "Klassifikation",
                    },
                    {"field": "role_label", "type": "nominal", "title": "Rolle"},
                    {
                        "field": "spread_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Deckgruppen-Spread %",
                    },
                    {
                        "field": "max_group_share_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Max Gruppenanteil %",
                    },
                    {
                        "field": "inclusion_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Globale Inklusion %",
                    },
                    {
                        "field": "deck_count",
                        "type": "quantitative",
                        "format": ".0f",
                        "title": "Deckvorkommen",
                    },
                    {
                        "field": "deck_group_count",
                        "type": "quantitative",
                        "format": ".0f",
                        "title": "Deckgruppen",
                    },
                    {
                        "field": "average_cardmarket_eur",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Ø Cardmarket EUR",
                    },
                ],
            },
        },
        width="stretch",
    )


def _render_main_vs_side_scatter(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info(
            "Fuer den aktuellen Filter konnten keine Main-vs-Side-Daten berechnet werden."
        )
        return

    chart_rows = [
        {
            "card_name": row["card_name"],
            "classification_label": row["classification_label"],
            "role_label": row["role_label"],
            "usage_profile_label": row["usage_profile_label"],
            "main_presence_pct": row["main_presence_pct"],
            "side_presence_pct": row["side_presence_pct"],
            "average_copies_when_present": row["average_copies_when_present"],
            "deck_cost_contribution_eur": float(
                row.get("expected_deck_cost_contribution_eur") or 0.0
            ),
            "inclusion_pct": row["global_inclusion_rate_pct"],
        }
        for row in rows
    ]
    domain = sorted({str(row["role_label"]) for row in rows})
    color_range = [_role_color(str(role_label)) for role_label in domain]

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": 360,
            "mark": {"type": "circle", "tooltip": True, "opacity": 0.82},
            "encoding": {
                "x": {
                    "field": "main_presence_pct",
                    "type": "quantitative",
                    "axis": {"title": "Main >=1 %"},
                    "scale": {"zero": True},
                },
                "y": {
                    "field": "side_presence_pct",
                    "type": "quantitative",
                    "axis": {"title": "Side >=1 %"},
                    "scale": {"zero": True},
                },
                "size": {
                    "field": "deck_cost_contribution_eur",
                    "type": "quantitative",
                    "legend": {"title": "Erwarteter Deckkostenbeitrag EUR"},
                    "scale": {"range": [80, 1500]},
                },
                "color": {
                    "field": "role_label",
                    "type": "nominal",
                    "scale": {"domain": domain, "range": color_range},
                    "legend": {"title": "Rolle", "orient": "bottom"},
                },
                "tooltip": [
                    {"field": "card_name", "type": "nominal", "title": "Karte"},
                    {
                        "field": "classification_label",
                        "type": "nominal",
                        "title": "Klassifikation",
                    },
                    {"field": "role_label", "type": "nominal", "title": "Rolle"},
                    {
                        "field": "usage_profile_label",
                        "type": "nominal",
                        "title": "Nutzungsprofil",
                    },
                    {
                        "field": "main_presence_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Main >=1 %",
                    },
                    {
                        "field": "side_presence_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Side >=1 %",
                    },
                    {
                        "field": "average_copies_when_present",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Ø Kopien bei Nutzung",
                    },
                    {
                        "field": "deck_cost_contribution_eur",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Erwarteter Deckkostenbeitrag EUR",
                    },
                    {
                        "field": "inclusion_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Globale Inklusion %",
                    },
                ],
            },
        },
        width="stretch",
    )


def _top_row(
    rows: list[dict[str, object]], sort_field: str
) -> dict[str, object] | None:
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: (
            float(row.get(sort_field) or 0.0),
            float(row.get("global_inclusion_rate_pct") or 0.0),
            int(row.get("deck_group_count") or 0),
            str(row.get("card_name") or ""),
        ),
    )


def _render_candidate_splash_summary(candidate_rows: list[dict[str, object]]) -> None:
    if not candidate_rows:
        st.info("Im aktiven Zeitraum wurden keine Candidate-Splash-Karten erkannt.")
        return

    main_first_share_pct = round(
        sum(
            1
            for row in candidate_rows
            if str(row.get("usage_profile_label") or "-") == "Main-first"
        )
        * 100.0
        / len(candidate_rows),
        1,
    )
    archetype_anchor = _top_row(candidate_rows, "archetype_match_share_pct")
    concentration_anchor = _top_row(candidate_rows, "max_group_share_pct")
    spread_anchor = _top_row(candidate_rows, "deck_group_spread_pct")
    cost_anchor = _top_row(candidate_rows, "expected_deck_cost_contribution_eur")

    metric_cols = st.columns(5)
    metric_cols[0].metric("Candidate Splash Karten", len(candidate_rows))
    metric_cols[1].metric(
        "Median Archetype Match",
        _format_percent(_numeric_median(candidate_rows, "archetype_match_share_pct")),
    )
    metric_cols[2].metric(
        "Median Max Gruppenanteil",
        _format_percent(_numeric_median(candidate_rows, "max_group_share_pct")),
    )
    metric_cols[3].metric(
        "Median globale Inklusion",
        _format_percent(_numeric_median(candidate_rows, "global_inclusion_rate_pct")),
    )
    metric_cols[4].metric("Main-first Anteil", _format_percent(main_first_share_pct))

    highlight_cols = st.columns(4)
    highlight_cols[0].metric(
        "Hoechster Archetype-Match",
        str((archetype_anchor or {}).get("card_name") or "-"),
        _format_percent((archetype_anchor or {}).get("archetype_match_share_pct")),
        delta_color="off",
    )
    highlight_cols[1].metric(
        "Staerkste Gruppenkonzentration",
        str((concentration_anchor or {}).get("card_name") or "-"),
        _format_percent((concentration_anchor or {}).get("max_group_share_pct")),
        delta_color="off",
    )
    highlight_cols[2].metric(
        "Breitestes Splash-Paket",
        str((spread_anchor or {}).get("card_name") or "-"),
        _format_percent((spread_anchor or {}).get("deck_group_spread_pct")),
        delta_color="off",
    )
    highlight_cols[3].metric(
        "Teuerster Deckkostenbeitrag",
        str((cost_anchor or {}).get("card_name") or "-"),
        _format_currency(
            (cost_anchor or {}).get("expected_deck_cost_contribution_eur")
        ),
        delta_color="off",
    )

    st.caption(
        "Candidate Splash ist hier bewusst als Grenzbereich zwischen universeller Staple und archetypenaher Paketkarte modelliert. Hoher Archetype Match und hoher Max Gruppenanteil schieben eine Karte naeher an Engine oder sehr schmale Paketnutzung; hoher Spread bei moderater Konzentration spricht eher fuer wiederkehrende Splash-Nutzung."
    )


def _render_candidate_splash_boundary_chart(
    non_engine_rows: list[dict[str, object]],
    candidate_rows: list[dict[str, object]],
) -> None:
    if not candidate_rows:
        st.info("Im aktiven Zeitraum wurden keine Candidate-Splash-Karten erkannt.")
        return

    chart_rows = [
        {
            "card_name": row["card_name"],
            "classification_label": row["classification_label"],
            "usage_profile_label": row["usage_profile_label"],
            "archetype_match_share_pct": row["archetype_match_share_pct"],
            "max_group_share_pct": row["max_group_share_pct"],
            "deck_group_spread_pct": row["deck_group_spread_pct"],
            "global_inclusion_rate_pct": row["global_inclusion_rate_pct"],
            "expected_deck_cost_contribution_eur": float(
                row.get("expected_deck_cost_contribution_eur") or 0.0
            ),
        }
        for row in non_engine_rows + candidate_rows
    ]

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": 360,
            "mark": {"type": "circle", "tooltip": True, "opacity": 0.82},
            "encoding": {
                "x": {
                    "field": "archetype_match_share_pct",
                    "type": "quantitative",
                    "axis": {"title": "Archetype Match %"},
                    "scale": {"zero": True},
                },
                "y": {
                    "field": "max_group_share_pct",
                    "type": "quantitative",
                    "axis": {"title": "Max Gruppenanteil %"},
                    "scale": {"zero": True},
                },
                "size": {
                    "field": "global_inclusion_rate_pct",
                    "type": "quantitative",
                    "legend": {"title": "Globale Inklusion %"},
                    "scale": {"range": [70, 1500]},
                },
                "color": {
                    "field": "classification_label",
                    "type": "nominal",
                    "scale": {
                        "domain": ["Non-Engine", "Candidate Splash"],
                        "range": ["#8E9AAF", "#E76F51"],
                    },
                    "legend": {"title": "Klassifikation", "orient": "bottom"},
                },
                "tooltip": [
                    {"field": "card_name", "type": "nominal", "title": "Karte"},
                    {
                        "field": "classification_label",
                        "type": "nominal",
                        "title": "Klassifikation",
                    },
                    {
                        "field": "usage_profile_label",
                        "type": "nominal",
                        "title": "Nutzungsprofil",
                    },
                    {
                        "field": "archetype_match_share_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Archetype Match %",
                    },
                    {
                        "field": "max_group_share_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Max Gruppenanteil %",
                    },
                    {
                        "field": "deck_group_spread_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Deckgruppen-Spread %",
                    },
                    {
                        "field": "global_inclusion_rate_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Globale Inklusion %",
                    },
                    {
                        "field": "expected_deck_cost_contribution_eur",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Erwarteter Deckkostenbeitrag EUR",
                    },
                ],
            },
        },
        width="stretch",
    )


def _performance_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        row for row in rows if int(row.get("valid_placement_percentile_count") or 0) > 0
    ]


def _open_deck_group(deck_name: str) -> None:
    st.session_state[DECKGROUP_STATE_KEY] = deck_name
    st.switch_page(DECKGROUP_PAGE_PATH)


def _card_drilldown_label(row: dict[str, object]) -> str:
    return " | ".join(
        [
            str(row.get("card_name") or "-"),
            str(row.get("classification_label") or "-"),
            str(row.get("role_label") or "-"),
            _format_percent(row.get("global_inclusion_rate_pct")),
        ]
    )


def _deck_group_drilldown_label(row: dict[str, object]) -> str:
    return " | ".join(
        [
            str(row.get("deck_name") or "-"),
            f"Inkl. {_format_percent(row.get('group_inclusion_rate_pct'))}",
            f"Median {_format_percent(row.get('median_placement_percentile'))}",
            f"{_format_count(row.get('decks_with_card'))}/{_format_count(row.get('deck_group_size'))} Decks",
        ]
    )


def _render_performance_summary(rows: list[dict[str, object]]) -> None:
    performance_rows = _performance_rows(rows)
    if not performance_rows:
        st.info(
            "Fuer den aktuellen Filter konnten keine card-level Performance-Werte berechnet werden."
        )
        return

    best_median_row = max(
        performance_rows,
        key=lambda row: (
            float(row.get("median_placement_percentile") or -1.0),
            float(row.get("delta_vs_field_average_placement_percentile") or -999.0),
            int(row.get("valid_placement_percentile_count") or 0),
            str(row.get("card_name") or ""),
        ),
    )
    best_delta_row = max(
        performance_rows,
        key=lambda row: (
            float(row.get("delta_vs_field_average_placement_percentile") or -999.0),
            float(row.get("median_placement_percentile") or -1.0),
            int(row.get("valid_placement_percentile_count") or 0),
            str(row.get("card_name") or ""),
        ),
    )
    stable_rows = [
        row
        for row in performance_rows
        if row.get("placement_percentile_iqr") is not None
    ]
    most_stable_row = (
        min(
            stable_rows,
            key=lambda row: (
                float(row.get("placement_percentile_iqr") or 999.0),
                -int(row.get("valid_placement_percentile_count") or 0),
                str(row.get("card_name") or ""),
            ),
        )
        if stable_rows
        else None
    )
    field_average = next(
        (
            row.get("field_average_placement_percentile")
            for row in performance_rows
            if row.get("field_average_placement_percentile") is not None
        ),
        None,
    )

    metric_cols = st.columns(4)
    metric_cols[0].metric("Feldmittel Ø Perzentil", _format_percent(field_average))
    metric_cols[1].metric(
        "Bester Median",
        str(best_median_row.get("card_name") or "-"),
        _format_percent(best_median_row.get("median_placement_percentile")),
        delta_color="off",
    )
    metric_cols[2].metric(
        "Bestes Delta vs Feld",
        str(best_delta_row.get("card_name") or "-"),
        _format_delta_pp(
            best_delta_row.get("delta_vs_field_average_placement_percentile")
        ),
        delta_color="off",
    )
    metric_cols[3].metric(
        "Stabilster Performer",
        str((most_stable_row or {}).get("card_name") or "-"),
        _format_percent((most_stable_row or {}).get("placement_percentile_iqr")),
        delta_color="off",
    )

    st.caption(
        "Die Tournament-Meta-Daten liegen insgesamt schon auf hohem Niveau. Deshalb ist `Delta vs Feld` oft aussagekraeftiger als das absolute Perzentil allein. Niedrigeres `Performance-IQR` bedeutet stabilere Resultate ueber die mit der Karte beobachteten Listen hinweg."
    )


def _render_role_performance_chart(rows: list[dict[str, object]]) -> None:
    performance_rows = _performance_rows(rows)
    if not performance_rows:
        st.info(
            "Fuer den aktuellen Filter konnten keine rollenbasierten Performance-Werte berechnet werden."
        )
        return

    role_labels = sorted({str(row["role_label"]) for row in performance_rows})
    role_rows: list[dict[str, object]] = []
    for role_label in role_labels:
        matching_rows = [
            row for row in performance_rows if str(row["role_label"]) == role_label
        ]
        role_rows.append(
            {
                "role_label": role_label,
                "card_count": len(matching_rows),
                "median_delta_pp": _numeric_median(
                    matching_rows, "delta_vs_field_average_placement_percentile"
                ),
                "median_placement_percentile": _numeric_median(
                    matching_rows, "median_placement_percentile"
                ),
                "median_performance_iqr": _numeric_median(
                    matching_rows, "placement_percentile_iqr"
                ),
                "median_top_25_pct": _numeric_median(
                    matching_rows, "top_25_finish_rate_pct"
                ),
            }
        )

    domain = [
        row["role_label"]
        for row in sorted(
            role_rows, key=lambda row: (-int(row["card_count"]), str(row["role_label"]))
        )
    ]
    color_range = [_role_color(str(role_label)) for role_label in domain]

    st.vega_lite_chart(
        {
            "data": {"values": role_rows},
            "height": {"step": 34},
            "mark": {"type": "bar", "tooltip": True},
            "encoding": {
                "y": {
                    "field": "role_label",
                    "type": "nominal",
                    "title": None,
                    "sort": "-x",
                },
                "x": {
                    "field": "median_delta_pp",
                    "type": "quantitative",
                    "axis": {"title": "Median Delta vs Feld (pp)"},
                },
                "color": {
                    "field": "role_label",
                    "type": "nominal",
                    "scale": {"domain": domain, "range": color_range},
                    "legend": {"title": None, "orient": "bottom"},
                },
                "tooltip": [
                    {"field": "role_label", "type": "nominal", "title": "Rolle"},
                    {
                        "field": "card_count",
                        "type": "quantitative",
                        "format": ".0f",
                        "title": "Karten",
                    },
                    {
                        "field": "median_delta_pp",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Median Delta vs Feld pp",
                    },
                    {
                        "field": "median_placement_percentile",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Median Platzierungs-Perzentil",
                    },
                    {
                        "field": "median_performance_iqr",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Median Performance-IQR",
                    },
                    {
                        "field": "median_top_25_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Median Top-25 %",
                    },
                ],
            },
        },
        width="stretch",
    )


def _render_inclusion_vs_performance_scatter(rows: list[dict[str, object]]) -> None:
    performance_rows = _performance_rows(rows)
    if not performance_rows:
        st.info(
            "Fuer den aktuellen Filter konnten keine Performance-vs-Inklusions-Daten berechnet werden."
        )
        return

    chart_rows = [
        {
            "card_name": row["card_name"],
            "classification_label": row["classification_label"],
            "role_label": row["role_label"],
            "global_inclusion_rate_pct": row["global_inclusion_rate_pct"],
            "median_placement_percentile": row["median_placement_percentile"],
            "delta_vs_field_average_placement_percentile": row[
                "delta_vs_field_average_placement_percentile"
            ],
            "valid_placement_percentile_count": row["valid_placement_percentile_count"],
            "placement_percentile_iqr": row["placement_percentile_iqr"],
            "expected_deck_cost_contribution_eur": float(
                row.get("expected_deck_cost_contribution_eur") or 0.0
            ),
        }
        for row in performance_rows
        if row.get("median_placement_percentile") is not None
    ]
    if not chart_rows:
        st.info(
            "Fuer den aktuellen Filter konnten keine Performance-vs-Inklusions-Daten berechnet werden."
        )
        return

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": 360,
            "mark": {"type": "circle", "tooltip": True, "opacity": 0.82},
            "encoding": {
                "x": {
                    "field": "global_inclusion_rate_pct",
                    "type": "quantitative",
                    "axis": {"title": "Globale Inklusion %"},
                },
                "y": {
                    "field": "median_placement_percentile",
                    "type": "quantitative",
                    "axis": {"title": "Median Platzierungs-Perzentil"},
                    "scale": {"zero": False},
                },
                "size": {
                    "field": "valid_placement_percentile_count",
                    "type": "quantitative",
                    "legend": {"title": "Performance Stichprobe"},
                    "scale": {"range": [80, 1600]},
                },
                "color": {
                    "field": "delta_vs_field_average_placement_percentile",
                    "type": "quantitative",
                    "legend": {"title": "Delta vs Feld pp"},
                    "scale": {
                        "domainMid": 0,
                        "range": ["#E76F51", "#F4A261", "#2A9D8F"],
                    },
                },
                "tooltip": [
                    {"field": "card_name", "type": "nominal", "title": "Karte"},
                    {
                        "field": "classification_label",
                        "type": "nominal",
                        "title": "Klassifikation",
                    },
                    {"field": "role_label", "type": "nominal", "title": "Rolle"},
                    {
                        "field": "global_inclusion_rate_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Globale Inklusion %",
                    },
                    {
                        "field": "median_placement_percentile",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Median Platzierungs-Perzentil",
                    },
                    {
                        "field": "delta_vs_field_average_placement_percentile",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Delta vs Feld pp",
                    },
                    {
                        "field": "placement_percentile_iqr",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Performance-IQR",
                    },
                    {
                        "field": "valid_placement_percentile_count",
                        "type": "quantitative",
                        "format": ".0f",
                        "title": "Performance Stichprobe",
                    },
                    {
                        "field": "expected_deck_cost_contribution_eur",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Erwarteter Deckkostenbeitrag EUR",
                    },
                ],
            },
        },
        width="stretch",
    )


def _render_cost_vs_performance_scatter(rows: list[dict[str, object]]) -> None:
    performance_rows = _performance_rows(rows)
    if not performance_rows:
        st.info(
            "Fuer den aktuellen Filter konnten keine Kosten-vs-Performance-Daten berechnet werden."
        )
        return

    domain = sorted({str(row["role_label"]) for row in performance_rows})
    color_range = [_role_color(str(role_label)) for role_label in domain]
    chart_rows = [
        {
            "card_name": row["card_name"],
            "classification_label": row["classification_label"],
            "role_label": row["role_label"],
            "deck_cost_contribution_eur": float(
                row.get("expected_deck_cost_contribution_eur") or 0.0
            ),
            "median_placement_percentile": row["median_placement_percentile"],
            "global_inclusion_rate_pct": row["global_inclusion_rate_pct"],
            "placement_percentile_iqr": row["placement_percentile_iqr"],
            "valid_placement_percentile_count": row["valid_placement_percentile_count"],
        }
        for row in performance_rows
        if row.get("median_placement_percentile") is not None
    ]
    if not chart_rows:
        st.info(
            "Fuer den aktuellen Filter konnten keine Kosten-vs-Performance-Daten berechnet werden."
        )
        return

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": 360,
            "mark": {"type": "circle", "tooltip": True, "opacity": 0.82},
            "encoding": {
                "x": {
                    "field": "deck_cost_contribution_eur",
                    "type": "quantitative",
                    "axis": {"title": "Erwarteter Deckkostenbeitrag EUR"},
                },
                "y": {
                    "field": "median_placement_percentile",
                    "type": "quantitative",
                    "axis": {"title": "Median Platzierungs-Perzentil"},
                    "scale": {"zero": False},
                },
                "size": {
                    "field": "global_inclusion_rate_pct",
                    "type": "quantitative",
                    "legend": {"title": "Globale Inklusion %"},
                    "scale": {"range": [80, 1500]},
                },
                "color": {
                    "field": "role_label",
                    "type": "nominal",
                    "scale": {"domain": domain, "range": color_range},
                    "legend": {"title": "Rolle", "orient": "bottom"},
                },
                "tooltip": [
                    {"field": "card_name", "type": "nominal", "title": "Karte"},
                    {
                        "field": "classification_label",
                        "type": "nominal",
                        "title": "Klassifikation",
                    },
                    {"field": "role_label", "type": "nominal", "title": "Rolle"},
                    {
                        "field": "deck_cost_contribution_eur",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Erwarteter Deckkostenbeitrag EUR",
                    },
                    {
                        "field": "median_placement_percentile",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Median Platzierungs-Perzentil",
                    },
                    {
                        "field": "placement_percentile_iqr",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Performance-IQR",
                    },
                    {
                        "field": "global_inclusion_rate_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Globale Inklusion %",
                    },
                    {
                        "field": "valid_placement_percentile_count",
                        "type": "quantitative",
                        "format": ".0f",
                        "title": "Performance Stichprobe",
                    },
                ],
            },
        },
        width="stretch",
    )


def _trend_delta_points(current_value: object, previous_value: object) -> str | None:
    if current_value is None or previous_value is None:
        return None
    return f"{float(current_value) - float(previous_value):+.2f} pp"


def _trend_delta_count(current_value: object, previous_value: object) -> str | None:
    if current_value is None or previous_value is None:
        return None
    return f"{int(current_value) - int(previous_value):+d}"


def _latest_month_rows(
    rows: list[dict[str, object]],
    *,
    section: str | None = None,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    filtered_rows = rows
    if section is not None:
        filtered_rows = [
            row for row in rows if str(row.get("section") or "") == section
        ]
    if not filtered_rows:
        return None, None
    sorted_rows = sorted(filtered_rows, key=lambda row: str(row["month_start"]))
    latest_row = sorted_rows[-1]
    previous_row = sorted_rows[-2] if len(sorted_rows) > 1 else None
    return latest_row, previous_row


def _monthly_chart_rows(
    rows: list[dict[str, object]],
    *,
    series_fields: list[tuple[str, str]],
) -> list[dict[str, object]]:
    chart_rows: list[dict[str, object]] = []
    for row in rows:
        for field_name, series_label in series_fields:
            value = row.get(field_name)
            if value is None:
                continue
            chart_rows.append(
                {
                    "month_start": str(row["month_start"]),
                    "series_label": series_label,
                    "share_pct": float(value),
                    "deck_count": int(row.get("deck_count") or 0),
                }
            )
    return chart_rows


def _render_monthly_series_chart(
    chart_rows: list[dict[str, object]],
    *,
    series_order: list[str],
    color_range: list[str],
    axis_title: str,
    empty_message: str,
    stacked: bool = False,
) -> None:
    if not chart_rows:
        st.info(empty_message)
        return

    mark = (
        {"type": "area", "tooltip": True, "opacity": 0.86}
        if stacked
        else {"type": "line", "point": True, "tooltip": True}
    )

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": 320,
            "mark": mark,
            "encoding": {
                "x": {
                    "field": "month_start",
                    "type": "temporal",
                    "axis": {"title": "Monat", "format": "%Y-%m"},
                },
                "y": {
                    "field": "share_pct",
                    "type": "quantitative",
                    "axis": {"title": axis_title},
                    "scale": {"zero": True},
                    "stack": "zero" if stacked else None,
                },
                "color": {
                    "field": "series_label",
                    "type": "nominal",
                    "scale": {"domain": series_order, "range": color_range},
                    "legend": {"title": None, "orient": "bottom"},
                },
                "tooltip": [
                    {
                        "field": "month_start",
                        "type": "temporal",
                        "format": "%Y-%m",
                        "title": "Monat",
                    },
                    {"field": "series_label", "type": "nominal", "title": "Serie"},
                    {
                        "field": "share_pct",
                        "type": "quantitative",
                        "format": ".2f",
                        "title": "Anteil %",
                    },
                    {
                        "field": "deck_count",
                        "type": "quantitative",
                        "format": ".0f",
                        "title": "Decks im Monat",
                    },
                ],
            },
        },
        width="stretch",
    )


def _render_monthly_trend_metrics(
    engine_vs_non_engine_rows: list[dict[str, object]],
    main_share_rows: list[dict[str, object]],
    side_share_rows: list[dict[str, object]],
    subrole_rows: list[dict[str, object]],
) -> None:
    latest_main_balance_row, previous_main_balance_row = _latest_month_rows(
        engine_vs_non_engine_rows, section="main"
    )
    latest_side_balance_row, previous_side_balance_row = _latest_month_rows(
        engine_vs_non_engine_rows, section="side"
    )
    latest_main_role_row, previous_main_role_row = _latest_month_rows(main_share_rows)
    latest_side_role_row, previous_side_role_row = _latest_month_rows(side_share_rows)
    latest_subrole_row, previous_subrole_row = _latest_month_rows(subrole_rows)

    if (
        latest_main_role_row is None
        and latest_side_role_row is None
        and latest_subrole_row is None
    ):
        st.info(
            "Fuer den aktiven Zeitraum konnten keine monatlichen Non-Engine-Trends berechnet werden."
        )
        return

    latest_month_label = "-"
    for row in [
        latest_main_role_row,
        latest_side_role_row,
        latest_subrole_row,
        latest_main_balance_row,
        latest_side_balance_row,
    ]:
        if row is not None:
            latest_month_label = str(row["month_start"])[:7]

    st.caption(
        f"Monatlicher Trend fuer den aktiven Datumsfilter. Letzter ausgewerteter Monat: {latest_month_label}. Die Deltas beziehen sich jeweils auf den direkt vorherigen verfuegbaren Monat."
    )

    metric_cols = st.columns(6)
    metric_cols[0].metric(
        "Decks im letzten Monat",
        _format_count(
            (
                latest_main_role_row or latest_side_role_row or latest_subrole_row or {}
            ).get("deck_count")
        ),
        _trend_delta_count(
            (
                latest_main_role_row or latest_side_role_row or latest_subrole_row or {}
            ).get("deck_count"),
            (
                (
                    previous_main_role_row
                    or previous_side_role_row
                    or previous_subrole_row
                    or {}
                ).get("deck_count")
                if (
                    previous_main_role_row
                    or previous_side_role_row
                    or previous_subrole_row
                )
                else None
            ),
        ),
        delta_color="off",
    )
    metric_cols[1].metric(
        "Main Non-Engine %",
        _format_percent(
            (latest_main_balance_row or {}).get("average_non_engine_share_pct")
        ),
        _trend_delta_points(
            (latest_main_balance_row or {}).get("average_non_engine_share_pct"),
            (
                (previous_main_balance_row or {}).get("average_non_engine_share_pct")
                if previous_main_balance_row
                else None
            ),
        ),
        delta_color="off",
    )
    metric_cols[2].metric(
        "Side Non-Engine %",
        _format_percent(
            (latest_side_balance_row or {}).get("average_non_engine_share_pct")
        ),
        _trend_delta_points(
            (latest_side_balance_row or {}).get("average_non_engine_share_pct"),
            (
                (previous_side_balance_row or {}).get("average_non_engine_share_pct")
                if previous_side_balance_row
                else None
            ),
        ),
        delta_color="off",
    )
    metric_cols[3].metric(
        "Main Handtrap %",
        _format_percent((latest_main_role_row or {}).get("average_handtrap_share_pct")),
        _trend_delta_points(
            (latest_main_role_row or {}).get("average_handtrap_share_pct"),
            (
                (previous_main_role_row or {}).get("average_handtrap_share_pct")
                if previous_main_role_row
                else None
            ),
        ),
        delta_color="off",
    )
    metric_cols[4].metric(
        "Side Boardbreaker %",
        _format_percent(
            (latest_side_role_row or {}).get("average_boardbreaker_share_pct")
        ),
        _trend_delta_points(
            (latest_side_role_row or {}).get("average_boardbreaker_share_pct"),
            (
                (previous_side_role_row or {}).get("average_boardbreaker_share_pct")
                if previous_side_role_row
                else None
            ),
        ),
        delta_color="off",
    )
    metric_cols[5].metric(
        "Protection in Weitere NE %",
        _format_percent((latest_subrole_row or {}).get("average_protection_share_pct")),
        _trend_delta_points(
            (latest_subrole_row or {}).get("average_protection_share_pct"),
            (
                (previous_subrole_row or {}).get("average_protection_share_pct")
                if previous_subrole_row
                else None
            ),
        ),
        delta_color="off",
    )


def _render_monthly_trend_section(
    engine_vs_non_engine_rows: list[dict[str, object]],
    main_share_rows: list[dict[str, object]],
    side_share_rows: list[dict[str, object]],
    subrole_rows: list[dict[str, object]],
) -> None:
    _render_monthly_trend_metrics(
        engine_vs_non_engine_rows,
        main_share_rows,
        side_share_rows,
        subrole_rows,
    )
    balance_chart_rows = [
        {
            "month_start": row["month_start"],
            "series_label": f"{'Main Deck' if str(source_row.get('section')) == 'main' else 'Side Deck'} | {row['series_label']}",
            "share_pct": row["share_pct"],
            "deck_count": row["deck_count"],
        }
        for source_row in engine_vs_non_engine_rows
        for row in _monthly_chart_rows(
            [source_row],
            series_fields=[
                ("average_engine_share_pct", "Engine"),
                ("average_non_engine_share_pct", "Non-Engine"),
            ],
        )
    ]

    main_role_chart_rows = _monthly_chart_rows(
        main_share_rows,
        series_fields=[
            ("average_engine_share_pct", "Engine"),
            ("average_handtrap_share_pct", "Handtrap"),
            ("average_boardbreaker_share_pct", "Boardbreaker"),
        ],
    )
    side_role_chart_rows = _monthly_chart_rows(
        side_share_rows,
        series_fields=[
            ("average_handtrap_share_pct", "Handtrap"),
            ("average_boardbreaker_share_pct", "Boardbreaker"),
            ("average_non_engine_other_share_pct", "Weitere Non-Engine"),
        ],
    )
    subrole_chart_rows = _monthly_chart_rows(
        subrole_rows,
        series_fields=[
            ("average_floodgate_share_pct", "Floodgate"),
            ("average_protection_share_pct", "Protection"),
            ("average_draw_engine_share_pct", "Draw Engine"),
            ("average_unknown_share_pct", "Unklar"),
        ],
    )

    trend_tab_1, trend_tab_2, trend_tab_3, trend_tab_4 = st.tabs(
        ["Deckbereich-Balance", "Main Rollen", "Side Rollen", "Weitere Non-Engine"]
    )

    with trend_tab_1:
        st.caption(
            "Engine und Non-Engine werden hier getrennt fuer Main und Side gelesen. So wird sichtbar, in welchem Deckbereich der generische Anteil zuletzt zugenommen oder abgenommen hat."
        )
        _render_monthly_series_chart(
            balance_chart_rows,
            series_order=[
                "Main Deck | Engine",
                "Main Deck | Non-Engine",
                "Side Deck | Engine",
                "Side Deck | Non-Engine",
            ],
            color_range=["#1D3557", "#E76F51", "#457B9D", "#E9C46A"],
            axis_title="Anteil am Deckbereich (%)",
            empty_message="Fuer den aktiven Zeitraum konnten keine Monatswerte fuer Engine vs Non-Engine berechnet werden.",
        )

    with trend_tab_2:
        st.caption(
            "Das Main Deck fokussiert auf den Spannungsbogen zwischen Engine, Handtraps und Boardbreakern. Andere Non-Engine-Rollen werden hier bewusst nicht weiter aufgefaechert."
        )
        _render_monthly_series_chart(
            main_role_chart_rows,
            series_order=["Engine", "Handtrap", "Boardbreaker"],
            color_range=["#1D3557", "#E76F51", "#F4A261"],
            axis_title="Durchschnittlicher Anteil im Main Deck (%)",
            empty_message="Fuer den aktiven Zeitraum konnten keine monatlichen Main-Deck-Rollenwerte berechnet werden.",
        )

    with trend_tab_3:
        st.caption(
            "Im Side Deck liegt der Fokus auf Handtraps, Boardbreakern und dem Sammelbecken `Weitere Non-Engine`, also den nicht direkt separierten Side-Paketen."
        )
        _render_monthly_series_chart(
            side_role_chart_rows,
            series_order=["Handtrap", "Boardbreaker", "Weitere Non-Engine"],
            color_range=["#E76F51", "#F4A261", "#E9C46A"],
            axis_title="Durchschnittlicher Anteil im Side Deck (%)",
            empty_message="Fuer den aktiven Zeitraum konnten keine monatlichen Side-Deck-Rollenwerte berechnet werden.",
        )

    with trend_tab_4:
        st.caption(
            "Innerhalb von `Weitere Non-Engine` zeigt die gestapelte Monatsansicht, ob sich der Pool eher in Richtung Protection, Floodgates, Draw Engine oder unklare Faelle verschiebt."
        )
        _render_monthly_series_chart(
            subrole_chart_rows,
            series_order=["Floodgate", "Protection", "Draw Engine", "Unklar"],
            color_range=["#6D597A", "#2A9D8F", "#457B9D", "#8E9AAF"],
            axis_title="Anteil innerhalb Weitere Non-Engine (%)",
            empty_message="Fuer den aktiven Zeitraum konnten keine monatlichen Unterrollenwerte berechnet werden.",
            stacked=True,
        )


st.set_page_config(page_title="Non-Engine Analyse", layout="wide")

database_path = resolve_dashboard_db_path()
repository = DashboardRepository(database_path)

st.title("Non-Engine Analyse")

status_message = repository.status_message()
if status_message is not None:
    st.warning(status_message)
    st.stop()

start_date, end_date = render_dashboard_date_filter(repository)

global_non_engine_cards = repository.list_non_engine_cards(
    classification="non_engine",
    limit=500,
    start_date=start_date,
    end_date=end_date,
)
global_candidate_splash_cards = repository.list_non_engine_cards(
    classification="candidate_splash",
    limit=500,
    start_date=start_date,
    end_date=end_date,
)
monthly_main_share_rows = repository.get_monthly_main_deck_share_trends(
    start_date=start_date, end_date=end_date
)
monthly_side_share_rows = repository.get_monthly_side_deck_share_trends(
    start_date=start_date, end_date=end_date
)
monthly_subrole_rows = repository.get_monthly_non_engine_subrole_trends(
    start_date=start_date, end_date=end_date
)
monthly_section_balance_rows = (
    repository.get_monthly_section_engine_vs_non_engine_trends(
        start_date=start_date,
        end_date=end_date,
    )
)
normalized_non_engine_rows = _normalize_global_rows(
    global_non_engine_cards, "non_engine"
)
normalized_candidate_splash_rows = _normalize_global_rows(
    global_candidate_splash_cards, "candidate_splash"
)
combined_rows = normalized_non_engine_rows + normalized_candidate_splash_rows

st.markdown(
    "Die Klassifikation kombiniert Verbreitungssignale mit Kartenmetadaten aus der YGOPRODeck-API. `Non-Engine` bedeutet breite Verteilung bei niedriger Gruppenkonzentration und geringem Archetype-Match zur Deckgruppe. `Candidate Splash` markiert wiederkehrende Pakete zwischen Engine und echter Staple."
)

st.caption(
    "`Archetype Match %` zeigt, wie stark eine Karte in Deckgruppen auftaucht, deren Name den Karten-Archetype traegt. Hohe Werte sprechen eher fuer Engine als fuer generische Non-Engine."
)

st.info(
    "`Ø Main / Deck` und `Ø Side / Deck` mitteln ueber alle aktuell gefilterten Decks, fehlende Vorkommen zaehlen also als 0. `Main >=1 %` und `Side >=1 %` zeigen den Anteil der Decks, in denen die Karte im jeweiligen Bereich mindestens einmal vorkommt. `Ø Kopien bei Nutzung` mittelt nur ueber Decks, die die Karte mindestens einmal in Main oder Side spielen."
)

st.caption(
    "Die Unterrollen fuer echte Non-Engine-Karten werden heuristisch aus Kartentext, Typ, Frame-Typ und Main-vs-Side-Nutzung abgeleitet. Es gibt bewusst keine manuell gepflegte Karten-Namensliste."
)

_section_header(
    "Uebersicht",
    "Der Kopfbereich verdichtet den globalen Kartenpool in grobe Verbreitungs-, Konzentrations- und Kostenindikatoren.",
)
_render_overview_metrics(normalized_non_engine_rows, normalized_candidate_splash_rows)

st.caption(
    "`Main-first` und `Side-first` nutzen einen Abstand von mindestens 15 Prozentpunkten zwischen Main >=1 % und Side >=1 %. Dazwischen wird die Karte als `Hybrid` gelesen."
)

st.divider()

_section_header(
    "Candidate Splash Grenze",
    "Diese Sicht macht den Uebergangsraum zwischen echter Staple und archetypenahem Paket sichtbar. Candidate Splash wird gegen den Non-Engine-Kontext in derselben Grenzlandkarte gespiegelt.",
)
_render_candidate_splash_summary(normalized_candidate_splash_rows)
_render_candidate_splash_boundary_chart(
    normalized_non_engine_rows, normalized_candidate_splash_rows
)

st.divider()

_section_header(
    "Karten-Explorer",
    "Die folgenden Filter steuern Rollenmix, Scatterplots und Tabelle gemeinsam. So laesst sich der globale Pool als Staple-Landkarte statt als reine Rohliste lesen.",
)

pool_col, role_col, profile_col, confidence_col = st.columns(4)
selected_pool = pool_col.radio(
    "Kartenpool",
    options=["Non-Engine", "Candidate Splash", "Beide"],
    horizontal=True,
)

base_rows = combined_rows
if selected_pool == "Non-Engine":
    base_rows = normalized_non_engine_rows
elif selected_pool == "Candidate Splash":
    base_rows = normalized_candidate_splash_rows

role_options = sorted({str(row["role_label"]) for row in base_rows})
selected_roles = role_col.multiselect("Rollen", options=role_options)

profile_options = [
    profile
    for profile in ["Main-first", "Side-first", "Hybrid", "-"]
    if any(str(row["usage_profile_label"]) == profile for row in base_rows)
]
selected_profiles = profile_col.multiselect("Nutzungsprofil", options=profile_options)

confidence_options = sorted({str(row["confidence_label"]) for row in base_rows})
selected_confidences = confidence_col.multiselect(
    "Sicherheit", options=confidence_options
)

slider_col_1, slider_col_2, slider_col_3, slider_col_4 = st.columns(4)
min_inclusion_pct = slider_col_1.slider(
    "Min Globale Inklusion %", min_value=0.0, max_value=100.0, value=0.0, step=1.0
)
min_spread_pct = slider_col_2.slider(
    "Min Deckgruppen-Spread %", min_value=0.0, max_value=100.0, value=0.0, step=1.0
)
price_upper_bound = max(
    1.0,
    round(
        max(
            (
                float(row.get("average_cardmarket_price_eur") or 0.0)
                for row in base_rows
            ),
            default=0.0,
        ),
        2,
    ),
)
price_step = 0.25 if price_upper_bound > 10.0 else 0.05
selected_price_range = slider_col_3.slider(
    "Ø Cardmarket €",
    min_value=0.0,
    max_value=float(price_upper_bound),
    value=(0.0, float(price_upper_bound)),
    step=float(price_step),
)
sort_mode = slider_col_4.selectbox(
    "Sortierung",
    options=[
        "Globale Inklusion",
        "Deckgruppen-Spread",
        "Erwarteter Deckkostenbeitrag",
        "Ø Cardmarket",
        "Deckgruppen",
        "Deckvorkommen",
        "Karte",
    ],
    index=0,
)

filtered_rows = _filter_global_rows(
    base_rows,
    roles=selected_roles,
    usage_profiles=selected_profiles,
    confidence_levels=selected_confidences,
    min_inclusion_pct=min_inclusion_pct,
    min_spread_pct=min_spread_pct,
    price_range=selected_price_range,
)
sorted_filtered_rows = _sort_global_rows(filtered_rows, sort_mode)

filtered_metric_cols = st.columns(5)
filtered_metric_cols[0].metric("Karten im Filter", len(sorted_filtered_rows))
filtered_metric_cols[1].metric(
    "Rollen im Filter", len({str(row["role_label"]) for row in sorted_filtered_rows})
)
filtered_metric_cols[2].metric(
    "Median Inklusion",
    _format_percent(_numeric_median(sorted_filtered_rows, "global_inclusion_rate_pct")),
)
filtered_metric_cols[3].metric(
    "Median Spread",
    _format_percent(_numeric_median(sorted_filtered_rows, "deck_group_spread_pct")),
)
filtered_metric_cols[4].metric(
    "Median Deckkostenbeitrag",
    _format_currency(
        _numeric_median(sorted_filtered_rows, "expected_deck_cost_contribution_eur")
    ),
)

st.caption(
    f"Aktueller Pool: {selected_pool}. Nach Filtern bleiben {len(sorted_filtered_rows)} Karten uebrig. Die Visualisierungen lesen denselben Filterzustand wie die Tabelle."
)

chart_tab_1, chart_tab_2, chart_tab_3 = st.tabs(
    ["Rollenmix", "Universell vs konzentriert", "Main vs Side"]
)

with chart_tab_1:
    st.caption(
        "Der Rollenmix zeigt, welche Unterklassen im aktuellen Filter dominieren und wie breit diese Rollen im Feld verteilt sind."
    )
    _render_role_mix_chart(sorted_filtered_rows)

with chart_tab_2:
    st.caption(
        "Weit rechts und gleichzeitig tief liegende Punkte sind die universalsten Staples: hohe Deckgruppen-Breite bei niedriger Konzentration auf einzelne Deckgruppen."
    )
    _render_universal_vs_concentrated_scatter(sorted_filtered_rows)

with chart_tab_3:
    st.caption(
        "Die Main-vs-Side-Landkarte trennt Main-Staples, Side-Bullets und Hybrid-Karten; die Punktgroesse approximiert den durchschnittlichen Cardmarket-Kostenbeitrag pro Deck."
    )
    _render_main_vs_side_scatter(sorted_filtered_rows)

st.divider()

_section_header(
    "Performance-Layer",
    "Diese Sicht verbindet card-level Verbreitung mit Resultatmetriken aus den beobachteten Listen derselben Karten. Sie folgt denselben Explorer-Filtern wie Charts und Tabelle.",
)
_render_performance_summary(sorted_filtered_rows)

performance_tab_1, performance_tab_2, performance_tab_3 = st.tabs(
    ["Inklusion vs Performance", "Kosten vs Performance", "Rollen-Benchmark"]
)

with performance_tab_1:
    st.caption(
        "Je weiter oben ein Punkt liegt, desto besser ist das typische Platzierungs-Perzentil der Listen mit dieser Karte. Die Farbe zeigt das Delta zum Feldmittel desselben Zeitraums."
    )
    _render_inclusion_vs_performance_scatter(sorted_filtered_rows)

with performance_tab_2:
    st.caption(
        "Hier wird der erwartete Deckkostenbeitrag gegen den Median der beobachteten Resultate gelegt. Die Punktgroesse bleibt die globale Inklusion, damit teure Nischenkarten nicht wie Meta-Staples wirken."
    )
    _render_cost_vs_performance_scatter(sorted_filtered_rows)

with performance_tab_3:
    st.caption(
        "Der Rollen-Benchmark verdichtet die card-level Performance in einen Rollenblick. Relevant ist vor allem das Median-Delta zum Feld, nicht nur das absolute Perzentil."
    )
    _render_role_performance_chart(sorted_filtered_rows)

st.divider()

_section_header(
    "Karten-Drilldown",
    "Fuer die aktuell gefilterten Karten lassen sich hier die Deckgruppen mit dem staerksten Uebergewicht und ein direkter Sprung auf die Deckgruppen-Details-Seite auswaehlen.",
)

if sorted_filtered_rows:
    card_option_labels = [_card_drilldown_label(row) for row in sorted_filtered_rows]
    card_rows_by_label = {
        _card_drilldown_label(row): row for row in sorted_filtered_rows
    }
    if st.session_state.get(CARD_DRILLDOWN_STATE_KEY) not in card_option_labels:
        st.session_state[CARD_DRILLDOWN_STATE_KEY] = card_option_labels[0]

    selected_card_label = st.selectbox(
        "Karte fuer Gruppen-Drilldown",
        options=card_option_labels,
        key=CARD_DRILLDOWN_STATE_KEY,
    )
    selected_card_row = card_rows_by_label[selected_card_label]
    card_group_rows = repository.list_deck_groups_for_non_engine_card(
        str(selected_card_row["card_name"]),
        classification=str(selected_card_row["classification_key"]),
        limit=25,
        start_date=start_date,
        end_date=end_date,
    )

    if card_group_rows:
        top_inclusion_row = max(
            card_group_rows,
            key=lambda row: (
                float(row.get("group_inclusion_rate_pct") or 0.0),
                str(row["deck_name"]),
            ),
        )
        top_share_row = max(
            card_group_rows,
            key=lambda row: (
                float(row.get("card_group_share_pct") or 0.0),
                str(row["deck_name"]),
            ),
        )
        best_group_row = max(
            card_group_rows,
            key=lambda row: (
                float(row.get("median_placement_percentile") or 0.0),
                str(row["deck_name"]),
            ),
        )

        drilldown_metric_cols = st.columns(4)
        drilldown_metric_cols[0].metric("Deckgruppen mit Karte", len(card_group_rows))
        drilldown_metric_cols[1].metric(
            "Hoechste Gruppen-Inklusion",
            str(top_inclusion_row.get("deck_name") or "-"),
            _format_percent(top_inclusion_row.get("group_inclusion_rate_pct")),
            delta_color="off",
        )
        drilldown_metric_cols[2].metric(
            "Groesster Karten-Share",
            str(top_share_row.get("deck_name") or "-"),
            _format_percent(top_share_row.get("card_group_share_pct")),
            delta_color="off",
        )
        drilldown_metric_cols[3].metric(
            "Bestes Gruppen-Median",
            str(best_group_row.get("deck_name") or "-"),
            _format_percent(best_group_row.get("median_placement_percentile")),
            delta_color="off",
        )

        group_option_names = [str(row["deck_name"]) for row in card_group_rows]
        if (
            st.session_state.get(CARD_GROUP_DRILLDOWN_STATE_KEY)
            not in group_option_names
        ):
            st.session_state[CARD_GROUP_DRILLDOWN_STATE_KEY] = group_option_names[0]

        drilldown_col_1, drilldown_col_2 = st.columns((3, 1))
        selected_group_name = drilldown_col_1.selectbox(
            "Deckgruppe fuer Details",
            options=group_option_names,
            format_func=lambda deck_name: _deck_group_drilldown_label(
                next(
                    row
                    for row in card_group_rows
                    if str(row["deck_name"]) == str(deck_name)
                )
            ),
            key=CARD_GROUP_DRILLDOWN_STATE_KEY,
        )
        if drilldown_col_2.button("Zu Deckgruppen-Details"):
            _open_deck_group(str(selected_group_name))

        st.caption(
            f"Die Gruppenliste fuer {selected_card_row['card_name']} ist auf die aktuell gewaehlte Klassifikation und den aktiven Datumsfilter begrenzt. `Karten-Share` misst, welcher Anteil der beobachteten Decks mit dieser Karte auf die jeweilige Deckgruppe entfaellt."
        )
        st.dataframe(
            [
                {
                    "Deckgruppe": row["deck_name"],
                    "Kartendecks in Gruppe": row["decks_with_card"],
                    "Gruppengroesse": row["deck_group_size"],
                    "Karten-Share %": row["card_group_share_pct"],
                    "Gruppen-Inklusion %": row["group_inclusion_rate_pct"],
                    "Main >=1 %": row["main_presence_pct"],
                    "Side >=1 %": row["side_presence_pct"],
                    "Ø Kopien bei Nutzung": row["average_copies_when_present"],
                    "Median Platzierungs-Perzentil": row["median_placement_percentile"],
                    "Top-25 %": row["top_25_finish_rate_pct"],
                    "Performance-IQR": row["placement_percentile_iqr"],
                }
                for row in card_group_rows
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.info(
            "Fuer die ausgewaehlte Karte konnten im aktiven Zeitraum keine Deckgruppen-Drilldown-Daten berechnet werden."
        )
else:
    st.info("Der aktuelle Filter liefert keine Karten fuer einen Drilldown.")

st.markdown("**Kartenliste**")
_render_global_table(sorted_filtered_rows, "Der aktuelle Filter liefert keine Karten.")

st.divider()

_section_header(
    "Monatlicher Trend",
    "Diese Sektion folgt nur dem globalen Datumsfilter und zeigt, wie sich Non-Engine-Anteile und Unterrollen ueber die Monate verschieben.",
)
_render_monthly_trend_section(
    monthly_section_balance_rows,
    monthly_main_share_rows,
    monthly_side_share_rows,
    monthly_subrole_rows,
)
