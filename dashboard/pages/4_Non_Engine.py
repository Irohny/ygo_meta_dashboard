from __future__ import annotations

from statistics import median

import streamlit as st

from ygo_crawler.dashboard_filters import render_dashboard_date_filter
from ygo_crawler.dashboard_queries import DashboardRepository, resolve_dashboard_db_path


def _format_percent(value: object) -> str:
    if value is None:
        return "-"
    return f"{float(value):.1f}%"


def _format_currency(value: object) -> str:
    if value is None:
        return "-"
    return f"EUR {float(value):.2f}"


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


def _normalize_global_rows(rows: list[dict[str, object]], classification: str) -> list[dict[str, object]]:
    normalized_rows: list[dict[str, object]] = []
    for row in rows:
        normalized_rows.append(
            {
                "image_url_small": row.get("image_url_small"),
                "card_name": str(row.get("card_name") or "-"),
                "classification_label": _classification_label(classification),
                "role_label": str(row.get("non_engine_role_label") or "-"),
                "confidence_label": str(row.get("role_confidence") or "-"),
                "usage_profile_label": _usage_profile_label(row.get("main_presence_pct"), row.get("side_presence_pct")),
                "card_archetype": str(row.get("card_archetype") or "-"),
                "total_decks_with_card": int(row.get("total_decks_with_card") or 0),
                "deck_group_count": int(row.get("deck_group_count") or 0),
                "global_inclusion_rate_pct": float(row.get("global_inclusion_rate_pct") or 0.0),
                "deck_group_spread_pct": float(row.get("deck_group_spread_pct") or 0.0),
                "max_group_share_pct": float(row.get("max_group_share_pct") or 0.0),
                "archetype_match_share_pct": float(row.get("archetype_match_share_pct") or 0.0),
                "average_main_copies_per_deck": float(row.get("average_main_copies_per_deck") or 0.0),
                "average_side_copies_per_deck": float(row.get("average_side_copies_per_deck") or 0.0),
                "main_presence_pct": float(row.get("main_presence_pct") or 0.0),
                "side_presence_pct": float(row.get("side_presence_pct") or 0.0),
                "average_copies_when_present": float(row.get("average_copies_when_present") or 0.0),
                "average_cardmarket_price_eur": float(row.get("average_cardmarket_price_eur") or 0.0),
                "expected_deck_cost_contribution_eur": _expected_deck_cost_contribution(row),
                "total_copies": int(row.get("total_copies") or 0),
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
            "Erwarteter Deckkostenbeitrag €": row["expected_deck_cost_contribution_eur"],
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
        "Globale Inklusion %": st.column_config.NumberColumn("Globale Inklusion %", format="%.1f"),
        "Deckgruppen-Spread %": st.column_config.NumberColumn("Deckgruppen-Spread %", format="%.1f"),
        "Max Gruppenanteil %": st.column_config.NumberColumn("Max Gruppenanteil %", format="%.1f"),
        "Archetype Match %": st.column_config.NumberColumn("Archetype Match %", format="%.1f"),
        "Ø Main / Deck": st.column_config.NumberColumn("Ø Main / Deck", format="%.2f"),
        "Ø Side / Deck": st.column_config.NumberColumn("Ø Side / Deck", format="%.2f"),
        "Main >=1 %": st.column_config.NumberColumn("Main >=1 %", format="%.1f"),
        "Side >=1 %": st.column_config.NumberColumn("Side >=1 %", format="%.1f"),
        "Ø Kopien bei Nutzung": st.column_config.NumberColumn("Ø Kopien bei Nutzung", format="%.2f"),
        "Ø Cardmarket €": st.column_config.NumberColumn("Ø Cardmarket €", format="%.2f"),
        "Erwarteter Deckkostenbeitrag €": st.column_config.NumberColumn("Erwarteter Deckkostenbeitrag €", format="%.2f"),
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
    return sum(1 for row in rows if str(row.get("usage_profile_label") or "-") == profile)


def _render_overview_metrics(
    non_engine_rows: list[dict[str, object]],
    candidate_splash_rows: list[dict[str, object]],
) -> None:
    total_rows = len(non_engine_rows) + len(candidate_splash_rows)
    candidate_share_pct = round(len(candidate_splash_rows) * 100.0 / total_rows, 1) if total_rows > 0 else None

    primary_cols = st.columns(6)
    primary_cols[0].metric("Non-Engine Karten", len(non_engine_rows))
    primary_cols[1].metric("Candidate Splash Karten", len(candidate_splash_rows))
    primary_cols[2].metric("Candidate-Anteil am Pool", _format_percent(candidate_share_pct))
    primary_cols[3].metric("Median Spread Non-Engine", _format_percent(_numeric_median(non_engine_rows, "deck_group_spread_pct")))
    primary_cols[4].metric(
        "Median Max Gruppenanteil Splash",
        _format_percent(_numeric_median(candidate_splash_rows, "max_group_share_pct")),
    )
    primary_cols[5].metric(
        "Median Deckkostenbeitrag Non-Engine",
        _format_currency(_numeric_median(non_engine_rows, "expected_deck_cost_contribution_eur")),
    )

    secondary_cols = st.columns(5)
    secondary_cols[0].metric("Non-Engine Main-first", _count_usage_profile(non_engine_rows, "Main-first"))
    secondary_cols[1].metric("Non-Engine Side-first", _count_usage_profile(non_engine_rows, "Side-first"))
    secondary_cols[2].metric("Non-Engine Hybrid", _count_usage_profile(non_engine_rows, "Hybrid"))
    secondary_cols[3].metric(
        "Median Cardmarket Non-Engine",
        _format_currency(_numeric_median(non_engine_rows, "average_cardmarket_price_eur")),
    )
    secondary_cols[4].metric(
        "Median Archetype Match Splash",
        _format_percent(_numeric_median(candidate_splash_rows, "archetype_match_share_pct")),
    )


def _sort_global_rows(rows: list[dict[str, object]], sort_mode: str) -> list[dict[str, object]]:
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
                "median_inclusion_pct": _numeric_median(matching_rows, "global_inclusion_rate_pct"),
                "median_spread_pct": _numeric_median(matching_rows, "deck_group_spread_pct"),
                "median_cardmarket_eur": _numeric_median(matching_rows, "average_cardmarket_price_eur"),
            }
        )

    domain = [row["role_label"] for row in sorted(role_rows, key=lambda row: (-int(row["card_count"]), str(row["role_label"]))) ]
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
                    {"field": "card_count", "type": "quantitative", "format": ".0f", "title": "Karten"},
                    {"field": "median_inclusion_pct", "type": "quantitative", "format": ".2f", "title": "Median Inklusion %"},
                    {"field": "median_spread_pct", "type": "quantitative", "format": ".2f", "title": "Median Spread %"},
                    {"field": "median_cardmarket_eur", "type": "quantitative", "format": ".2f", "title": "Median Cardmarket EUR"},
                ],
            },
        },
        width="stretch",
    )


def _render_universal_vs_concentrated_scatter(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info("Fuer den aktuellen Filter konnten keine Verteilungsdaten berechnet werden.")
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
                    {"field": "classification_label", "type": "nominal", "title": "Klassifikation"},
                    {"field": "role_label", "type": "nominal", "title": "Rolle"},
                    {"field": "spread_pct", "type": "quantitative", "format": ".2f", "title": "Deckgruppen-Spread %"},
                    {"field": "max_group_share_pct", "type": "quantitative", "format": ".2f", "title": "Max Gruppenanteil %"},
                    {"field": "inclusion_pct", "type": "quantitative", "format": ".2f", "title": "Globale Inklusion %"},
                    {"field": "deck_count", "type": "quantitative", "format": ".0f", "title": "Deckvorkommen"},
                    {"field": "deck_group_count", "type": "quantitative", "format": ".0f", "title": "Deckgruppen"},
                    {"field": "average_cardmarket_eur", "type": "quantitative", "format": ".2f", "title": "Ø Cardmarket EUR"},
                ],
            },
        },
        width="stretch",
    )


def _render_main_vs_side_scatter(rows: list[dict[str, object]]) -> None:
    if not rows:
        st.info("Fuer den aktuellen Filter konnten keine Main-vs-Side-Daten berechnet werden.")
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
            "deck_cost_contribution_eur": float(row.get("expected_deck_cost_contribution_eur") or 0.0),
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
                    {"field": "classification_label", "type": "nominal", "title": "Klassifikation"},
                    {"field": "role_label", "type": "nominal", "title": "Rolle"},
                    {"field": "usage_profile_label", "type": "nominal", "title": "Nutzungsprofil"},
                    {"field": "main_presence_pct", "type": "quantitative", "format": ".2f", "title": "Main >=1 %"},
                    {"field": "side_presence_pct", "type": "quantitative", "format": ".2f", "title": "Side >=1 %"},
                    {"field": "average_copies_when_present", "type": "quantitative", "format": ".2f", "title": "Ø Kopien bei Nutzung"},
                    {"field": "deck_cost_contribution_eur", "type": "quantitative", "format": ".2f", "title": "Erwarteter Deckkostenbeitrag EUR"},
                    {"field": "inclusion_pct", "type": "quantitative", "format": ".2f", "title": "Globale Inklusion %"},
                ],
            },
        },
        width="stretch",
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
normalized_non_engine_rows = _normalize_global_rows(global_non_engine_cards, "non_engine")
normalized_candidate_splash_rows = _normalize_global_rows(global_candidate_splash_cards, "candidate_splash")
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

profile_options = [profile for profile in ["Main-first", "Side-first", "Hybrid", "-"] if any(str(row["usage_profile_label"]) == profile for row in base_rows)]
selected_profiles = profile_col.multiselect("Nutzungsprofil", options=profile_options)

confidence_options = sorted({str(row["confidence_label"]) for row in base_rows})
selected_confidences = confidence_col.multiselect("Sicherheit", options=confidence_options)

slider_col_1, slider_col_2, slider_col_3, slider_col_4 = st.columns(4)
min_inclusion_pct = slider_col_1.slider("Min Globale Inklusion %", min_value=0.0, max_value=100.0, value=0.0, step=1.0)
min_spread_pct = slider_col_2.slider("Min Deckgruppen-Spread %", min_value=0.0, max_value=100.0, value=0.0, step=1.0)
price_upper_bound = max(1.0, round(max((float(row.get("average_cardmarket_price_eur") or 0.0) for row in base_rows), default=0.0), 2))
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
    options=["Globale Inklusion", "Deckgruppen-Spread", "Erwarteter Deckkostenbeitrag", "Ø Cardmarket", "Deckgruppen", "Deckvorkommen", "Karte"],
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
filtered_metric_cols[1].metric("Rollen im Filter", len({str(row['role_label']) for row in sorted_filtered_rows}))
filtered_metric_cols[2].metric("Median Inklusion", _format_percent(_numeric_median(sorted_filtered_rows, "global_inclusion_rate_pct")))
filtered_metric_cols[3].metric("Median Spread", _format_percent(_numeric_median(sorted_filtered_rows, "deck_group_spread_pct")))
filtered_metric_cols[4].metric(
    "Median Deckkostenbeitrag",
    _format_currency(_numeric_median(sorted_filtered_rows, "expected_deck_cost_contribution_eur")),
)

st.caption(
    f"Aktueller Pool: {selected_pool}. Nach Filtern bleiben {len(sorted_filtered_rows)} Karten uebrig. Die Visualisierungen lesen denselben Filterzustand wie die Tabelle."
)

chart_tab_1, chart_tab_2, chart_tab_3 = st.tabs(["Rollenmix", "Universell vs konzentriert", "Main vs Side"])

with chart_tab_1:
    st.caption("Der Rollenmix zeigt, welche Unterklassen im aktuellen Filter dominieren und wie breit diese Rollen im Feld verteilt sind.")
    _render_role_mix_chart(sorted_filtered_rows)

with chart_tab_2:
    st.caption("Weit rechts und gleichzeitig tief liegende Punkte sind die universalsten Staples: hohe Deckgruppen-Breite bei niedriger Konzentration auf einzelne Deckgruppen.")
    _render_universal_vs_concentrated_scatter(sorted_filtered_rows)

with chart_tab_3:
    st.caption("Die Main-vs-Side-Landkarte trennt Main-Staples, Side-Bullets und Hybrid-Karten; die Punktgroesse approximiert den durchschnittlichen Cardmarket-Kostenbeitrag pro Deck.")
    _render_main_vs_side_scatter(sorted_filtered_rows)

st.markdown("**Kartenliste**")
_render_global_table(sorted_filtered_rows, "Der aktuelle Filter liefert keine Karten.")