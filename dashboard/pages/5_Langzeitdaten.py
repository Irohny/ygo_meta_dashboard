from __future__ import annotations

import streamlit as st

from ygo_crawler.dashboard_filters import render_dashboard_date_filter
from ygo_crawler.dashboard_queries import DashboardRepository, resolve_dashboard_db_path


def _render_time_series_chart(
    chart_rows: list[dict[str, object]],
    *,
    y_field: str,
    y_axis_title: str,
    color_domain: list[str],
    color_range: list[str],
    value_format: str,
    empty_message: str,
    extra_tooltip_fields: list[dict[str, object]] | None = None,
) -> None:
    if not chart_rows:
        st.info(empty_message)
        return

    tooltip = [
        {"field": "Monat", "type": "temporal", "title": "Monat", "format": "%Y-%m"},
        {"field": "Serie", "type": "nominal"},
        {"field": y_field, "type": "quantitative", "format": value_format},
    ]
    if extra_tooltip_fields:
        tooltip.extend(extra_tooltip_fields)

    st.vega_lite_chart(
        {
            "data": {"values": chart_rows},
            "height": 420,
            "mark": {"type": "line", "point": True, "tooltip": True},
            "encoding": {
                "x": {
                    "field": "Monat",
                    "type": "temporal",
                    "axis": {"title": None, "format": "%Y-%m"},
                },
                "y": {
                    "field": y_field,
                    "type": "quantitative",
                    "axis": {"title": y_axis_title},
                    "scale": {"zero": True},
                },
                "color": {
                    "field": "Serie",
                    "type": "nominal",
                    "scale": {"domain": color_domain, "range": color_range},
                    "legend": {"title": None, "orient": "bottom"},
                },
                "tooltip": tooltip,
            },
        },
        width="stretch",
    )


def _render_monthly_share_chart(rows: list[dict[str, object]]) -> None:
    chart_rows: list[dict[str, object]] = []
    for row in rows:
        month_start = str(row["month_start"])
        deck_count = int(row["deck_count"])
        chart_rows.extend(
            [
                {
                    "Monat": month_start,
                    "Serie": "Engine",
                    "Anteil %": float(row["average_engine_share_pct"]),
                    "Decks": deck_count,
                },
                {
                    "Monat": month_start,
                    "Serie": "Handtraps",
                    "Anteil %": float(row["average_handtrap_share_pct"]),
                    "Decks": deck_count,
                },
                {
                    "Monat": month_start,
                    "Serie": "Boardbreaker",
                    "Anteil %": float(row["average_boardbreaker_share_pct"]),
                    "Decks": deck_count,
                },
            ]
        )

    _render_time_series_chart(
        chart_rows,
        y_field="Anteil %",
        y_axis_title="Mittlerer Anteil am Main Deck (%)",
        color_domain=["Engine", "Handtraps", "Boardbreaker"],
        color_range=["#1D3557", "#E76F51", "#F4A261"],
        value_format=".2f",
        empty_message="Fuer den aktuellen Zeitraum konnten keine Monatswerte berechnet werden.",
        extra_tooltip_fields=[{"field": "Decks", "type": "quantitative"}],
    )


def _render_monthly_concentration_chart(rows: list[dict[str, object]]) -> None:
    chart_rows: list[dict[str, object]] = []
    for row in rows:
        month_start = str(row["month_start"])
        result_count = int(row["result_count"])
        distinct_deck_names = int(row["distinct_deck_names"])
        chart_rows.extend(
            [
                {
                    "Monat": month_start,
                    "Serie": "25 % der Ergebnisse",
                    "Decknamen": int(row["deck_names_for_25_pct"]),
                    "Ergebnisse": result_count,
                    "Distinct Decknamen": distinct_deck_names,
                },
                {
                    "Monat": month_start,
                    "Serie": "50 % der Ergebnisse",
                    "Decknamen": int(row["deck_names_for_50_pct"]),
                    "Ergebnisse": result_count,
                    "Distinct Decknamen": distinct_deck_names,
                },
                {
                    "Monat": month_start,
                    "Serie": "75 % der Ergebnisse",
                    "Decknamen": int(row["deck_names_for_75_pct"]),
                    "Ergebnisse": result_count,
                    "Distinct Decknamen": distinct_deck_names,
                },
                {
                    "Monat": month_start,
                    "Serie": "90 % der Ergebnisse",
                    "Decknamen": int(row["deck_names_for_90_pct"]),
                    "Ergebnisse": result_count,
                    "Distinct Decknamen": distinct_deck_names,
                },
            ]
        )

    _render_time_series_chart(
        chart_rows,
        y_field="Decknamen",
        y_axis_title="Benoetigte Decknamen",
        color_domain=[
            "25 % der Ergebnisse",
            "50 % der Ergebnisse",
            "75 % der Ergebnisse",
            "90 % der Ergebnisse",
        ],
        color_range=["#1D3557", "#457B9D", "#F4A261", "#E76F51"],
        value_format=".0f",
        empty_message="Fuer den aktuellen Zeitraum konnten keine Diversitaetswerte berechnet werden.",
        extra_tooltip_fields=[
            {"field": "Ergebnisse", "type": "quantitative"},
            {"field": "Distinct Decknamen", "type": "quantitative"},
        ],
    )


def _render_monthly_new_deck_name_share_chart(rows: list[dict[str, object]]) -> None:
    chart_rows = [
        {
            "Monat": str(row["month_start"]),
            "Serie": "Neue Decknamen",
            "Anteil %": float(row["new_result_share_pct"]),
            "Neue Decknamen": int(row["new_deck_name_count"]),
            "Neue Ergebnisse": int(row["new_result_count"]),
            "Ergebnisse": int(row["result_count"]),
            "Distinct Decknamen": int(row["distinct_deck_names"]),
        }
        for row in rows
        if row["new_result_share_pct"] is not None
        and row["new_deck_name_count"] is not None
        and row["new_result_count"] is not None
    ]
    _render_time_series_chart(
        chart_rows,
        y_field="Anteil %",
        y_axis_title="Anteil neuer Decknamen an Monatsergebnissen (%)",
        color_domain=["Neue Decknamen"],
        color_range=["#2A9D8F"],
        value_format=".2f",
        empty_message="Fuer den aktuellen Zeitraum konnten keine Werte fuer neue Decknamen berechnet werden.",
        extra_tooltip_fields=[
            {"field": "Neue Decknamen", "type": "quantitative"},
            {"field": "Neue Ergebnisse", "type": "quantitative"},
            {"field": "Ergebnisse", "type": "quantitative"},
            {"field": "Distinct Decknamen", "type": "quantitative"},
        ],
    )


def _render_monthly_side_share_chart(rows: list[dict[str, object]]) -> None:
    chart_rows: list[dict[str, object]] = []
    for row in rows:
        month_start = str(row["month_start"])
        deck_count = int(row["deck_count"])
        chart_rows.extend(
            [
                {
                    "Monat": month_start,
                    "Serie": "Handtraps",
                    "Anteil %": float(row["average_handtrap_share_pct"]),
                    "Decks": deck_count,
                },
                {
                    "Monat": month_start,
                    "Serie": "Boardbreaker",
                    "Anteil %": float(row["average_boardbreaker_share_pct"]),
                    "Decks": deck_count,
                },
                {
                    "Monat": month_start,
                    "Serie": "Weitere Non-Engine",
                    "Anteil %": float(row["average_non_engine_other_share_pct"]),
                    "Decks": deck_count,
                },
            ]
        )
    _render_time_series_chart(
        chart_rows,
        y_field="Anteil %",
        y_axis_title="Mittlerer Anteil am Side Deck (%)",
        color_domain=["Handtraps", "Boardbreaker", "Weitere Non-Engine"],
        color_range=["#E76F51", "#F4A261", "#E9C46A"],
        value_format=".2f",
        empty_message="Fuer den aktuellen Zeitraum konnten keine Side-Deck-Anteile berechnet werden.",
        extra_tooltip_fields=[{"field": "Decks", "type": "quantitative"}],
    )


def _render_monthly_non_engine_subrole_chart(rows: list[dict[str, object]]) -> None:
    chart_rows: list[dict[str, object]] = []
    for row in rows:
        month_start = str(row["month_start"])
        deck_count = int(row["deck_count"])
        chart_rows.extend(
            [
                {
                    "Monat": month_start,
                    "Serie": "Floodgates",
                    "Anteil %": float(row["average_floodgate_share_pct"]),
                    "Decks": deck_count,
                },
                {
                    "Monat": month_start,
                    "Serie": "Protection",
                    "Anteil %": float(row["average_protection_share_pct"]),
                    "Decks": deck_count,
                },
                {
                    "Monat": month_start,
                    "Serie": "Draw Engine",
                    "Anteil %": float(row["average_draw_engine_share_pct"]),
                    "Decks": deck_count,
                },
            ]
        )
    _render_time_series_chart(
        chart_rows,
        y_field="Anteil %",
        y_axis_title="Anteil innerhalb von Weitere Non-Engine (%)",
        color_domain=["Floodgates", "Protection", "Draw Engine"],
        color_range=["#264653", "#6D597A", "#2A9D8F"],
        value_format=".2f",
        empty_message="Fuer den aktuellen Zeitraum konnten keine Unterrollen fuer Weitere Non-Engine berechnet werden.",
        extra_tooltip_fields=[{"field": "Decks", "type": "quantitative"}],
    )


def _render_section_engine_vs_non_engine_chart(rows: list[dict[str, object]], section: str) -> None:
    section_label = "Main Deck" if section == "main" else "Side Deck"
    chart_rows: list[dict[str, object]] = []
    for row in rows:
        if str(row["section"]) != section:
            continue
        month_start = str(row["month_start"])
        deck_count = int(row["deck_count"])
        chart_rows.extend(
            [
                {
                    "Monat": month_start,
                    "Serie": "Engine",
                    "Anteil %": float(row["average_engine_share_pct"]),
                    "Decks": deck_count,
                },
                {
                    "Monat": month_start,
                    "Serie": "Non-Engine",
                    "Anteil %": float(row["average_non_engine_share_pct"]),
                    "Decks": deck_count,
                },
            ]
        )
    _render_time_series_chart(
        chart_rows,
        y_field="Anteil %",
        y_axis_title=f"Mittlerer Anteil am {section_label} (%)",
        color_domain=["Engine", "Non-Engine"],
        color_range=["#1D3557", "#E76F51"],
        value_format=".2f",
        empty_message=f"Fuer den aktuellen Zeitraum konnten keine Engine-vs-Non-Engine-Werte fuer {section_label} berechnet werden.",
        extra_tooltip_fields=[{"field": "Decks", "type": "quantitative"}],
    )


def _render_monthly_top_deck_cost_chart(rows: list[dict[str, object]]) -> None:
    chart_rows: list[dict[str, object]] = []
    for row in rows:
        month_start = str(row["month_start"])
        result_count = int(row["result_count"])
        top_10_deck_name_count = int(row["top_10_deck_name_count"])
        top_10_result_share_pct = float(row["top_10_result_share_pct"])
        chart_rows.extend(
            [
                {
                    "Monat": month_start,
                    "Serie": "Top 10 ungewichtet",
                    "Kosten €": float(row["average_top_10_cardmarket_price_eur"]),
                    "Ergebnisse": result_count,
                    "Top Decknamen": top_10_deck_name_count,
                    "Top-10 Share %": top_10_result_share_pct,
                },
                {
                    "Monat": month_start,
                    "Serie": "Top 10 ergebnisgewichtet",
                    "Kosten €": float(row["weighted_average_top_10_cardmarket_price_eur"]),
                    "Ergebnisse": result_count,
                    "Top Decknamen": top_10_deck_name_count,
                    "Top-10 Share %": top_10_result_share_pct,
                },
            ]
        )
    _render_time_series_chart(
        chart_rows,
        y_field="Kosten €",
        y_axis_title="Mittlere Cardmarket-Summe der Top-10-Decknamen (€)",
        color_domain=["Top 10 ungewichtet", "Top 10 ergebnisgewichtet"],
        color_range=["#457B9D", "#F4A261"],
        value_format=".2f",
        empty_message="Fuer den aktuellen Zeitraum konnten keine Kostenwerte der Top-Decks berechnet werden.",
        extra_tooltip_fields=[
            {"field": "Ergebnisse", "type": "quantitative"},
            {"field": "Top Decknamen", "type": "quantitative"},
            {"field": "Top-10 Share %", "type": "quantitative", "format": ".2f"},
        ],
    )


st.set_page_config(page_title="Langzeitdaten", layout="wide")

database_path = resolve_dashboard_db_path()
repository = DashboardRepository(database_path)

st.title("Langzeitdaten")

status_message = repository.status_message()
if status_message is not None:
    st.warning(status_message)
    st.stop()

start_date, end_date = render_dashboard_date_filter(repository)

trend_rows = repository.get_monthly_main_deck_share_trends(start_date=start_date, end_date=end_date)
side_trend_rows = repository.get_monthly_side_deck_share_trends(start_date=start_date, end_date=end_date)
subrole_trend_rows = repository.get_monthly_non_engine_subrole_trends(start_date=start_date, end_date=end_date)
section_trend_rows = repository.get_monthly_section_engine_vs_non_engine_trends(start_date=start_date, end_date=end_date)
new_deck_name_rows = repository.get_monthly_new_deck_name_share_trends(start_date=start_date, end_date=end_date)
concentration_rows = repository.get_monthly_deck_result_concentration_trends(start_date=start_date, end_date=end_date)
top_deck_cost_rows = repository.get_monthly_top_deck_cost_trends(start_date=start_date, end_date=end_date)
if not trend_rows:
    st.warning("Fuer den ausgewaehlten Zeitraum liegen keine Monatsaggregate vor.")
    st.stop()

st.markdown(
    "Die Seite aggregiert monatlich ueber alle aktuell gefilterten Decks und kombiniert Deckzusammensetzung, Formatdiversitaet, Metawechsel und Kostenentwicklung. `Engine` umfasst Hauptengine und restliche Engine. `Handtraps`, `Boardbreaker` und die weiteren Unterrollen nutzen dieselbe heuristische Non-Engine-Unterklassifikation wie die anderen Dashboard-Seiten."
)
st.caption(
    "Je nach Plot beziehen sich die Prozentwerte auf das Main Deck, das Side Deck, alle Monatsergebnisse oder auf den Bucket `Weitere Non-Engine`. Die Beschriftung unter jedem Chart nennt die jeweilige Bezugsbasis."
)

latest_new_share = None
if new_deck_name_rows and new_deck_name_rows[-1]["new_result_share_pct"] is not None:
    latest_new_share = float(new_deck_name_rows[-1]["new_result_share_pct"])

summary_col_1, summary_col_2, summary_col_3, summary_col_4 = st.columns(4)
summary_col_1.metric("Monate", len(trend_rows))
summary_col_2.metric("Neuester Monat", str(trend_rows[-1]["month_start"])[:7])
summary_col_3.metric("Decks im neuesten Monat", int(trend_rows[-1]["deck_count"]))
summary_col_4.metric("Neue Decknamen im neuesten Monat", f"{latest_new_share:.2f}%" if latest_new_share is not None else "-")

st.subheader("Monatlicher Main-Deck-Anteil")
st.caption(
    "Die Linien zeigen monatlich gemittelte Anteile im Main Deck ueber alle aktuell gefilterten Decks. `Engine` umfasst Hauptengine und restliche Engine."
)
_render_monthly_share_chart(trend_rows)

with st.expander("Monatswerte anzeigen"):
    st.dataframe(
        [
            {
                "Monat": str(row["month_start"])[:7],
                "Decks": int(row["deck_count"]),
                "Ø Engine %": float(row["average_engine_share_pct"]),
                "Ø Handtraps %": float(row["average_handtrap_share_pct"]),
                "Ø Boardbreaker %": float(row["average_boardbreaker_share_pct"]),
            }
            for row in trend_rows
        ],
        hide_index=True,
        width="stretch",
    )

st.subheader("Engine vs Non-Engine nach Deckbereich")
st.caption(
    "Hier werden fuer Main Deck und Side Deck getrennt die mittleren Monatsanteile von Engine und echter Non-Engine gezeigt."
)
main_col, side_col = st.columns(2)
with main_col:
    st.markdown("**Main Deck**")
    _render_section_engine_vs_non_engine_chart(section_trend_rows, "main")
with side_col:
    st.markdown("**Side Deck**")
    _render_section_engine_vs_non_engine_chart(section_trend_rows, "side")

with st.expander("Engine-vs-Non-Engine-Werte anzeigen"):
    st.dataframe(
        [
            {
                "Monat": str(row["month_start"])[:7],
                "Deckbereich": "Main Deck" if row["section"] == "main" else "Side Deck",
                "Decks": int(row["deck_count"]),
                "Ø Engine %": float(row["average_engine_share_pct"]),
                "Ø Non-Engine %": float(row["average_non_engine_share_pct"]),
            }
            for row in section_trend_rows
        ],
        hide_index=True,
        width="stretch",
    )

st.subheader("Monatlicher Side-Deck-Anteil")
st.caption(
    "Dieser Plot zeigt, wie sich Handtraps, Boardbreaker und `Weitere Non-Engine` im Side Deck ueber die Zeit verschieben."
)
_render_monthly_side_share_chart(side_trend_rows)

with st.expander("Side-Deck-Werte anzeigen"):
    st.dataframe(
        [
            {
                "Monat": str(row["month_start"])[:7],
                "Decks": int(row["deck_count"]),
                "Ø Handtraps %": float(row["average_handtrap_share_pct"]),
                "Ø Boardbreaker %": float(row["average_boardbreaker_share_pct"]),
                "Ø Weitere Non-Engine %": float(row["average_non_engine_other_share_pct"]),
            }
            for row in side_trend_rows
        ],
        hide_index=True,
        width="stretch",
    )

st.subheader("Unterrollen innerhalb von Weitere Non-Engine")
st.caption(
    "Die Linien zeigen, wie sich Floodgates, Protection und Draw Engine innerhalb des Buckets `Weitere Non-Engine` ueber Main und Side zusammen entwickeln. Unklare Faelle bleiben im Tabellen-Expander sichtbar."
)
_render_monthly_non_engine_subrole_chart(subrole_trend_rows)

with st.expander("Unterrollenwerte anzeigen"):
    st.dataframe(
        [
            {
                "Monat": str(row["month_start"])[:7],
                "Decks": int(row["deck_count"]),
                "Ø Floodgates %": float(row["average_floodgate_share_pct"]),
                "Ø Protection %": float(row["average_protection_share_pct"]),
                "Ø Draw Engine %": float(row["average_draw_engine_share_pct"]),
                "Ø Unklar %": float(row["average_unknown_share_pct"]),
            }
            for row in subrole_trend_rows
        ],
        hide_index=True,
        width="stretch",
    )

st.subheader("Anteil neuer Decknamen pro Monat")
st.caption(
    "Gezeigt wird der Anteil der Monatsergebnisse, die von Decknamen stammen, die im direkt vorherigen verfuegbaren Monat noch nicht vorkamen. Der erste Monat bleibt ohne Vergleichspunkt leer."
)
_render_monthly_new_deck_name_share_chart(new_deck_name_rows)

with st.expander("Neue-Decknamen-Werte anzeigen"):
    st.dataframe(
        [
            {
                "Monat": str(row["month_start"])[:7],
                "Ergebnisse": int(row["result_count"]),
                "Distinct Decknamen": int(row["distinct_deck_names"]),
                "Neue Decknamen": row["new_deck_name_count"],
                "Neue Ergebnisse": row["new_result_count"],
                "Neue Ergebnisanteile %": row["new_result_share_pct"],
            }
            for row in new_deck_name_rows
        ],
        hide_index=True,
        width="stretch",
    )

st.subheader("Formatdiversitaet nach Ergebnisabdeckung")
st.caption(
    "Die Linien zeigen, wie viele unterschiedliche Decknamen in einem Monat noetig sind, um zusammen 25 %, 50 %, 75 % oder 90 % aller gespeicherten Turnierergebnisse abzudecken. Niedrigere Werte sprechen fuer ein konzentrierteres, hoehere Werte fuer ein diverseres Format."
)
_render_monthly_concentration_chart(concentration_rows)

with st.expander("Diversitaetswerte anzeigen"):
    st.dataframe(
        [
            {
                "Monat": str(row["month_start"])[:7],
                "Ergebnisse": int(row["result_count"]),
                "Distinct Decknamen": int(row["distinct_deck_names"]),
                "Decknamen fuer 25 %": int(row["deck_names_for_25_pct"]),
                "Decknamen fuer 50 %": int(row["deck_names_for_50_pct"]),
                "Decknamen fuer 75 %": int(row["deck_names_for_75_pct"]),
                "Decknamen fuer 90 %": int(row["deck_names_for_90_pct"]),
            }
            for row in concentration_rows
        ],
        hide_index=True,
        width="stretch",
    )

st.subheader("Kosten der Top-Decks ueber Zeit")
st.caption(
    "Die Top-10-Decknamen werden je Monat nach Ergebnisanteil bestimmt. Der Plot zeigt ihre mittlere Cardmarket-Summe einmal ungewichtet und einmal ergebnisgewichtet."
)
_render_monthly_top_deck_cost_chart(top_deck_cost_rows)

with st.expander("Top-Deck-Kosten anzeigen"):
    st.dataframe(
        [
            {
                "Monat": str(row["month_start"])[:7],
                "Ergebnisse": int(row["result_count"]),
                "Top-10 Decknamen": int(row["top_10_deck_name_count"]),
                "Top-10 Ergebnisanteil %": float(row["top_10_result_share_pct"]),
                "Ø Top 10 ungewichtet €": float(row["average_top_10_cardmarket_price_eur"]),
                "Ø Top 10 ergebnisgewichtet €": float(row["weighted_average_top_10_cardmarket_price_eur"]),
            }
            for row in top_deck_cost_rows
        ],
        hide_index=True,
        width="stretch",
    )