from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import sys
from typing import Any

from .config import (
    DEFAULT_DATABASE_PATH,
    NON_ENGINE_MAX_ARCHETYPE_MATCH_SHARE,
    NON_ENGINE_MAX_GROUP_SHARE,
    NON_ENGINE_MIN_DECK_GROUPS,
    NON_ENGINE_MIN_GROUP_SPREAD_RATIO,
    NON_ENGINE_MIN_TOTAL_DECKS,
    NON_ENGINE_SPLASH_MAX_GROUP_SHARE,
    NON_ENGINE_SPLASH_MIN_DECK_GROUPS,
    NON_ENGINE_SPLASH_MIN_TOTAL_DECKS,
)
from .non_engine_roles import classify_non_engine_role, format_non_engine_role_label


@dataclass(slots=True, frozen=True)
class DashboardKpis:
    crawled_decks: int
    distinct_deck_names: int


@dataclass(slots=True, frozen=True)
class DatabaseSummary:
    runs: int
    tournaments: int
    entries: int
    decks: int
    deck_cards: int
    skipped_sources: int


class DashboardRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def status_message(self) -> str | None:
        if not self.database_path.exists():
            return f"Die Datenbank {self.database_path} existiert noch nicht. Starte zuerst einen Crawl."

        try:
            row = self._fetch_one(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'view'
                  AND name = 'dashboard_deck_summary_v'
                """
            )
        except sqlite3.Error as exc:
            return f"Die Datenbank konnte nicht gelesen werden: {exc}"

        if row is None:
            return "Die Dashboard-Views fehlen in der Datenbank. Initialisiere das Schema erneut."
        return None

    def get_available_date_range(self) -> tuple[date, date] | None:
        row = self._fetch_one(
            """
            SELECT
                MIN(t.tournament_date) AS min_date,
                MAX(t.tournament_date) AS max_date
            FROM decks d
            JOIN tournaments t ON t.tournament_site_id = d.tournament_site_id
            """
        )
        if row is None or row["min_date"] is None or row["max_date"] is None:
            row = self._fetch_one(
                """
                SELECT
                    MIN(tournament_date) AS min_date,
                    MAX(tournament_date) AS max_date
                FROM tournaments
                """
            )
        if row is None or row["min_date"] is None or row["max_date"] is None:
            return None
        return (date.fromisoformat(str(row["min_date"])), date.fromisoformat(str(row["max_date"])))

    def get_kpis(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> DashboardKpis:
        cte_sql, cte_parameters = self._deck_summaries_with_prices_cte(start_date, end_date)
        row = self._fetch_one(
            f"""
            WITH {cte_sql}
            SELECT
                COUNT(*) AS crawled_decks,
                COUNT(DISTINCT deck_name) AS distinct_deck_names
            FROM filtered_deck_summaries
            """,
            cte_parameters,
        )
        if row is None:
            return DashboardKpis(crawled_decks=0, distinct_deck_names=0)
        return DashboardKpis(
            crawled_decks=int(row["crawled_decks"]),
            distinct_deck_names=int(row["distinct_deck_names"]),
        )

    def get_database_summary(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> DatabaseSummary:
        tournament_filter_sql, tournament_filter_parameters = self._date_filter_clause(
            "tournament_date",
            start_date,
            end_date,
            prefix="WHERE",
        )
        row = self._fetch_one(
            f"""
            WITH filtered_tournaments AS (
                SELECT tournament_site_id
                FROM tournaments
                {tournament_filter_sql}
            ),
            filtered_entries AS (
                SELECT entry_id
                FROM tournament_entries
                WHERE tournament_site_id IN (SELECT tournament_site_id FROM filtered_tournaments)
            ),
            filtered_decks AS (
                SELECT deck_site_id
                FROM decks
                WHERE tournament_site_id IN (SELECT tournament_site_id FROM filtered_tournaments)
            )
            SELECT
                (SELECT COUNT(*) FROM crawl_runs) AS runs,
                (SELECT COUNT(*) FROM filtered_tournaments) AS tournaments,
                (SELECT COUNT(*) FROM filtered_entries) AS entries,
                (SELECT COUNT(*) FROM filtered_decks) AS decks,
                (
                    SELECT COUNT(*)
                    FROM deck_cards dc
                    JOIN filtered_decks fd ON fd.deck_site_id = dc.deck_site_id
                ) AS deck_cards,
                (SELECT COUNT(*) FROM skipped_sources) AS skipped_sources
            """,
            tournament_filter_parameters,
        )
        if row is None:
            return DatabaseSummary(0, 0, 0, 0, 0, 0)
        return DatabaseSummary(
            runs=int(row["runs"]),
            tournaments=int(row["tournaments"]),
            entries=int(row["entries"]),
            decks=int(row["decks"]),
            deck_cards=int(row["deck_cards"]),
            skipped_sources=int(row["skipped_sources"]),
        )

    def list_deck_summaries(
        self,
        limit: int = 250,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        cte_sql, cte_parameters = self._deck_summaries_with_prices_cte(start_date, end_date)
        rows = self._fetch_all(
            f"""
            WITH {cte_sql}
            SELECT
                deck_site_id,
                deck_name,
                player_name,
                placement,
                participants_count,
                archetype_text,
                tournament_name,
                tournament_date,
                country,
                main_card_total,
                extra_card_total,
                side_card_total,
                cardmarket_deck_price_eur,
                deck_url
            FROM filtered_deck_summaries
            ORDER BY tournament_date DESC, placement_sort_value ASC, deck_name ASC
            LIMIT ?
            """,
            cte_parameters + (limit,),
        )
        return [dict(row) for row in rows]

    def get_deck_summary(
        self,
        deck_site_id: int,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> dict[str, Any] | None:
        cte_sql, cte_parameters = self._deck_summaries_with_prices_cte(start_date, end_date)
        row = self._fetch_one(
            f"""
            WITH {cte_sql}
            SELECT
                deck_site_id,
                deck_name,
                player_name,
                author_name,
                archetype_text,
                placement,
                placement_sort_value,
                participants_count,
                tournament_name,
                tournament_date,
                country,
                tier,
                tcg_price_usd,
                cardmarket_deck_price_eur,
                main_card_total,
                extra_card_total,
                side_card_total,
                deck_url
            FROM filtered_deck_summaries
            WHERE deck_site_id = ?
            """,
            cte_parameters + (deck_site_id,),
        )
        return dict(row) if row is not None else None

    def get_deck_summary_extended(
        self,
        deck_site_id: int,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> dict[str, Any] | None:
        summary = self.get_deck_summary(deck_site_id, start_date, end_date)
        if summary is None:
            return None

        participants_count = int(summary["participants_count"]) if summary.get("participants_count") is not None else 0
        placement_sort_value = (
            int(summary["placement_sort_value"]) if summary.get("placement_sort_value") is not None else None
        )
        if participants_count > 0 and placement_sort_value is not None and placement_sort_value > 0:
            placement_percentile = round(
                (participants_count - placement_sort_value + 1) * 100.0 / participants_count,
                1,
            )
        else:
            placement_percentile = None

        extended_summary = dict(summary)
        extended_summary["placement_percentile"] = placement_percentile
        return extended_summary

    def get_deck_role_metrics(
        self,
        deck_site_id: int,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> dict[str, Any] | None:
        summary = self.get_deck_summary_extended(deck_site_id, start_date, end_date)
        if summary is None:
            return None

        analyses = self._build_deck_analysis_totals(
            self._get_deck_analysis_card_rows(deck_site_id=deck_site_id, start_date=start_date, end_date=end_date)
        )
        analysis = analyses.get(deck_site_id)
        if analysis is None:
            return None

        metrics = self._calculate_deck_role_metrics_from_analysis(
            deck_site_id=deck_site_id,
            deck_name=str(summary["deck_name"]),
            analysis=analysis,
        )
        benchmarks = self.get_deck_group_role_benchmarks(str(summary["deck_name"]), start_date, end_date)
        if benchmarks is not None:
            metrics.update(
                {
                    "group_deck_count": int(benchmarks["deck_count"]),
                    "group_average_main_engine_share_pct": benchmarks["average_main_engine_share_pct"],
                    "group_average_main_non_engine_share_pct": benchmarks["average_main_non_engine_share_pct"],
                    "group_average_side_non_engine_share_pct": benchmarks["average_side_non_engine_share_pct"],
                    "group_average_side_handtrap_share_pct": benchmarks["average_side_handtrap_share_pct"],
                    "group_average_side_boardbreaker_share_pct": benchmarks["average_side_boardbreaker_share_pct"],
                    "group_average_side_non_engine_other_share_pct": benchmarks["average_side_non_engine_other_share_pct"],
                    "delta_vs_group_main_engine_share_pct": round(
                        float(metrics["main_engine_share_pct"]) - float(benchmarks["average_main_engine_share_pct"]),
                        2,
                    ),
                    "delta_vs_group_main_non_engine_share_pct": round(
                        float(metrics["main_non_engine_share_pct"])
                        - float(benchmarks["average_main_non_engine_share_pct"]),
                        2,
                    ),
                    "delta_vs_group_side_non_engine_share_pct": round(
                        float(metrics["side_non_engine_share_pct"])
                        - float(benchmarks["average_side_non_engine_share_pct"]),
                        2,
                    ),
                    "delta_vs_group_side_handtrap_share_pct": round(
                        float(metrics["side_handtrap_share_pct"])
                        - float(benchmarks["average_side_handtrap_share_pct"]),
                        2,
                    ),
                    "delta_vs_group_side_boardbreaker_share_pct": round(
                        float(metrics["side_boardbreaker_share_pct"])
                        - float(benchmarks["average_side_boardbreaker_share_pct"]),
                        2,
                    ),
                    "delta_vs_group_side_non_engine_other_share_pct": round(
                        float(metrics["side_non_engine_other_share_pct"])
                        - float(benchmarks["average_side_non_engine_other_share_pct"]),
                        2,
                    ),
                }
            )
        return metrics

    def get_deck_group_role_benchmarks(
        self,
        deck_name: str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> dict[str, Any] | None:
        analyses = self._build_deck_analysis_totals(
            self._get_deck_analysis_card_rows(deck_name=deck_name, start_date=start_date, end_date=end_date)
        )
        if not analyses:
            return None

        benchmark_fields = (
            "main_engine_share_pct",
            "main_non_engine_share_pct",
            "side_non_engine_share_pct",
            "side_handtrap_share_pct",
            "side_boardbreaker_share_pct",
            "side_non_engine_other_share_pct",
        )
        totals = {field: 0.0 for field in benchmark_fields}

        for deck_site_id, analysis in analyses.items():
            deck_metrics = self._calculate_deck_role_metrics_from_analysis(
                deck_site_id=deck_site_id,
                deck_name=str(analysis["deck_name"]),
                analysis=analysis,
            )
            for field in benchmark_fields:
                totals[field] += float(deck_metrics[field])

        deck_count = len(analyses)
        if deck_count <= 0:
            return None

        return {
            "deck_name": deck_name,
            "deck_count": deck_count,
            "average_main_engine_share_pct": round(totals["main_engine_share_pct"] / deck_count, 2),
            "average_main_non_engine_share_pct": round(totals["main_non_engine_share_pct"] / deck_count, 2),
            "average_side_non_engine_share_pct": round(totals["side_non_engine_share_pct"] / deck_count, 2),
            "average_side_handtrap_share_pct": round(totals["side_handtrap_share_pct"] / deck_count, 2),
            "average_side_boardbreaker_share_pct": round(totals["side_boardbreaker_share_pct"] / deck_count, 2),
            "average_side_non_engine_other_share_pct": round(
                totals["side_non_engine_other_share_pct"] / deck_count,
                2,
            ),
        }

    def get_deck_vs_group_section_comparison(
        self,
        deck_site_id: int,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        summary = self.get_deck_summary_extended(deck_site_id, start_date, end_date)
        if summary is None:
            return []

        deck_rows = self.get_deck_section_composition(deck_site_id, start_date, end_date)
        group_rows = self.get_deck_group_section_composition(str(summary["deck_name"]), start_date, end_date)
        comparison_rows: list[dict[str, Any]] = []

        for row in deck_rows:
            comparison_rows.append(
                {
                    "scope": "deck",
                    "scope_label": "Ausgewaehltes Deck",
                    "section": row["section"],
                    "component_name": row["component_name"],
                    "component_type": row["component_type"],
                    "copies_per_deck": float(row["copies_in_section"]),
                    "share_pct": float(row["share_pct"]),
                    "type_rank": int(row["type_rank"]),
                }
            )

        for row in group_rows:
            comparison_rows.append(
                {
                    "scope": "group",
                    "scope_label": "Deckgruppen-Mittel",
                    "section": row["section"],
                    "component_name": row["component_name"],
                    "component_type": row["component_type"],
                    "copies_per_deck": float(row["average_copies_per_group_deck"]),
                    "share_pct": float(row["share_pct"]),
                    "type_rank": int(row["type_rank"]),
                }
            )

        comparison_rows.sort(
            key=lambda row: (
                0 if row["section"] == "main" else 1,
                0 if row["scope"] == "deck" else 1,
                int(row["type_rank"]),
                -float(row["share_pct"]),
                str(row["component_name"]),
            )
        )
        return comparison_rows

    def get_deck_role_cost_distribution(
        self,
        deck_site_id: int,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        metrics = self.get_deck_role_metrics(deck_site_id, start_date, end_date)
        if metrics is None:
            return []

        total_cost = float(metrics["main_side_cardmarket_cost_eur"])
        if total_cost <= 0:
            return []

        rows = [
            {
                "component_name": "Engine",
                "component_type": "main_engine",
                "cardmarket_cost_eur": round(float(metrics["engine_cardmarket_cost_eur"]), 2),
                "share_pct": round(float(metrics["engine_cardmarket_cost_eur"]) * 100.0 / total_cost, 2),
                "type_rank": 1,
            },
            {
                "component_name": "Handtraps",
                "component_type": "non_engine_handtrap",
                "cardmarket_cost_eur": round(float(metrics["handtrap_cardmarket_cost_eur"]), 2),
                "share_pct": round(float(metrics["handtrap_cardmarket_cost_eur"]) * 100.0 / total_cost, 2),
                "type_rank": 2,
            },
            {
                "component_name": "Boardbreaker",
                "component_type": "non_engine_boardbreaker",
                "cardmarket_cost_eur": round(float(metrics["boardbreaker_cardmarket_cost_eur"]), 2),
                "share_pct": round(float(metrics["boardbreaker_cardmarket_cost_eur"]) * 100.0 / total_cost, 2),
                "type_rank": 3,
            },
            {
                "component_name": "Weitere Non-Engine",
                "component_type": "non_engine_other",
                "cardmarket_cost_eur": round(float(metrics["non_engine_other_cardmarket_cost_eur"]), 2),
                "share_pct": round(float(metrics["non_engine_other_cardmarket_cost_eur"]) * 100.0 / total_cost, 2),
                "type_rank": 4,
            },
        ]
        rows.sort(key=lambda row: (int(row["type_rank"]), -float(row["share_pct"]), str(row["component_name"])))
        return rows

    def get_deck_copy_count_histogram(
        self,
        deck_site_id: int,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        metrics = self.get_deck_role_metrics(deck_site_id, start_date, end_date)
        if metrics is None:
            return []

        histogram_rows = [
            {"copy_count": 1, "label": "1x", "card_count": int(metrics["main_one_of_count"])},
            {"copy_count": 2, "label": "2x", "card_count": int(metrics["main_two_of_count"])},
            {"copy_count": 3, "label": "3x", "card_count": int(metrics["main_three_of_count"])},
        ]
        total_distinct_main_cards = sum(row["card_count"] for row in histogram_rows)
        for row in histogram_rows:
            row["share_pct"] = round(row["card_count"] * 100.0 / total_distinct_main_cards, 2) if total_distinct_main_cards > 0 else 0.0
        return histogram_rows

    def list_deck_name_aggregates(
        self,
        limit: int = 250,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._fetch_deck_name_aggregate_base_rows(limit=limit, start_date=start_date, end_date=end_date)
        return self._attach_deck_name_aggregate_enrichments(
            rows,
            start_date=start_date,
            end_date=end_date,
        )

    def list_deck_name_aggregates_extended(
        self,
        limit: int = 250,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        return self.list_deck_name_aggregates(limit=limit, start_date=start_date, end_date=end_date)

    def get_deck_name_aggregate(
        self,
        deck_name: str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> dict[str, Any] | None:
        rows = self._fetch_deck_name_aggregate_base_rows(
            deck_name=deck_name,
            start_date=start_date,
            end_date=end_date,
        )
        if not rows:
            return None
        return self._attach_deck_name_aggregate_enrichments(
            rows,
            start_date=start_date,
            end_date=end_date,
        )[0]

    def get_deck_name_aggregate_extended(
        self,
        deck_name: str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> dict[str, Any] | None:
        return self.get_deck_name_aggregate(deck_name, start_date=start_date, end_date=end_date)

    def get_deck_name_scatter_rows(
        self,
        limit: int = 250,
        min_deck_count: int = 1,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        aggregate_rows = self._attach_deck_name_aggregate_enrichments(
            self._fetch_deck_name_aggregate_base_rows(start_date=start_date, end_date=end_date),
            start_date=start_date,
            end_date=end_date,
        )
        scatter_rows: list[dict[str, Any]] = []
        for row in aggregate_rows:
            deck_count = int(row.get("deck_count") or 0)
            if deck_count < min_deck_count:
                continue
            average_placement_percentile = row.get("average_placement_percentile")
            median_placement_percentile = row.get("median_placement_percentile")
            if average_placement_percentile is None and median_placement_percentile is None:
                continue
            scatter_rows.append(
                {
                    "deck_name": row["deck_name"],
                    "deck_count": deck_count,
                    "tournament_count": int(row.get("tournament_count") or 0),
                    "player_count": int(row.get("player_count") or 0),
                    "meta_share_pct": float(row.get("meta_share_pct") or 0.0),
                    "tournament_coverage_pct": float(row.get("tournament_coverage_pct") or 0.0),
                    "player_diversity_ratio": float(row.get("player_diversity_ratio") or 0.0),
                    "average_placement_percentile": float(average_placement_percentile)
                    if average_placement_percentile is not None
                    else None,
                    "median_placement_percentile": float(median_placement_percentile)
                    if median_placement_percentile is not None
                    else None,
                    "top_25_finish_rate_pct": float(row.get("top_25_finish_rate_pct"))
                    if row.get("top_25_finish_rate_pct") is not None
                    else None,
                    "average_cardmarket_deck_price_eur": float(row.get("average_cardmarket_deck_price_eur"))
                    if row.get("average_cardmarket_deck_price_eur") is not None
                    else None,
                    "median_cardmarket_deck_price_eur": float(row.get("median_cardmarket_deck_price_eur"))
                    if row.get("median_cardmarket_deck_price_eur") is not None
                    else None,
                    "recent_30d_result_share_pct": float(row.get("recent_30d_result_share_pct"))
                    if row.get("recent_30d_result_share_pct") is not None
                    else None,
                }
            )
        scatter_rows.sort(
            key=lambda row: (
                -float(row["meta_share_pct"]),
                -(float(row["average_placement_percentile"]) if row["average_placement_percentile"] is not None else 0.0),
                str(row["deck_name"]),
            )
        )
        return scatter_rows[:limit]

    def get_deck_name_cost_performance_rows(
        self,
        limit: int = 250,
        min_deck_count: int = 1,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.get_deck_name_scatter_rows(
            limit=max(limit, 1_000),
            min_deck_count=min_deck_count,
            start_date=start_date,
            end_date=end_date,
        )
        cost_rows = [
            {
                **row,
                "median_cardmarket_deck_price_eur": row["median_cardmarket_deck_price_eur"],
                "cardmarket_deck_price_p25_eur": row.get("cardmarket_deck_price_p25_eur"),
                "cardmarket_deck_price_p75_eur": row.get("cardmarket_deck_price_p75_eur"),
            }
            for row in self._attach_cost_distribution_fields(rows, start_date=start_date, end_date=end_date)
            if row.get("median_cardmarket_deck_price_eur") is not None
        ]
        cost_rows.sort(
            key=lambda row: (
                float(row["median_cardmarket_deck_price_eur"]),
                -(float(row["average_placement_percentile"]) if row["average_placement_percentile"] is not None else 0.0),
                str(row["deck_name"]),
            )
        )
        return cost_rows[:limit]

    def get_deck_name_profile_rows(
        self,
        deck_names: list[str] | None = None,
        limit: int = 8,
        sort_field: str = "meta_share_pct",
        min_deck_count: int = 1,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        aggregate_rows = self._attach_deck_name_aggregate_enrichments(
            self._fetch_deck_name_aggregate_base_rows(start_date=start_date, end_date=end_date),
            start_date=start_date,
            end_date=end_date,
        )
        aggregate_by_name = {str(row["deck_name"]): row for row in aggregate_rows}

        if deck_names is None or not deck_names:
            sortable_fields = {
                "meta_share_pct",
                "deck_count",
                "average_placement_percentile",
                "median_cardmarket_deck_price_eur",
            }
            effective_sort_field = sort_field if sort_field in sortable_fields else "meta_share_pct"
            candidate_rows = [row for row in aggregate_rows if int(row.get("deck_count") or 0) >= min_deck_count]
            candidate_rows.sort(
                key=lambda row: (
                    -float(row.get(effective_sort_field) or 0.0),
                    -int(row.get("deck_count") or 0),
                    str(row["deck_name"]),
                )
            )
            selected_deck_names = [str(row["deck_name"]) for row in candidate_rows[:limit]]
        else:
            selected_deck_names = [deck_name for deck_name in deck_names if deck_name in aggregate_by_name]

        profile_rows: list[dict[str, Any]] = []
        for deck_rank, deck_name in enumerate(selected_deck_names, start=1):
            aggregate_row = aggregate_by_name.get(deck_name)
            if aggregate_row is None:
                continue
            for row in self.get_deck_group_section_composition(deck_name, start_date, end_date):
                profile_rows.append(
                    {
                        "deck_name": deck_name,
                        "deck_rank": deck_rank,
                        "section": row["section"],
                        "component_name": row["component_name"],
                        "component_type": row["component_type"],
                        "average_copies_per_group_deck": float(row["average_copies_per_group_deck"]),
                        "share_pct": float(row["share_pct"]),
                        "type_rank": int(row["type_rank"]),
                        "deck_count": int(aggregate_row.get("deck_count") or 0),
                        "meta_share_pct": float(aggregate_row.get("meta_share_pct") or 0.0),
                        "average_placement_percentile": float(aggregate_row.get("average_placement_percentile"))
                        if aggregate_row.get("average_placement_percentile") is not None
                        else None,
                        "median_cardmarket_deck_price_eur": float(aggregate_row.get("median_cardmarket_deck_price_eur"))
                        if aggregate_row.get("median_cardmarket_deck_price_eur") is not None
                        else None,
                    }
                )
        return profile_rows

    def get_deck_name_trend_rows(
        self,
        deck_names: list[str] | None = None,
        limit: int = 8,
        sort_field: str = "meta_share_pct",
        min_deck_count: int = 1,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        aggregate_rows = self._attach_deck_name_aggregate_enrichments(
            self._fetch_deck_name_aggregate_base_rows(start_date=start_date, end_date=end_date),
            start_date=start_date,
            end_date=end_date,
        )
        aggregate_by_name = {str(row["deck_name"]): row for row in aggregate_rows}

        if deck_names is None or not deck_names:
            sortable_fields = {
                "meta_share_pct",
                "deck_count",
                "average_placement_percentile",
                "median_cardmarket_deck_price_eur",
            }
            effective_sort_field = sort_field if sort_field in sortable_fields else "meta_share_pct"
            candidate_rows = [row for row in aggregate_rows if int(row.get("deck_count") or 0) >= min_deck_count]
            candidate_rows.sort(
                key=lambda row: (
                    -float(row.get(effective_sort_field) or 0.0),
                    -int(row.get("deck_count") or 0),
                    str(row["deck_name"]),
                )
            )
            selected_deck_names = [str(row["deck_name"]) for row in candidate_rows[:limit]]
        else:
            selected_deck_names = [deck_name for deck_name in deck_names if deck_name in aggregate_by_name]

        if not selected_deck_names:
            return []

        placeholders = ", ".join("?" for _ in selected_deck_names)
        cte_sql, cte_parameters = self._deck_summaries_with_prices_cte(start_date, end_date)

        monthly_total_rows = self._fetch_all(
            f"""
            WITH {cte_sql}
            SELECT
                strftime('%Y-%m-01', tournament_date) AS month_start,
                COUNT(*) AS total_deck_count
            FROM filtered_deck_summaries
            GROUP BY strftime('%Y-%m-01', tournament_date)
            ORDER BY month_start ASC
            """,
            cte_parameters,
        )
        month_totals = {
            str(row["month_start"]): int(row["total_deck_count"] or 0)
            for row in monthly_total_rows
            if row["month_start"] is not None
        }

        raw_rows = self._fetch_all(
            f"""
            WITH {cte_sql}
            SELECT
                deck_name,
                strftime('%Y-%m-01', tournament_date) AS month_start,
                participants_count,
                placement_sort_value,
                cardmarket_deck_price_eur
            FROM filtered_deck_summaries
            WHERE deck_name IN ({placeholders})
            ORDER BY deck_name ASC, month_start ASC, placement_sort_value ASC
            """,
            cte_parameters + tuple(selected_deck_names),
        )

        trend_stats: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: {
                "deck_count": 0,
                "placement_percentiles": [],
                "known_prices": [],
            }
        )

        for row in raw_rows:
            if row["month_start"] is None:
                continue
            deck_name = str(row["deck_name"])
            month_start = str(row["month_start"])
            stats = trend_stats[(deck_name, month_start)]
            stats["deck_count"] += 1

            placement_percentile = self._placement_percentile_value(
                participants_count=row["participants_count"],
                placement_sort_value=row["placement_sort_value"],
            )
            if placement_percentile is not None:
                stats["placement_percentiles"].append(float(placement_percentile))

            if row["cardmarket_deck_price_eur"] is not None:
                cardmarket_deck_price_eur = float(row["cardmarket_deck_price_eur"])
                if cardmarket_deck_price_eur > 0:
                    stats["known_prices"].append(cardmarket_deck_price_eur)

        deck_rank_by_name = {deck_name: index for index, deck_name in enumerate(selected_deck_names, start=1)}
        trend_rows: list[dict[str, Any]] = []
        for (deck_name, month_start), stats in sorted(
            trend_stats.items(),
            key=lambda item: (deck_rank_by_name.get(item[0][0], 9_999), item[0][1]),
        ):
            placement_percentiles = sorted(float(value) for value in stats["placement_percentiles"])
            known_prices = sorted(float(value) for value in stats["known_prices"])
            placement_p25 = self._interpolated_quantile(placement_percentiles, 0.25)
            placement_p50 = self._interpolated_quantile(placement_percentiles, 0.50)
            placement_p75 = self._interpolated_quantile(placement_percentiles, 0.75)
            price_p50 = self._interpolated_quantile(known_prices, 0.50)
            price_p75 = self._interpolated_quantile(known_prices, 0.75)
            price_p25 = self._interpolated_quantile(known_prices, 0.25)
            month_total_deck_count = int(month_totals.get(month_start) or 0)
            deck_count = int(stats["deck_count"])

            trend_rows.append(
                {
                    "deck_name": deck_name,
                    "deck_rank": int(deck_rank_by_name.get(deck_name, 0)),
                    "month_start": month_start,
                    "deck_count": deck_count,
                    "month_total_deck_count": month_total_deck_count,
                    "meta_share_pct": round(deck_count * 100.0 / month_total_deck_count, 2)
                    if month_total_deck_count > 0
                    else None,
                    "average_placement_percentile": round(sum(placement_percentiles) / len(placement_percentiles), 2)
                    if placement_percentiles
                    else None,
                    "median_placement_percentile": placement_p50,
                    "placement_percentile_iqr": round(placement_p75 - placement_p25, 2)
                    if placement_p25 is not None and placement_p75 is not None
                    else None,
                    "top_25_finish_rate_pct": round(
                        sum(1 for value in placement_percentiles if value >= 75.0) * 100.0 / len(placement_percentiles),
                        2,
                    )
                    if placement_percentiles
                    else None,
                    "median_cardmarket_deck_price_eur": price_p50,
                    "cardmarket_deck_price_iqr_eur": round(price_p75 - price_p25, 2)
                    if price_p25 is not None and price_p75 is not None
                    else None,
                }
            )
        return trend_rows

    def _fetch_deck_name_aggregate_base_rows(
        self,
        *,
        deck_name: str | None = None,
        limit: int | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        cte_sql, cte_parameters = self._deck_summaries_with_prices_cte(start_date, end_date)
        where_sql = "WHERE deck_name = ?" if deck_name is not None else ""
        limit_sql = "LIMIT ?" if limit is not None else ""
        parameters: tuple[Any, ...] = cte_parameters
        if deck_name is not None:
            parameters += (deck_name,)
        if limit is not None:
            parameters += (limit,)

        rows = self._fetch_all(
            f"""
            WITH {cte_sql}
            SELECT
                deck_name,
                COUNT(*) AS deck_count,
                COUNT(DISTINCT tournament_site_id) AS tournament_count,
                COUNT(DISTINCT player_name) AS player_count,
                ROUND(AVG(placement_sort_value), 2) AS average_placement,
                MIN(placement_sort_value) AS best_placement,
                MAX(placement_sort_value) AS worst_placement,
                ROUND(AVG(participants_count), 1) AS average_participants_count,
                ROUND(AVG(main_card_total), 2) AS average_main_card_total,
                ROUND(AVG(extra_card_total), 2) AS average_extra_card_total,
                ROUND(AVG(side_card_total), 2) AS average_side_card_total,
                ROUND(AVG(tcg_price_usd), 2) AS average_tcg_price_usd,
                ROUND(AVG(cardmarket_deck_price_eur), 2) AS average_cardmarket_deck_price_eur,
                MIN(tournament_date) AS first_seen_date,
                MAX(tournament_date) AS last_seen_date
            FROM filtered_deck_summaries
            {where_sql}
            GROUP BY deck_name
            ORDER BY deck_count DESC, average_placement ASC, deck_name ASC
            {limit_sql}
            """,
            parameters,
        )
        return [dict(row) for row in rows]

    def _attach_cost_distribution_fields(
        self,
        rows: list[dict[str, Any]],
        *,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        if not rows:
            return rows

        deck_names = [str(row["deck_name"]) for row in rows if row.get("deck_name") is not None]
        distribution_metrics = self._get_deck_name_distribution_metrics(
            deck_names,
            start_date=start_date,
            end_date=end_date,
            latest_tournament_date=self._get_filtered_deck_summary_totals(
                start_date=start_date,
                end_date=end_date,
            )["latest_tournament_date"],
        )
        annotated_rows: list[dict[str, Any]] = []
        for row in rows:
            annotated = dict(row)
            annotated.update(distribution_metrics.get(str(row["deck_name"]), {}))
            annotated_rows.append(annotated)
        return annotated_rows

    def get_deck_group_section_composition(
        self,
        deck_name: str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._fetch_all(
            f"""
            {self._non_engine_classification_cte(start_date, end_date)}
            , matching_decks AS (
                SELECT deck_site_id
                FROM filtered_decks
                WHERE deck_name = ?
            ),
            per_deck_section_cards AS (
                SELECT
                    md.deck_site_id,
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT)) AS card_name,
                    MAX(c.card_archetype) AS card_archetype,
                    MAX(c.card_type) AS card_type,
                    MAX(c.card_race) AS card_race,
                    MAX(c.frame_type) AS frame_type,
                    MAX(CASE WHEN c.effect_text IS NOT NULL AND LOWER(TRIM(c.effect_text)) NOT IN ('none', 'null', 'n/a', 'na') THEN c.effect_text END) AS effect_text,
                    MAX(COALESCE(cc.classification, 'engine')) AS classification,
                    SUM(dc.quantity) AS copies_in_deck
                FROM deck_cards dc
                JOIN matching_decks md ON md.deck_site_id = dc.deck_site_id
                LEFT JOIN cards c ON c.card_passcode = dc.card_passcode
                LEFT JOIN classified_cards cc
                  ON cc.section = dc.section
                 AND cc.card_name = COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
                WHERE dc.section IN ('main', 'side')
                GROUP BY
                    md.deck_site_id,
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
            ),
            section_totals AS (
                SELECT
                    section,
                    COUNT(DISTINCT deck_site_id) AS deck_count,
                    COALESCE(SUM(copies_in_deck), 0) AS total_section_copies
                FROM per_deck_section_cards
                GROUP BY section
            )
            SELECT
                pdsc.section,
                pdsc.card_name,
                pdsc.card_archetype,
                pdsc.card_type,
                pdsc.card_race,
                pdsc.frame_type,
                pdsc.effect_text,
                pdsc.classification,
                SUM(pdsc.copies_in_deck) AS total_copies,
                st.deck_count,
                st.total_section_copies
            FROM per_deck_section_cards pdsc
            JOIN section_totals st ON st.section = pdsc.section
            WHERE st.deck_count > 0
              AND st.total_section_copies > 0
            GROUP BY
                pdsc.section,
                pdsc.card_name,
                pdsc.card_archetype,
                pdsc.card_type,
                pdsc.card_race,
                pdsc.frame_type,
                pdsc.effect_text,
                pdsc.classification,
                st.deck_count,
                st.total_section_copies
            ORDER BY
                CASE pdsc.section
                    WHEN 'main' THEN 1
                    WHEN 'side' THEN 2
                    ELSE 3
                END,
                total_copies DESC,
                pdsc.card_name ASC
            """,
            self._non_engine_classification_parameters(start_date, end_date) + (deck_name,),
        )

        normalized_deck_name = deck_name.strip().lower()
        component_totals: dict[tuple[str, str, str], float] = {}
        section_deck_counts: dict[str, int] = {}
        section_total_copies: dict[str, float] = {}

        for row in rows:
            section = str(row["section"])
            section_deck_counts[section] = int(row["deck_count"])
            section_total_copies[section] = float(row["total_section_copies"])

            component_name, component_type = self._resolve_deck_group_component(
                normalized_deck_name=normalized_deck_name,
                card_name=str(row["card_name"]),
                card_archetype=row["card_archetype"],
                classification=str(row["classification"]),
                card_type=row["card_type"],
                frame_type=row["frame_type"],
                race=row["card_race"],
                effect_text=row["effect_text"],
            )
            key = (section, component_name, component_type)
            component_totals[key] = component_totals.get(key, 0.0) + float(row["total_copies"])

        composition_rows: list[dict[str, Any]] = []
        for (section, component_name, component_type), total_copies in component_totals.items():
            deck_count = section_deck_counts.get(section, 0)
            total_section_copies = section_total_copies.get(section, 0.0)
            if deck_count <= 0 or total_section_copies <= 0:
                continue
            composition_rows.append(
                {
                    "section": section,
                    "component_name": component_name,
                    "component_type": component_type,
                    "average_copies_per_group_deck": round(total_copies / deck_count, 2),
                    "share_pct": round(total_copies * 100.0 / total_section_copies, 1),
                    "type_rank": self._deck_group_component_rank(component_type),
                }
            )

        composition_rows.sort(
            key=lambda row: (
                0 if row["section"] == "main" else 1,
                int(row["type_rank"]),
                -float(row["share_pct"]),
                str(row["component_name"]),
            )
        )
        return composition_rows

    def get_deck_group_main_deck_composition(
        self,
        deck_name: str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            row
            for row in self.get_deck_group_section_composition(deck_name, start_date, end_date)
            if row["section"] == "main"
        ]

    def get_deck_section_composition(
        self,
        deck_site_id: int,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._fetch_all(
            f"""
            {self._non_engine_classification_cte(start_date, end_date)}
            , selected_deck AS (
                SELECT deck_site_id, deck_name
                FROM filtered_decks
                WHERE deck_site_id = ?
            ),
            per_deck_section_cards AS (
                SELECT
                    sd.deck_name,
                    sd.deck_site_id,
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT)) AS card_name,
                    MAX(c.card_archetype) AS card_archetype,
                    MAX(c.card_type) AS card_type,
                    MAX(c.card_race) AS card_race,
                    MAX(c.frame_type) AS frame_type,
                    MAX(CASE WHEN c.effect_text IS NOT NULL AND LOWER(TRIM(c.effect_text)) NOT IN ('none', 'null', 'n/a', 'na') THEN c.effect_text END) AS effect_text,
                    MAX(COALESCE(cc.classification, 'engine')) AS classification,
                    SUM(dc.quantity) AS copies_in_deck
                FROM deck_cards dc
                JOIN selected_deck sd ON sd.deck_site_id = dc.deck_site_id
                LEFT JOIN cards c ON c.card_passcode = dc.card_passcode
                LEFT JOIN classified_cards cc
                  ON cc.section = dc.section
                 AND cc.card_name = COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
                WHERE dc.section IN ('main', 'side')
                GROUP BY
                    sd.deck_name,
                    sd.deck_site_id,
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
            ),
            section_totals AS (
                SELECT
                    section,
                    COALESCE(SUM(copies_in_deck), 0) AS total_section_copies
                FROM per_deck_section_cards
                GROUP BY section
            )
            SELECT
                pdsc.deck_name,
                pdsc.section,
                pdsc.card_name,
                pdsc.card_archetype,
                pdsc.card_type,
                pdsc.card_race,
                pdsc.frame_type,
                pdsc.effect_text,
                pdsc.classification,
                pdsc.copies_in_deck AS total_copies,
                st.total_section_copies
            FROM per_deck_section_cards pdsc
            JOIN section_totals st ON st.section = pdsc.section
            WHERE st.total_section_copies > 0
            ORDER BY
                CASE pdsc.section
                    WHEN 'main' THEN 1
                    WHEN 'side' THEN 2
                    ELSE 3
                END,
                total_copies DESC,
                pdsc.card_name ASC
            """,
            self._non_engine_classification_parameters(start_date, end_date) + (deck_site_id,),
        )
        if not rows:
            return []

        normalized_deck_name = str(rows[0]["deck_name"]).strip().lower()
        component_totals: dict[tuple[str, str, str], float] = {}
        section_total_copies: dict[str, float] = {}

        for row in rows:
            section = str(row["section"])
            section_total_copies[section] = float(row["total_section_copies"])

            component_name, component_type = self._resolve_deck_group_component(
                normalized_deck_name=normalized_deck_name,
                card_name=str(row["card_name"]),
                card_archetype=row["card_archetype"],
                classification=str(row["classification"]),
                card_type=row["card_type"],
                frame_type=row["frame_type"],
                race=row["card_race"],
                effect_text=row["effect_text"],
            )
            key = (section, component_name, component_type)
            component_totals[key] = component_totals.get(key, 0.0) + float(row["total_copies"])

        composition_rows: list[dict[str, Any]] = []
        for (section, component_name, component_type), total_copies in component_totals.items():
            total_section_copies = section_total_copies.get(section, 0.0)
            if total_section_copies <= 0:
                continue
            composition_rows.append(
                {
                    "section": section,
                    "component_name": component_name,
                    "component_type": component_type,
                    "copies_in_section": round(total_copies, 2),
                    "share_pct": round(total_copies * 100.0 / total_section_copies, 1),
                    "type_rank": self._deck_group_component_rank(component_type),
                }
            )

        composition_rows.sort(
            key=lambda row: (
                0 if row["section"] == "main" else 1,
                int(row["type_rank"]),
                -float(row["share_pct"]),
                str(row["component_name"]),
            )
        )
        return composition_rows

    def get_monthly_main_deck_share_trends(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        per_deck_totals = self._get_monthly_deck_section_role_totals(start_date, end_date)
        monthly_totals: dict[str, dict[str, float]] = defaultdict(
            lambda: {
                "deck_count": 0.0,
                "engine_share_sum": 0.0,
                "handtrap_share_sum": 0.0,
                "boardbreaker_share_sum": 0.0,
            }
        )

        for deck_totals in per_deck_totals.values():
            main_totals = deck_totals["sections"]["main"]
            main_total = float(main_totals["total"])
            if main_total <= 0:
                continue
            month_start = str(deck_totals["month_start"])
            monthly_totals[month_start]["deck_count"] += 1.0
            monthly_totals[month_start]["engine_share_sum"] += float(main_totals["engine"]) * 100.0 / main_total
            monthly_totals[month_start]["handtrap_share_sum"] += float(main_totals["handtrap"]) * 100.0 / main_total
            monthly_totals[month_start]["boardbreaker_share_sum"] += float(main_totals["boardbreaker"]) * 100.0 / main_total

        trend_rows: list[dict[str, Any]] = []
        for month_start in sorted(monthly_totals.keys()):
            deck_count = int(monthly_totals[month_start]["deck_count"])
            if deck_count <= 0:
                continue
            trend_rows.append(
                {
                    "month_start": month_start,
                    "deck_count": deck_count,
                    "average_engine_share_pct": round(monthly_totals[month_start]["engine_share_sum"] / deck_count, 2),
                    "average_handtrap_share_pct": round(monthly_totals[month_start]["handtrap_share_sum"] / deck_count, 2),
                    "average_boardbreaker_share_pct": round(monthly_totals[month_start]["boardbreaker_share_sum"] / deck_count, 2),
                }
            )
        return trend_rows

    def get_monthly_side_deck_share_trends(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        per_deck_totals = self._get_monthly_deck_section_role_totals(start_date, end_date)
        monthly_totals: dict[str, dict[str, float]] = defaultdict(
            lambda: {
                "deck_count": 0.0,
                "handtrap_share_sum": 0.0,
                "boardbreaker_share_sum": 0.0,
                "non_engine_other_share_sum": 0.0,
            }
        )

        for deck_totals in per_deck_totals.values():
            side_totals = deck_totals["sections"]["side"]
            side_total = float(side_totals["total"])
            if side_total <= 0:
                continue
            month_start = str(deck_totals["month_start"])
            monthly_totals[month_start]["deck_count"] += 1.0
            monthly_totals[month_start]["handtrap_share_sum"] += float(side_totals["handtrap"]) * 100.0 / side_total
            monthly_totals[month_start]["boardbreaker_share_sum"] += float(side_totals["boardbreaker"]) * 100.0 / side_total
            monthly_totals[month_start]["non_engine_other_share_sum"] += float(side_totals["non_engine_other"]) * 100.0 / side_total

        trend_rows: list[dict[str, Any]] = []
        for month_start in sorted(monthly_totals.keys()):
            deck_count = int(monthly_totals[month_start]["deck_count"])
            if deck_count <= 0:
                continue
            trend_rows.append(
                {
                    "month_start": month_start,
                    "deck_count": deck_count,
                    "average_handtrap_share_pct": round(monthly_totals[month_start]["handtrap_share_sum"] / deck_count, 2),
                    "average_boardbreaker_share_pct": round(monthly_totals[month_start]["boardbreaker_share_sum"] / deck_count, 2),
                    "average_non_engine_other_share_pct": round(monthly_totals[month_start]["non_engine_other_share_sum"] / deck_count, 2),
                }
            )
        return trend_rows

    def get_monthly_non_engine_subrole_trends(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        per_deck_totals = self._get_monthly_deck_section_role_totals(start_date, end_date)
        monthly_totals: dict[str, dict[str, float]] = defaultdict(
            lambda: {
                "deck_count": 0.0,
                "floodgate_share_sum": 0.0,
                "protection_share_sum": 0.0,
                "draw_engine_share_sum": 0.0,
                "unknown_share_sum": 0.0,
            }
        )

        for deck_totals in per_deck_totals.values():
            combined_other_total = float(deck_totals["sections"]["main"]["non_engine_other"]) + float(
                deck_totals["sections"]["side"]["non_engine_other"]
            )
            if combined_other_total <= 0:
                continue
            floodgate_total = float(deck_totals["sections"]["main"]["floodgate"]) + float(
                deck_totals["sections"]["side"]["floodgate"]
            )
            protection_total = float(deck_totals["sections"]["main"]["protection"]) + float(
                deck_totals["sections"]["side"]["protection"]
            )
            draw_engine_total = float(deck_totals["sections"]["main"]["draw_engine"]) + float(
                deck_totals["sections"]["side"]["draw_engine"]
            )
            unknown_total = float(deck_totals["sections"]["main"]["unknown_non_engine"]) + float(
                deck_totals["sections"]["side"]["unknown_non_engine"]
            )

            month_start = str(deck_totals["month_start"])
            monthly_totals[month_start]["deck_count"] += 1.0
            monthly_totals[month_start]["floodgate_share_sum"] += floodgate_total * 100.0 / combined_other_total
            monthly_totals[month_start]["protection_share_sum"] += protection_total * 100.0 / combined_other_total
            monthly_totals[month_start]["draw_engine_share_sum"] += draw_engine_total * 100.0 / combined_other_total
            monthly_totals[month_start]["unknown_share_sum"] += unknown_total * 100.0 / combined_other_total

        trend_rows: list[dict[str, Any]] = []
        for month_start in sorted(monthly_totals.keys()):
            deck_count = int(monthly_totals[month_start]["deck_count"])
            if deck_count <= 0:
                continue
            trend_rows.append(
                {
                    "month_start": month_start,
                    "deck_count": deck_count,
                    "average_floodgate_share_pct": round(monthly_totals[month_start]["floodgate_share_sum"] / deck_count, 2),
                    "average_protection_share_pct": round(monthly_totals[month_start]["protection_share_sum"] / deck_count, 2),
                    "average_draw_engine_share_pct": round(monthly_totals[month_start]["draw_engine_share_sum"] / deck_count, 2),
                    "average_unknown_share_pct": round(monthly_totals[month_start]["unknown_share_sum"] / deck_count, 2),
                }
            )
        return trend_rows

    def get_monthly_section_engine_vs_non_engine_trends(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        per_deck_totals = self._get_monthly_deck_section_role_totals(start_date, end_date)
        monthly_totals: dict[tuple[str, str], dict[str, float]] = defaultdict(
            lambda: {
                "deck_count": 0.0,
                "engine_share_sum": 0.0,
                "non_engine_share_sum": 0.0,
            }
        )

        for deck_totals in per_deck_totals.values():
            month_start = str(deck_totals["month_start"])
            for section in ("main", "side"):
                section_totals = deck_totals["sections"][section]
                section_total = float(section_totals["total"])
                if section_total <= 0:
                    continue
                key = (month_start, section)
                monthly_totals[key]["deck_count"] += 1.0
                monthly_totals[key]["engine_share_sum"] += float(section_totals["engine"]) * 100.0 / section_total
                monthly_totals[key]["non_engine_share_sum"] += float(section_totals["non_engine_total"]) * 100.0 / section_total

        trend_rows: list[dict[str, Any]] = []
        for month_start, section in sorted(monthly_totals.keys()):
            deck_count = int(monthly_totals[(month_start, section)]["deck_count"])
            if deck_count <= 0:
                continue
            trend_rows.append(
                {
                    "month_start": month_start,
                    "section": section,
                    "deck_count": deck_count,
                    "average_engine_share_pct": round(
                        monthly_totals[(month_start, section)]["engine_share_sum"] / deck_count,
                        2,
                    ),
                    "average_non_engine_share_pct": round(
                        monthly_totals[(month_start, section)]["non_engine_share_sum"] / deck_count,
                        2,
                    ),
                }
            )
        return trend_rows

    def get_monthly_new_deck_name_share_trends(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._get_monthly_deck_name_result_rows(start_date, end_date)
        if not rows:
            return []

        monthly_results: dict[str, dict[str, int]] = defaultdict(dict)
        for row in rows:
            monthly_results[str(row["month_start"])][str(row["deck_name"])] = int(row["result_count"])

        trend_rows: list[dict[str, Any]] = []
        previous_deck_names: set[str] | None = None
        for month_start in sorted(monthly_results.keys()):
            result_counts = monthly_results[month_start]
            total_results = sum(result_counts.values())
            if total_results <= 0:
                continue

            if previous_deck_names is None:
                new_deck_name_count: int | None = None
                new_result_count: int | None = None
                new_result_share_pct: float | None = None
            else:
                new_deck_names = {deck_name for deck_name in result_counts if deck_name not in previous_deck_names}
                new_deck_name_count = len(new_deck_names)
                new_result_count = sum(result_counts[deck_name] for deck_name in new_deck_names)
                new_result_share_pct = round(new_result_count * 100.0 / total_results, 2)

            trend_rows.append(
                {
                    "month_start": month_start,
                    "result_count": total_results,
                    "distinct_deck_names": len(result_counts),
                    "new_deck_name_count": new_deck_name_count,
                    "new_result_count": new_result_count,
                    "new_result_share_pct": new_result_share_pct,
                }
            )
            previous_deck_names = set(result_counts.keys())

        return trend_rows

    def get_monthly_deck_result_concentration_trends(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._get_monthly_deck_name_result_rows(start_date, end_date)
        if not rows:
            return []

        monthly_counts: dict[str, list[int]] = defaultdict(list)
        monthly_distinct_deck_names: dict[str, set[str]] = defaultdict(set)

        for row in rows:
            month_start = row["month_start"]
            if month_start is None:
                continue
            month_key = str(month_start)
            monthly_counts[month_key].append(int(row["result_count"]))
            monthly_distinct_deck_names[month_key].add(str(row["deck_name"]))

        threshold_definitions = [
            (0.25, "deck_names_for_25_pct"),
            (0.50, "deck_names_for_50_pct"),
            (0.75, "deck_names_for_75_pct"),
            (0.90, "deck_names_for_90_pct"),
        ]

        trend_rows: list[dict[str, Any]] = []
        for month_start in sorted(monthly_counts.keys()):
            counts = monthly_counts[month_start]
            total_results = sum(counts)
            if total_results <= 0:
                continue

            trend_row: dict[str, Any] = {
                "month_start": month_start,
                "result_count": total_results,
                "distinct_deck_names": len(monthly_distinct_deck_names[month_start]),
            }

            cumulative_results = 0
            deck_name_count = 0
            threshold_index = 0
            for result_count in counts:
                cumulative_results += int(result_count)
                deck_name_count += 1
                while threshold_index < len(threshold_definitions):
                    threshold_share, threshold_key = threshold_definitions[threshold_index]
                    if cumulative_results / total_results >= threshold_share:
                        trend_row[threshold_key] = deck_name_count
                        threshold_index += 1
                    else:
                        break

            while threshold_index < len(threshold_definitions):
                _, threshold_key = threshold_definitions[threshold_index]
                trend_row[threshold_key] = deck_name_count
                threshold_index += 1

            trend_rows.append(trend_row)

        return trend_rows

    def get_monthly_top_deck_cost_trends(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        cte_sql, cte_parameters = self._deck_summaries_with_prices_cte(start_date, end_date)
        rows = self._fetch_all(
            f"""
            WITH {cte_sql}
            SELECT
                strftime('%Y-%m-01', tournament_date) AS month_start,
                deck_name,
                COUNT(*) AS result_count,
                ROUND(AVG(cardmarket_deck_price_eur), 2) AS average_cardmarket_deck_price_eur
            FROM filtered_deck_summaries
            WHERE tournament_date IS NOT NULL
            GROUP BY strftime('%Y-%m-01', tournament_date), deck_name
            ORDER BY month_start ASC, result_count DESC, deck_name ASC
            """,
            cte_parameters,
        )
        if not rows:
            return []

        monthly_rows: dict[str, list[dict[str, float]]] = defaultdict(list)
        for row in rows:
            month_start = row["month_start"]
            if month_start is None:
                continue
            monthly_rows[str(month_start)].append(
                {
                    "result_count": float(row["result_count"]),
                    "average_cardmarket_deck_price_eur": float(row["average_cardmarket_deck_price_eur"] or 0.0),
                }
            )

        trend_rows: list[dict[str, Any]] = []
        for month_start in sorted(monthly_rows.keys()):
            deck_rows = monthly_rows[month_start]
            if not deck_rows:
                continue
            total_results = int(sum(row["result_count"] for row in deck_rows))
            top_rows = deck_rows[:10]
            top_result_count = int(sum(row["result_count"] for row in top_rows))
            top_deck_name_count = len(top_rows)
            if top_result_count <= 0 or top_deck_name_count <= 0:
                continue
            average_top_10_cardmarket_price_eur = round(
                sum(row["average_cardmarket_deck_price_eur"] for row in top_rows) / top_deck_name_count,
                2,
            )
            weighted_average_top_10_cardmarket_price_eur = round(
                sum(row["average_cardmarket_deck_price_eur"] * row["result_count"] for row in top_rows)
                / top_result_count,
                2,
            )
            trend_rows.append(
                {
                    "month_start": month_start,
                    "result_count": total_results,
                    "top_10_deck_name_count": top_deck_name_count,
                    "top_10_result_count": top_result_count,
                    "top_10_result_share_pct": round(top_result_count * 100.0 / total_results, 2),
                    "average_top_10_cardmarket_price_eur": average_top_10_cardmarket_price_eur,
                    "weighted_average_top_10_cardmarket_price_eur": weighted_average_top_10_cardmarket_price_eur,
                }
            )
        return trend_rows

    def get_deck_cards(
        self,
        deck_site_id: int,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        grouped = self.get_deck_cards_detailed(deck_site_id, start_date, end_date)
        compact_columns = {
            "Bild",
            "Karte",
            "Anzahl",
            "Cardmarket €",
            "Gesamt €",
            "Passcode",
        }
        return {
            section: [
                {key: value for key, value in row.items() if key in compact_columns}
                for row in grouped.get(section, [])
            ]
            for section in ("main", "extra", "side")
        }

    def get_deck_cards_detailed(
        self,
        deck_site_id: int,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        summary = self.get_deck_summary(deck_site_id, start_date, end_date)
        if summary is None:
            return {section: [] for section in ("main", "extra", "side")}

        deck_name = str(summary["deck_name"])
        normalized_deck_name = deck_name.strip().lower()
        rows = self._fetch_all(
            f"""
            {self._non_engine_classification_cte(start_date, end_date)}
            , card_metadata_by_name AS (
                SELECT
                    canonical_name,
                    MAX(image_url_small) AS image_url_small,
                    MAX(card_archetype) AS card_archetype,
                    MAX(card_type) AS card_type,
                    MAX(card_race) AS card_race,
                    MAX(frame_type) AS frame_type,
                    MAX(CASE WHEN effect_text IS NOT NULL AND LOWER(TRIM(effect_text)) NOT IN ('none', 'null', 'n/a', 'na') THEN effect_text END) AS effect_text,
                    MAX(cardmarket_price_eur) AS cardmarket_price_eur
                FROM cards
                WHERE canonical_name IS NOT NULL
                GROUP BY canonical_name
            )
            SELECT
                dc.section,
                COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT)) AS card_name,
                SUM(dc.quantity) AS quantity,
                MIN(dc.card_passcode) AS card_passcode,
                COALESCE(MAX(c.image_url_small), MAX(cm.image_url_small)) AS image_url_small,
                COALESCE(MAX(c.card_archetype), MAX(cm.card_archetype)) AS card_archetype,
                COALESCE(MAX(c.card_type), MAX(cm.card_type)) AS card_type,
                COALESCE(MAX(c.card_race), MAX(cm.card_race)) AS card_race,
                COALESCE(MAX(c.frame_type), MAX(cm.frame_type)) AS frame_type,
                COALESCE(
                    MAX(CASE WHEN c.effect_text IS NOT NULL AND LOWER(TRIM(c.effect_text)) NOT IN ('none', 'null', 'n/a', 'na') THEN c.effect_text END),
                    MAX(cm.effect_text)
                ) AS effect_text,
                MAX(COALESCE(cc.classification, 'engine')) AS classification,
                ROUND(COALESCE(MAX(c.cardmarket_price_eur), MAX(cm.cardmarket_price_eur)), 2) AS cardmarket_price_eur,
                ROUND(SUM(dc.quantity) * COALESCE(MAX(c.cardmarket_price_eur), MAX(cm.cardmarket_price_eur)), 2) AS total_cardmarket_price_eur
            FROM deck_cards dc
            LEFT JOIN cards c ON c.card_passcode = dc.card_passcode
            LEFT JOIN card_metadata_by_name cm
              ON cm.canonical_name = COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
            LEFT JOIN classified_cards cc
              ON cc.section = dc.section
             AND cc.card_name = COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
            WHERE dc.deck_site_id = ?
            GROUP BY
                dc.section,
                COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
            ORDER BY
                CASE dc.section
                    WHEN 'main' THEN 1
                    WHEN 'extra' THEN 2
                    WHEN 'side' THEN 3
                    ELSE 4
                END,
                card_name ASC,
                MIN(dc.card_passcode) ASC
            """,
            self._non_engine_classification_parameters(start_date, end_date) + (deck_site_id,),
        )

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            section = str(row["section"])
            component_name = None
            component_type = None
            role_label = None

            if section in {"main", "side"}:
                resolved_component_name, resolved_component_type, resolved_role = self._resolve_deck_group_component_and_role(
                    normalized_deck_name=normalized_deck_name,
                    card_name=str(row["card_name"]),
                    card_archetype=row["card_archetype"],
                    classification=str(row["classification"]),
                    card_type=row["card_type"],
                    frame_type=row["frame_type"],
                    race=row["card_race"],
                    effect_text=row["effect_text"],
                )
                component_name = resolved_component_name
                component_type = resolved_component_type
                if resolved_component_type in {"main_engine", "rest_engine"}:
                    role_label = "Engine"
                elif resolved_component_type == "non_engine_handtrap":
                    role_label = "Handtrap"
                elif resolved_component_type == "non_engine_boardbreaker":
                    role_label = "Boardbreaker"
                elif resolved_role is not None and resolved_role != "unknown_non_engine":
                    role_label = format_non_engine_role_label(resolved_role)
                else:
                    role_label = "Weitere Non-Engine"
            else:
                component_name = "Extra Deck"
                component_type = "extra"

            grouped[section].append(
                {
                    "Bild": row["image_url_small"],
                    "Karte": row["card_name"],
                    "Anzahl": int(row["quantity"]),
                    "Komponente": self._format_detailed_component_label(component_name, component_type),
                    "Rolle": role_label,
                    "Cardmarket €": float(row["cardmarket_price_eur"]) if row["cardmarket_price_eur"] is not None else None,
                    "Gesamt €": float(row["total_cardmarket_price_eur"]) if row["total_cardmarket_price_eur"] is not None else None,
                    "Kostenklasse": self._card_cost_bucket_label(row["cardmarket_price_eur"]),
                    "Passcode": int(row["card_passcode"]),
                }
            )
        return {section: grouped.get(section, []) for section in ("main", "extra", "side")}

    def get_deck_section_heatmap_rows(
        self,
        deck_site_id: int,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        detailed_cards = self.get_deck_cards_detailed(deck_site_id, start_date, end_date)
        section_labels = {
            "main": "Main Deck",
            "extra": "Extra Deck",
            "side": "Side Deck",
        }
        section_rank = {
            "main": 1,
            "extra": 2,
            "side": 3,
        }

        heatmap_rows: list[dict[str, Any]] = []
        for section in ("main", "extra", "side"):
            for row in detailed_cards.get(section, []):
                quantity = int(row["Anzahl"])
                heatmap_rows.append(
                    {
                        "section": section,
                        "section_label": section_labels[section],
                        "section_rank": section_rank[section],
                        "card_name": row["Karte"],
                        "quantity": quantity,
                        "quantity_label": f"{quantity}x",
                        "component_label": row.get("Komponente"),
                        "role_label": row.get("Rolle"),
                        "cost_bucket": row.get("Kostenklasse"),
                        "cardmarket_price_eur": row.get("Cardmarket €"),
                        "total_cardmarket_price_eur": row.get("Gesamt €"),
                    }
                )

        heatmap_rows.sort(
            key=lambda row: (
                int(row["section_rank"]),
                -int(row["quantity"]),
                str(row["card_name"]),
            )
        )
        return heatmap_rows

    def get_aggregated_deck_cards(
        self,
        deck_name: str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        rows = self._fetch_all(
            f"""
            {self._non_engine_classification_cte(start_date, end_date)}
            ,
            matching_decks AS (
                SELECT deck_site_id
                FROM filtered_decks
                WHERE deck_name = ?
            ),
            deck_totals AS (
                SELECT COUNT(*) AS total_decks
                FROM matching_decks
            ),
            per_deck_cards AS (
                SELECT
                    dc.deck_site_id,
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT)) AS card_name,
                    MIN(c.image_url_small) AS image_url_small,
                    MAX(c.card_archetype) AS card_archetype,
                    MAX(c.card_type) AS card_type,
                    MAX(c.card_race) AS card_race,
                    MAX(c.frame_type) AS frame_type,
                    MAX(CASE WHEN c.effect_text IS NOT NULL AND LOWER(TRIM(c.effect_text)) NOT IN ('none', 'null', 'n/a', 'na') THEN c.effect_text END) AS effect_text,
                    SUM(dc.quantity) AS copies_in_deck,
                    SUM(dc.quantity * c.cardmarket_price_eur) AS total_cardmarket_cost_eur
                FROM deck_cards dc
                JOIN matching_decks md ON md.deck_site_id = dc.deck_site_id
                LEFT JOIN cards c ON c.card_passcode = dc.card_passcode
                GROUP BY
                    dc.deck_site_id,
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
            ),
            card_stats AS (
                SELECT
                    pdc.section,
                    pdc.card_name,
                    MIN(pdc.image_url_small) AS image_url_small,
                    MAX(pdc.card_archetype) AS card_archetype,
                    MAX(pdc.card_type) AS card_type,
                    MAX(pdc.card_race) AS card_race,
                    MAX(pdc.frame_type) AS frame_type,
                    MAX(CASE WHEN pdc.effect_text IS NOT NULL AND LOWER(TRIM(pdc.effect_text)) NOT IN ('none', 'null', 'n/a', 'na') THEN pdc.effect_text END) AS effect_text,
                    COUNT(*) AS deck_count,
                    SUM(pdc.copies_in_deck) AS total_copies,
                    SUM(pdc.total_cardmarket_cost_eur) AS total_cardmarket_cost_eur,
                    AVG(pdc.copies_in_deck * 1.0) AS average_copies_when_present
                FROM per_deck_cards pdc
                GROUP BY
                    pdc.section,
                    pdc.card_name
            )
            SELECT
                cs.section,
                cs.card_name,
                cs.image_url_small,
                cs.card_type,
                cs.card_race,
                cs.frame_type,
                cs.effect_text,
                CASE
                    WHEN cs.section = 'extra'
                    THEN 'Extra Deck'
                    WHEN cs.card_archetype IS NOT NULL
                         AND LENGTH(TRIM(cs.card_archetype)) > 0
                         AND (
                             LOWER(?) LIKE '%' || LOWER(cs.card_archetype) || '%'
                             OR LOWER(cs.card_archetype) LIKE '%' || LOWER(?) || '%'
                         )
                    THEN 'Hauptengine: ' || cs.card_archetype
                    WHEN COALESCE(cc.classification, 'engine') = 'non_engine'
                    THEN 'Non-Engine'
                    WHEN COALESCE(cc.classification, 'engine') = 'candidate_splash'
                    THEN 'Candidate Splash'
                    ELSE 'Restliche Engine'
                END AS component_class,
                cs.deck_count,
                cs.total_copies,
                ROUND(cs.deck_count * 100.0 / dt.total_decks, 1) AS inclusion_rate_pct,
                ROUND(cs.total_copies * 1.0 / dt.total_decks, 2) AS average_copies_per_deck,
                ROUND(cs.average_copies_when_present, 2) AS average_copies_when_present,
                ROUND(cs.total_cardmarket_cost_eur * 1.0 / cs.total_copies, 2) AS average_cardmarket_price_eur,
                ROUND(cs.total_cardmarket_cost_eur * 1.0 / dt.total_decks, 2) AS average_cardmarket_cost_per_deck_eur
            FROM card_stats cs
            LEFT JOIN classified_cards cc
              ON cc.section = cs.section
             AND cc.card_name = cs.card_name
            CROSS JOIN deck_totals dt
            WHERE dt.total_decks > 0
            ORDER BY
                CASE cs.section
                    WHEN 'main' THEN 1
                    WHEN 'extra' THEN 2
                    WHEN 'side' THEN 3
                    ELSE 4
                END,
                inclusion_rate_pct DESC,
                average_copies_per_deck DESC,
                cs.card_name ASC
            """,
            self._non_engine_classification_parameters(start_date, end_date) + (deck_name, deck_name, deck_name),
        )
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            component_class = str(row["component_class"])
            if component_class == "Non-Engine":
                role_scores = classify_non_engine_role(
                    card_name=row["card_name"],
                    card_type=row["card_type"],
                    frame_type=row["frame_type"],
                    race=row["card_race"],
                    effect_text=row["effect_text"],
                    average_main_copies=row["average_copies_per_deck"] if row["section"] == "main" else 0.0,
                    average_side_copies=row["average_copies_per_deck"] if row["section"] == "side" else 0.0,
                )
                component_class = f"Non-Engine: {format_non_engine_role_label(role_scores.role)}"
            grouped[str(row["section"])].append(
                {
                    "Bild": row["image_url_small"],
                    "Karte": row["card_name"],
                    "Klasse": component_class,
                    "In Decks": int(row["deck_count"]),
                    "Anteil %": float(row["inclusion_rate_pct"]),
                    "Ø Kopien / Deck": float(row["average_copies_per_deck"]),
                    "Ø Kopien bei Nutzung": float(row["average_copies_when_present"]),
                    "Ø Cardmarket €": float(row["average_cardmarket_price_eur"]) if row["average_cardmarket_price_eur"] is not None else None,
                    "Ø Kosten / Deck €": float(row["average_cardmarket_cost_per_deck_eur"]) if row["average_cardmarket_cost_per_deck_eur"] is not None else None,
                    "Gesamtkopien": int(row["total_copies"]),
                }
            )
        return {section: grouped.get(section, []) for section in ("main", "extra", "side")}

    def list_deck_instances_for_name(
        self,
        deck_name: str,
        limit: int = 250,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        cte_sql, cte_parameters = self._deck_summaries_with_prices_cte(start_date, end_date)
        rows = self._fetch_all(
            f"""
            WITH {cte_sql}
            SELECT
                deck_site_id,
                deck_name,
                player_name,
                placement,
                placement_sort_value,
                participants_count,
                tournament_name,
                tournament_date,
                country,
                main_card_total,
                extra_card_total,
                side_card_total,
                cardmarket_deck_price_eur,
                deck_url
            FROM filtered_deck_summaries
            WHERE deck_name = ?
            ORDER BY tournament_date DESC, placement_sort_value ASC, player_name ASC
            LIMIT ?
            """,
            cte_parameters + (deck_name, limit),
        )
        return [dict(row) for row in rows]

    def list_non_engine_cards(
        self,
        classification: str = "non_engine",
        limit: int = 250,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._fetch_all(
            f"""
            {self._non_engine_classification_cte(start_date, end_date)}
            , target_card_sections AS (
                SELECT
                    cc.section,
                    cc.card_name,
                    MAX(cc.card_archetype) AS card_archetype,
                    MIN(cc.card_passcode) AS card_passcode,
                    MIN(c.image_url_small) AS image_url_small,
                    MAX(c.card_type) AS card_type,
                    MAX(c.card_race) AS card_race,
                    MAX(c.frame_type) AS frame_type,
                    MAX(CASE WHEN c.effect_text IS NOT NULL AND LOWER(TRIM(c.effect_text)) NOT IN ('none', 'null', 'n/a', 'na') THEN c.effect_text END) AS effect_text
                FROM classified_cards cc
                LEFT JOIN cards c ON c.card_passcode = cc.card_passcode
                WHERE classification = ?
                GROUP BY cc.section, cc.card_name
            ),
            target_card_names AS (
                SELECT
                    card_name,
                    MAX(card_archetype) AS card_archetype,
                    MIN(card_passcode) AS card_passcode,
                    MIN(image_url_small) AS image_url_small,
                    MAX(card_type) AS card_type,
                    MAX(card_race) AS card_race,
                    MAX(frame_type) AS frame_type,
                    MAX(CASE WHEN effect_text IS NOT NULL AND LOWER(TRIM(effect_text)) NOT IN ('none', 'null', 'n/a', 'na') THEN effect_text END) AS effect_text
                FROM target_card_sections
                GROUP BY card_name
            ),
            per_deck_section_cards AS (
                SELECT
                    fd.deck_site_id,
                    fd.deck_name,
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT)) AS card_name,
                    SUM(dc.quantity) AS copies_in_deck_section,
                    SUM(dc.quantity * c.cardmarket_price_eur) AS total_cardmarket_cost_eur
                FROM filtered_decks fd
                JOIN deck_cards dc ON dc.deck_site_id = fd.deck_site_id
                LEFT JOIN cards c ON c.card_passcode = dc.card_passcode
                WHERE dc.section IN ('main', 'side')
                GROUP BY
                    fd.deck_site_id,
                    fd.deck_name,
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
            ),
            filtered_per_deck_cards AS (
                SELECT
                    pds.deck_site_id,
                    pds.deck_name,
                    pds.card_name,
                    MAX(CASE WHEN pds.section = 'main' THEN pds.copies_in_deck_section ELSE 0 END) AS main_copies_in_deck,
                    MAX(CASE WHEN pds.section = 'side' THEN pds.copies_in_deck_section ELSE 0 END) AS side_copies_in_deck,
                    MAX(CASE WHEN pds.section = 'main' THEN pds.total_cardmarket_cost_eur ELSE 0 END) AS main_cardmarket_cost_eur,
                    MAX(CASE WHEN pds.section = 'side' THEN pds.total_cardmarket_cost_eur ELSE 0 END) AS side_cardmarket_cost_eur
                FROM per_deck_section_cards pds
                JOIN target_card_sections tcs
                  ON tcs.card_name = pds.card_name
                 AND tcs.section = pds.section
                GROUP BY
                    pds.deck_site_id,
                    pds.deck_name,
                    pds.card_name
            ),
            per_group_card_usage AS (
                SELECT
                    fpdc.card_name,
                    fpdc.deck_name,
                    COUNT(*) AS decks_with_card_in_group
                FROM filtered_per_deck_cards fpdc
                GROUP BY fpdc.card_name, fpdc.deck_name
            ),
            aggregated_cards AS (
                SELECT
                    tcn.card_name,
                    tcn.card_archetype,
                    tcn.card_passcode,
                    tcn.image_url_small,
                    tcn.card_type,
                    tcn.card_race,
                    tcn.frame_type,
                    tcn.effect_text,
                    COUNT(*) AS total_decks_with_card,
                    COUNT(DISTINCT fpdc.deck_name) AS deck_group_count,
                    SUM(CASE WHEN fpdc.main_copies_in_deck > 0 THEN 1 ELSE 0 END) AS decks_with_main,
                    SUM(CASE WHEN fpdc.side_copies_in_deck > 0 THEN 1 ELSE 0 END) AS decks_with_side,
                    SUM(fpdc.main_copies_in_deck) AS total_main_copies,
                    SUM(fpdc.side_copies_in_deck) AS total_side_copies,
                    SUM(fpdc.main_copies_in_deck + fpdc.side_copies_in_deck) AS total_copies,
                    SUM(fpdc.main_cardmarket_cost_eur + fpdc.side_cardmarket_cost_eur) AS total_cardmarket_cost_eur,
                    AVG(fpdc.main_copies_in_deck + fpdc.side_copies_in_deck) AS average_copies_when_present
                FROM filtered_per_deck_cards fpdc
                JOIN target_card_names tcn ON tcn.card_name = fpdc.card_name
                GROUP BY tcn.card_name, tcn.card_archetype, tcn.card_passcode
            )
            SELECT
                ac.card_name,
                ac.card_archetype,
                ac.card_passcode,
                ac.image_url_small,
                ac.card_type,
                ac.card_race,
                ac.frame_type,
                ac.effect_text,
                ac.total_decks_with_card,
                ac.deck_group_count,
                ROUND(ac.total_decks_with_card * 100.0 / gdt.total_decks, 1) AS global_inclusion_rate_pct,
                ROUND(ac.deck_group_count * 100.0 / gdt.total_deck_groups, 1) AS deck_group_spread_pct,
                ROUND(
                    COALESCE(
                        (
                            SELECT MAX(pgu.decks_with_card_in_group * 1.0 / ac.total_decks_with_card)
                            FROM per_group_card_usage pgu
                            WHERE pgu.card_name = ac.card_name
                        ),
                        0.0
                    ) * 100.0,
                    1
                ) AS max_group_share_pct,
                ROUND(
                    COALESCE(
                        (
                            SELECT SUM(
                                CASE
                                    WHEN ac.card_archetype IS NOT NULL
                                         AND LENGTH(TRIM(ac.card_archetype)) > 0
                                         AND (
                                             LOWER(pgu.deck_name) LIKE '%' || LOWER(ac.card_archetype) || '%'
                                             OR LOWER(ac.card_archetype) LIKE '%' || LOWER(pgu.deck_name) || '%'
                                         )
                                    THEN pgu.decks_with_card_in_group
                                    ELSE 0
                                END
                            ) * 1.0 / ac.total_decks_with_card
                            FROM per_group_card_usage pgu
                            WHERE pgu.card_name = ac.card_name
                        ),
                        0.0
                    ) * 100.0,
                    1
                ) AS archetype_match_share_pct,
                ROUND(ac.total_main_copies * 1.0 / gdt.total_decks, 2) AS average_main_copies_per_deck,
                ROUND(ac.total_side_copies * 1.0 / gdt.total_decks, 2) AS average_side_copies_per_deck,
                ROUND(ac.decks_with_main * 100.0 / gdt.total_decks, 1) AS main_presence_pct,
                ROUND(ac.decks_with_side * 100.0 / gdt.total_decks, 1) AS side_presence_pct,
                ROUND(ac.average_copies_when_present, 2) AS average_copies_when_present,
                ROUND(ac.total_cardmarket_cost_eur * 1.0 / NULLIF(ac.total_copies, 0), 2) AS average_cardmarket_price_eur,
                ac.total_copies
            FROM aggregated_cards ac
            CROSS JOIN global_deck_totals gdt
            WHERE gdt.total_decks > 0
              AND gdt.total_deck_groups > 0
            ORDER BY
                ac.total_decks_with_card DESC,
                ac.deck_group_count DESC,
                ac.card_name ASC
            LIMIT ?
            """,
            self._non_engine_classification_parameters(start_date, end_date) + (classification, limit),
        )
        return self._annotate_non_engine_roles([dict(row) for row in rows], classification=classification)

    def list_non_engine_cards_for_deck_group(
        self,
        deck_name: str,
        classification: str = "non_engine",
        limit: int = 250,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._fetch_all(
            f"""
            {self._non_engine_classification_cte(start_date, end_date)}
            , matching_decks AS (
                SELECT deck_site_id
                FROM filtered_decks
                WHERE deck_name = ?
            ),
            deck_group_total AS (
                SELECT COUNT(*) AS total_decks
                FROM matching_decks
            ),
            target_card_sections AS (
                SELECT
                    cc.section,
                    cc.card_name,
                    MAX(cc.card_archetype) AS card_archetype,
                    MIN(cc.card_passcode) AS card_passcode,
                    MIN(c.image_url_small) AS image_url_small,
                    MAX(c.card_type) AS card_type,
                    MAX(c.card_race) AS card_race,
                    MAX(c.frame_type) AS frame_type,
                    MAX(CASE WHEN c.effect_text IS NOT NULL AND LOWER(TRIM(c.effect_text)) NOT IN ('none', 'null', 'n/a', 'na') THEN c.effect_text END) AS effect_text
                FROM classified_cards cc
                LEFT JOIN cards c ON c.card_passcode = cc.card_passcode
                WHERE classification = ?
                GROUP BY cc.section, cc.card_name
            ),
            target_card_names AS (
                SELECT
                    card_name,
                    MAX(card_archetype) AS card_archetype,
                    MIN(card_passcode) AS card_passcode,
                    MIN(image_url_small) AS image_url_small,
                    MAX(card_type) AS card_type,
                    MAX(card_race) AS card_race,
                    MAX(frame_type) AS frame_type,
                    MAX(CASE WHEN effect_text IS NOT NULL AND LOWER(TRIM(effect_text)) NOT IN ('none', 'null', 'n/a', 'na') THEN effect_text END) AS effect_text
                FROM target_card_sections
                GROUP BY card_name
            ),
            per_deck_section_cards AS (
                SELECT
                    dc.deck_site_id,
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT)) AS card_name,
                    SUM(dc.quantity) AS copies_in_deck,
                    SUM(dc.quantity * c.cardmarket_price_eur) AS total_cardmarket_cost_eur
                FROM deck_cards dc
                JOIN matching_decks md ON md.deck_site_id = dc.deck_site_id
                LEFT JOIN cards c ON c.card_passcode = dc.card_passcode
                WHERE dc.section IN ('main', 'side')
                GROUP BY
                    dc.deck_site_id,
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
            ),
            filtered_per_deck_cards AS (
                SELECT
                    pds.deck_site_id,
                    pds.card_name,
                    MAX(CASE WHEN pds.section = 'main' THEN pds.copies_in_deck ELSE 0 END) AS main_copies_in_deck,
                    MAX(CASE WHEN pds.section = 'side' THEN pds.copies_in_deck ELSE 0 END) AS side_copies_in_deck,
                    MAX(CASE WHEN pds.section = 'main' THEN pds.total_cardmarket_cost_eur ELSE 0 END) AS main_cardmarket_cost_eur,
                    MAX(CASE WHEN pds.section = 'side' THEN pds.total_cardmarket_cost_eur ELSE 0 END) AS side_cardmarket_cost_eur
                FROM per_deck_section_cards pds
                JOIN target_card_sections tcs
                  ON tcs.card_name = pds.card_name
                 AND tcs.section = pds.section
                GROUP BY pds.deck_site_id, pds.card_name
            ),
            aggregated_local_cards AS (
                SELECT
                    tcn.card_name,
                    tcn.card_archetype,
                    tcn.card_passcode,
                    tcn.image_url_small,
                    tcn.card_type,
                    tcn.card_race,
                    tcn.frame_type,
                    tcn.effect_text,
                    COUNT(*) AS decks_with_card,
                    SUM(CASE WHEN fpdc.main_copies_in_deck > 0 THEN 1 ELSE 0 END) AS decks_with_main,
                    SUM(CASE WHEN fpdc.side_copies_in_deck > 0 THEN 1 ELSE 0 END) AS decks_with_side,
                    SUM(fpdc.main_copies_in_deck) AS total_main_copies,
                    SUM(fpdc.side_copies_in_deck) AS total_side_copies,
                    SUM(fpdc.main_copies_in_deck + fpdc.side_copies_in_deck) AS total_copies,
                    SUM(fpdc.main_cardmarket_cost_eur + fpdc.side_cardmarket_cost_eur) AS total_cardmarket_cost_eur,
                    AVG(fpdc.main_copies_in_deck + fpdc.side_copies_in_deck) AS average_copies_when_present,
                    dgt.total_decks AS deck_group_size
                FROM filtered_per_deck_cards fpdc
                JOIN target_card_names tcn ON tcn.card_name = fpdc.card_name
                CROSS JOIN deck_group_total dgt
                GROUP BY
                    tcn.card_name,
                    tcn.card_archetype,
                    tcn.card_passcode,
                    dgt.total_decks
            )
            SELECT
                alc.card_name,
                alc.card_archetype,
                alc.card_passcode,
                alc.image_url_small,
                alc.card_type,
                alc.card_race,
                alc.frame_type,
                alc.effect_text,
                alc.decks_with_card AS decks_in_group,
                alc.deck_group_size,
                ROUND(alc.decks_with_card * 100.0 / alc.deck_group_size, 1) AS group_inclusion_rate_pct,
                ROUND(alc.total_main_copies * 1.0 / alc.deck_group_size, 2) AS average_main_copies_per_group_deck,
                ROUND(alc.total_side_copies * 1.0 / alc.deck_group_size, 2) AS average_side_copies_per_group_deck,
                ROUND(alc.decks_with_main * 100.0 / alc.deck_group_size, 1) AS main_presence_pct,
                ROUND(alc.decks_with_side * 100.0 / alc.deck_group_size, 1) AS side_presence_pct,
                ROUND(alc.average_copies_when_present, 2) AS average_copies_when_present,
                ROUND(alc.total_cardmarket_cost_eur * 1.0 / NULLIF(alc.total_copies, 0), 2) AS average_cardmarket_price_eur,
                alc.total_copies
            FROM aggregated_local_cards alc
            WHERE alc.deck_group_size > 0
            ORDER BY
                group_inclusion_rate_pct DESC,
                (average_main_copies_per_group_deck + average_side_copies_per_group_deck) DESC,
                alc.card_name ASC
            LIMIT ?
            """,
            self._non_engine_classification_parameters(start_date, end_date) + (deck_name, classification, limit),
        )
        return self._annotate_non_engine_roles([dict(row) for row in rows], classification=classification)

    def list_tournaments(
        self,
        limit: int = 50,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        filter_sql, filter_parameters = self._date_filter_clause(
            "tournament_date",
            start_date,
            end_date,
            prefix="WHERE",
        )
        rows = self._fetch_all(
            f"""
            SELECT
                tournament_site_id,
                tournament_name,
                tournament_date,
                country,
                tier,
                participants_count,
                tournament_url
            FROM tournaments
            {filter_sql}
            ORDER BY tournament_date DESC, tournament_name ASC
            LIMIT ?
            """,
            filter_parameters + (limit,),
        )
        return [dict(row) for row in rows]

    def list_skip_reason_summary(self) -> list[dict[str, Any]]:
        rows = self._fetch_all(
            """
            SELECT
                skip_reason,
                COUNT(*) AS anzahl
            FROM skipped_sources
            GROUP BY skip_reason
            ORDER BY anzahl DESC, skip_reason ASC
            """
        )
        return [dict(row) for row in rows]

    def list_skipped_sources(self, limit: int = 25) -> list[dict[str, Any]]:
        rows = self._fetch_all(
            """
            SELECT
                source_type,
                skip_reason,
                matched_text,
                source_url,
                seen_at
            FROM skipped_sources
            ORDER BY skipped_id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]

    def _annotate_non_engine_roles(
        self,
        rows: list[dict[str, Any]],
        *,
        classification: str,
    ) -> list[dict[str, Any]]:
        annotated_rows: list[dict[str, Any]] = []
        for row in rows:
            annotated = dict(row)
            if classification == "non_engine":
                role_scores = classify_non_engine_role(
                    card_name=annotated.get("card_name"),
                    card_type=annotated.get("card_type"),
                    frame_type=annotated.get("frame_type"),
                    race=annotated.get("card_race"),
                    effect_text=annotated.get("effect_text"),
                    average_main_copies=annotated.get("average_main_copies_per_deck")
                    or annotated.get("average_main_copies_per_group_deck"),
                    average_side_copies=annotated.get("average_side_copies_per_deck")
                    or annotated.get("average_side_copies_per_group_deck"),
                    main_presence_pct=annotated.get("main_presence_pct"),
                    side_presence_pct=annotated.get("side_presence_pct"),
                )
                annotated["non_engine_role"] = role_scores.role
                annotated["non_engine_role_label"] = format_non_engine_role_label(role_scores.role)
                annotated["role_confidence"] = role_scores.confidence
                annotated["handtrap_score"] = role_scores.handtrap_score
                annotated["boardbreaker_score"] = role_scores.boardbreaker_score
                annotated["floodgate_score"] = role_scores.floodgate_score
                annotated["protection_score"] = role_scores.protection_score
                annotated["draw_engine_score"] = role_scores.draw_engine_score
            else:
                annotated["non_engine_role"] = None
                annotated["non_engine_role_label"] = "-"
                annotated["role_confidence"] = None
                annotated["handtrap_score"] = None
                annotated["boardbreaker_score"] = None
                annotated["floodgate_score"] = None
                annotated["protection_score"] = None
                annotated["draw_engine_score"] = None
            annotated_rows.append(annotated)
        return annotated_rows

    def _attach_deck_name_component_averages(
        self,
        rows: list[dict[str, Any]],
        *,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        if not rows:
            return rows

        deck_names = [str(row["deck_name"]) for row in rows if row.get("deck_name") is not None]
        component_averages = self._get_deck_name_main_component_averages(
            deck_names,
            start_date=start_date,
            end_date=end_date,
        )

        annotated_rows: list[dict[str, Any]] = []
        for row in rows:
            annotated = dict(row)
            averages = component_averages.get(
                str(annotated["deck_name"]),
                {
                    "average_engine_card_total": 0.0,
                    "average_handtrap_card_total": 0.0,
                    "average_boardbreaker_card_total": 0.0,
                },
            )
            annotated.update(averages)
            annotated_rows.append(annotated)
        return annotated_rows

    def _attach_deck_name_aggregate_enrichments(
        self,
        rows: list[dict[str, Any]],
        *,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        if not rows:
            return rows

        deck_names = [str(row["deck_name"]) for row in rows if row.get("deck_name") is not None]
        totals = self._get_filtered_deck_summary_totals(start_date=start_date, end_date=end_date)
        component_averages = self._get_deck_name_main_component_averages(
            deck_names,
            start_date=start_date,
            end_date=end_date,
        )
        side_profile_averages = self._get_deck_name_side_profile_averages(
            deck_names,
            start_date=start_date,
            end_date=end_date,
        )
        distribution_metrics = self._get_deck_name_distribution_metrics(
            deck_names,
            start_date=start_date,
            end_date=end_date,
            latest_tournament_date=totals["latest_tournament_date"],
        )

        annotated_rows: list[dict[str, Any]] = []
        total_deck_count = int(totals["total_deck_count"])
        total_tournament_count = int(totals["total_tournament_count"])
        component_defaults = {
            "average_engine_card_total": 0.0,
            "average_handtrap_card_total": 0.0,
            "average_boardbreaker_card_total": 0.0,
        }
        side_defaults = {
            "average_side_non_engine_share_pct": 0.0,
            "average_side_handtrap_share_pct": 0.0,
            "average_side_boardbreaker_share_pct": 0.0,
            "average_side_non_engine_other_share_pct": 0.0,
        }
        distribution_defaults = {
            "average_placement_percentile": None,
            "median_placement_percentile": None,
            "placement_percentile_p25": None,
            "placement_percentile_p75": None,
            "placement_percentile_iqr": None,
            "top_25_finish_rate_pct": None,
            "valid_placement_percentile_count": 0,
            "median_cardmarket_deck_price_eur": None,
            "cardmarket_deck_price_p25_eur": None,
            "cardmarket_deck_price_p75_eur": None,
            "cardmarket_deck_price_iqr_eur": None,
            "priced_deck_count": 0,
            "recent_30d_result_count": 0,
            "recent_30d_result_share_pct": None,
        }

        for row in rows:
            annotated = dict(row)
            deck_name = str(annotated["deck_name"])
            deck_count = int(annotated.get("deck_count") or 0)
            tournament_count = int(annotated.get("tournament_count") or 0)
            player_count = int(annotated.get("player_count") or 0)

            annotated.update(component_averages.get(deck_name, component_defaults))
            annotated.update(side_profile_averages.get(deck_name, side_defaults))
            annotated.update(distribution_metrics.get(deck_name, distribution_defaults))
            annotated["meta_share_pct"] = round(deck_count * 100.0 / total_deck_count, 2) if total_deck_count > 0 else 0.0
            annotated["tournament_coverage_pct"] = (
                round(tournament_count * 100.0 / total_tournament_count, 2) if total_tournament_count > 0 else 0.0
            )
            annotated["player_diversity_ratio"] = round(player_count / deck_count, 3) if deck_count > 0 else 0.0
            annotated_rows.append(annotated)
        return annotated_rows

    def _get_filtered_deck_summary_totals(
        self,
        *,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> dict[str, Any]:
        cte_sql, cte_parameters = self._deck_summaries_with_prices_cte(start_date, end_date)
        row = self._fetch_one(
            f"""
            WITH {cte_sql}
            SELECT
                COUNT(*) AS total_deck_count,
                COUNT(DISTINCT tournament_site_id) AS total_tournament_count,
                MAX(tournament_date) AS latest_tournament_date
            FROM filtered_deck_summaries
            """,
            cte_parameters,
        )
        latest_tournament_date = None
        if row is not None and row["latest_tournament_date"] is not None:
            latest_tournament_date = date.fromisoformat(str(row["latest_tournament_date"]))
        return {
            "total_deck_count": int(row["total_deck_count"]) if row is not None and row["total_deck_count"] is not None else 0,
            "total_tournament_count": int(row["total_tournament_count"]) if row is not None and row["total_tournament_count"] is not None else 0,
            "latest_tournament_date": latest_tournament_date,
        }

    def _get_deck_name_distribution_metrics(
        self,
        deck_names: list[str],
        *,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        latest_tournament_date: date | None = None,
    ) -> dict[str, dict[str, Any]]:
        normalized_deck_names = sorted({deck_name.strip() for deck_name in deck_names if deck_name.strip()})
        if not normalized_deck_names:
            return {}

        placeholders = ", ".join("?" for _ in normalized_deck_names)
        cte_sql, cte_parameters = self._deck_summaries_with_prices_cte(start_date, end_date)
        rows = self._fetch_all(
            f"""
            WITH {cte_sql}
            SELECT
                deck_name,
                participants_count,
                placement_sort_value,
                cardmarket_deck_price_eur,
                tournament_date
            FROM filtered_deck_summaries
            WHERE deck_name IN ({placeholders})
            ORDER BY deck_name ASC, tournament_date ASC, placement_sort_value ASC
            """,
            cte_parameters + tuple(normalized_deck_names),
        )

        recent_cutoff_date = latest_tournament_date - timedelta(days=30) if latest_tournament_date is not None else None
        deck_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "placement_percentiles": [],
                "known_prices": [],
                "result_count": 0,
                "recent_30d_result_count": 0,
            }
        )

        for row in rows:
            deck_name = str(row["deck_name"])
            stats = deck_stats[deck_name]
            stats["result_count"] += 1

            placement_percentile = self._placement_percentile_value(
                participants_count=row["participants_count"],
                placement_sort_value=row["placement_sort_value"],
            )
            if placement_percentile is not None:
                stats["placement_percentiles"].append(placement_percentile)

            if row["cardmarket_deck_price_eur"] is not None:
                cardmarket_deck_price_eur = float(row["cardmarket_deck_price_eur"])
                if cardmarket_deck_price_eur > 0:
                    stats["known_prices"].append(cardmarket_deck_price_eur)

            if recent_cutoff_date is not None and row["tournament_date"] is not None:
                tournament_date = date.fromisoformat(str(row["tournament_date"]))
                if tournament_date >= recent_cutoff_date:
                    stats["recent_30d_result_count"] += 1

        distribution_metrics: dict[str, dict[str, Any]] = {}
        for deck_name in normalized_deck_names:
            stats = deck_stats.get(deck_name)
            if stats is None:
                distribution_metrics[deck_name] = {}
                continue

            placement_percentiles = sorted(float(value) for value in stats["placement_percentiles"])
            known_prices = sorted(float(value) for value in stats["known_prices"])
            placement_p25 = self._interpolated_quantile(placement_percentiles, 0.25)
            placement_p50 = self._interpolated_quantile(placement_percentiles, 0.50)
            placement_p75 = self._interpolated_quantile(placement_percentiles, 0.75)
            price_p25 = self._interpolated_quantile(known_prices, 0.25)
            price_p50 = self._interpolated_quantile(known_prices, 0.50)
            price_p75 = self._interpolated_quantile(known_prices, 0.75)

            average_placement_percentile = (
                round(sum(placement_percentiles) / len(placement_percentiles), 2) if placement_percentiles else None
            )
            top_25_finish_rate_pct = (
                round(
                    sum(1 for value in placement_percentiles if value >= 75.0) * 100.0 / len(placement_percentiles),
                    2,
                )
                if placement_percentiles
                else None
            )

            distribution_metrics[deck_name] = {
                "average_placement_percentile": average_placement_percentile,
                "median_placement_percentile": placement_p50,
                "placement_percentile_p25": placement_p25,
                "placement_percentile_p75": placement_p75,
                "placement_percentile_iqr": round(placement_p75 - placement_p25, 2)
                if placement_p25 is not None and placement_p75 is not None
                else None,
                "top_25_finish_rate_pct": top_25_finish_rate_pct,
                "valid_placement_percentile_count": len(placement_percentiles),
                "median_cardmarket_deck_price_eur": price_p50,
                "cardmarket_deck_price_p25_eur": price_p25,
                "cardmarket_deck_price_p75_eur": price_p75,
                "cardmarket_deck_price_iqr_eur": round(price_p75 - price_p25, 2)
                if price_p25 is not None and price_p75 is not None
                else None,
                "priced_deck_count": len(known_prices),
                "recent_30d_result_count": int(stats["recent_30d_result_count"]),
                "recent_30d_result_share_pct": round(
                    int(stats["recent_30d_result_count"]) * 100.0 / int(stats["result_count"]),
                    2,
                )
                if int(stats["result_count"]) > 0 and recent_cutoff_date is not None
                else None,
            }
        return distribution_metrics

    def _get_deck_name_side_profile_averages(
        self,
        deck_names: list[str],
        *,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> dict[str, dict[str, float]]:
        normalized_deck_names = sorted({deck_name.strip() for deck_name in deck_names if deck_name.strip()})
        if not normalized_deck_names:
            return {}

        placeholders = ", ".join("?" for _ in normalized_deck_names)
        rows = self._fetch_all(
            f"""
            {self._non_engine_classification_cte(start_date, end_date)}
            , per_deck_side_cards AS (
                SELECT
                    fd.deck_name,
                    fd.deck_site_id,
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT)) AS card_name,
                    MAX(c.card_archetype) AS card_archetype,
                    MAX(c.card_type) AS card_type,
                    MAX(c.card_race) AS card_race,
                    MAX(c.frame_type) AS frame_type,
                    MAX(CASE WHEN c.effect_text IS NOT NULL AND LOWER(TRIM(c.effect_text)) NOT IN ('none', 'null', 'n/a', 'na') THEN c.effect_text END) AS effect_text,
                    COALESCE(MAX(cc.classification), 'engine') AS classification,
                    SUM(dc.quantity) AS copies_in_deck
                FROM filtered_decks fd
                JOIN deck_cards dc ON dc.deck_site_id = fd.deck_site_id
                LEFT JOIN cards c ON c.card_passcode = dc.card_passcode
                LEFT JOIN classified_cards cc
                  ON cc.section = dc.section
                 AND cc.card_name = COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
                WHERE dc.section = 'side'
                  AND fd.deck_name IN ({placeholders})
                GROUP BY
                    fd.deck_name,
                    fd.deck_site_id,
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
            )
            SELECT
                deck_name,
                deck_site_id,
                card_name,
                card_archetype,
                card_type,
                card_race,
                frame_type,
                effect_text,
                classification,
                copies_in_deck
            FROM per_deck_side_cards
            ORDER BY deck_name ASC, deck_site_id ASC, card_name ASC
            """,
            self._non_engine_classification_parameters(start_date, end_date) + tuple(normalized_deck_names),
        )

        deck_ids_by_name: dict[str, set[int]] = defaultdict(set)
        side_metrics_by_deck: dict[tuple[str, int], dict[str, float]] = defaultdict(
            lambda: {
                "total": 0.0,
                "non_engine_total": 0.0,
                "handtrap": 0.0,
                "boardbreaker": 0.0,
                "non_engine_other": 0.0,
            }
        )

        for row in rows:
            deck_name = str(row["deck_name"])
            deck_site_id = int(row["deck_site_id"])
            deck_ids_by_name[deck_name].add(deck_site_id)
            copies_in_deck = float(row["copies_in_deck"])
            side_metrics = side_metrics_by_deck[(deck_name, deck_site_id)]
            side_metrics["total"] += copies_in_deck

            _, component_type, _ = self._resolve_deck_group_component_and_role(
                normalized_deck_name=deck_name.strip().lower(),
                card_name=str(row["card_name"]),
                card_archetype=row["card_archetype"],
                classification=str(row["classification"]),
                card_type=row["card_type"],
                frame_type=row["frame_type"],
                race=row["card_race"],
                effect_text=row["effect_text"],
            )

            if component_type == "non_engine_handtrap":
                side_metrics["non_engine_total"] += copies_in_deck
                side_metrics["handtrap"] += copies_in_deck
            elif component_type == "non_engine_boardbreaker":
                side_metrics["non_engine_total"] += copies_in_deck
                side_metrics["boardbreaker"] += copies_in_deck
            elif component_type == "non_engine_other":
                side_metrics["non_engine_total"] += copies_in_deck
                side_metrics["non_engine_other"] += copies_in_deck

        profile_averages: dict[str, dict[str, float]] = {}
        for deck_name in normalized_deck_names:
            deck_ids = deck_ids_by_name.get(deck_name, set())
            deck_count = len(deck_ids)
            if deck_count <= 0:
                profile_averages[deck_name] = {
                    "average_side_non_engine_share_pct": 0.0,
                    "average_side_handtrap_share_pct": 0.0,
                    "average_side_boardbreaker_share_pct": 0.0,
                    "average_side_non_engine_other_share_pct": 0.0,
                }
                continue

            total_non_engine_share = 0.0
            total_handtrap_share = 0.0
            total_boardbreaker_share = 0.0
            total_other_share = 0.0
            for deck_site_id in deck_ids:
                side_metrics = side_metrics_by_deck.get((deck_name, deck_site_id))
                if side_metrics is None:
                    continue
                side_total = float(side_metrics["total"])
                if side_total <= 0:
                    continue
                total_non_engine_share += float(side_metrics["non_engine_total"]) * 100.0 / side_total
                total_handtrap_share += float(side_metrics["handtrap"]) * 100.0 / side_total
                total_boardbreaker_share += float(side_metrics["boardbreaker"]) * 100.0 / side_total
                total_other_share += float(side_metrics["non_engine_other"]) * 100.0 / side_total

            profile_averages[deck_name] = {
                "average_side_non_engine_share_pct": round(total_non_engine_share / deck_count, 2),
                "average_side_handtrap_share_pct": round(total_handtrap_share / deck_count, 2),
                "average_side_boardbreaker_share_pct": round(total_boardbreaker_share / deck_count, 2),
                "average_side_non_engine_other_share_pct": round(total_other_share / deck_count, 2),
            }
        return profile_averages

    def _placement_percentile_value(self, *, participants_count: Any, placement_sort_value: Any) -> float | None:
        if participants_count is None or placement_sort_value is None:
            return None
        normalized_participants_count = int(participants_count)
        normalized_placement_sort_value = int(placement_sort_value)
        if normalized_participants_count <= 0 or normalized_placement_sort_value <= 0:
            return None
        return (normalized_participants_count - normalized_placement_sort_value + 1) * 100.0 / normalized_participants_count

    def _interpolated_quantile(self, values: list[float], quantile: float) -> float | None:
        if not values:
            return None
        if len(values) == 1:
            return round(float(values[0]), 2)

        bounded_quantile = min(max(quantile, 0.0), 1.0)
        position = (len(values) - 1) * bounded_quantile
        lower_index = int(position)
        upper_index = min(lower_index + 1, len(values) - 1)
        lower_value = float(values[lower_index])
        upper_value = float(values[upper_index])
        interpolated_value = lower_value + (upper_value - lower_value) * (position - lower_index)
        return round(interpolated_value, 2)

    def _get_deck_name_main_component_averages(
        self,
        deck_names: list[str],
        *,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> dict[str, dict[str, float]]:
        normalized_deck_names = sorted({deck_name.strip() for deck_name in deck_names if deck_name.strip()})
        if not normalized_deck_names:
            return {}

        deck_name_filter_sql = ""
        if normalized_deck_names:
            placeholders = ", ".join("?" for _ in normalized_deck_names)
            deck_name_filter_sql = f"AND fd.deck_name IN ({placeholders})"

        rows = self._fetch_all(
            f"""
            {self._non_engine_classification_cte(start_date, end_date)}
            , per_deck_main_cards AS (
                SELECT
                    fd.deck_name,
                    fd.deck_site_id,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT)) AS card_name,
                    MAX(c.card_archetype) AS card_archetype,
                    MAX(c.card_type) AS card_type,
                    MAX(c.card_race) AS card_race,
                    MAX(c.frame_type) AS frame_type,
                    MAX(CASE WHEN c.effect_text IS NOT NULL AND LOWER(TRIM(c.effect_text)) NOT IN ('none', 'null', 'n/a', 'na') THEN c.effect_text END) AS effect_text,
                    COALESCE(MAX(cc.classification), 'engine') AS classification,
                    SUM(dc.quantity) AS copies_in_deck
                FROM filtered_decks fd
                JOIN deck_cards dc ON dc.deck_site_id = fd.deck_site_id
                LEFT JOIN cards c ON c.card_passcode = dc.card_passcode
                LEFT JOIN classified_cards cc
                  ON cc.section = dc.section
                 AND cc.card_name = COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
                WHERE dc.section = 'main'
                  {deck_name_filter_sql}
                GROUP BY
                    fd.deck_name,
                    fd.deck_site_id,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
            )
            SELECT
                deck_name,
                deck_site_id,
                card_name,
                card_archetype,
                card_type,
                card_race,
                frame_type,
                effect_text,
                classification,
                copies_in_deck
            FROM per_deck_main_cards
            ORDER BY deck_name ASC, deck_site_id ASC, card_name ASC
            """,
            self._non_engine_classification_parameters(start_date, end_date) + tuple(normalized_deck_names),
        )

        deck_component_sums: dict[str, dict[str, float]] = defaultdict(
            lambda: {
                "engine_total": 0.0,
                "handtrap_total": 0.0,
                "boardbreaker_total": 0.0,
            }
        )
        deck_ids_by_name: dict[str, set[int]] = defaultdict(set)

        for row in rows:
            deck_name = str(row["deck_name"])
            deck_ids_by_name[deck_name].add(int(row["deck_site_id"]))
            _, component_type = self._resolve_deck_group_component(
                normalized_deck_name=deck_name.strip().lower(),
                card_name=str(row["card_name"]),
                card_archetype=row["card_archetype"],
                classification=str(row["classification"]),
                card_type=row["card_type"],
                frame_type=row["frame_type"],
                race=row["card_race"],
                effect_text=row["effect_text"],
            )
            copies_in_deck = float(row["copies_in_deck"])
            if component_type in {"main_engine", "rest_engine"}:
                deck_component_sums[deck_name]["engine_total"] += copies_in_deck
            elif component_type == "non_engine_handtrap":
                deck_component_sums[deck_name]["handtrap_total"] += copies_in_deck
            elif component_type == "non_engine_boardbreaker":
                deck_component_sums[deck_name]["boardbreaker_total"] += copies_in_deck

        component_averages: dict[str, dict[str, float]] = {}
        for deck_name in normalized_deck_names:
            deck_count = len(deck_ids_by_name.get(deck_name, set()))
            totals = deck_component_sums.get(deck_name)
            if deck_count == 0 or totals is None:
                component_averages[deck_name] = {
                    "average_engine_card_total": 0.0,
                    "average_handtrap_card_total": 0.0,
                    "average_boardbreaker_card_total": 0.0,
                }
                continue
            component_averages[deck_name] = {
                "average_engine_card_total": round(totals["engine_total"] / deck_count, 2),
                "average_handtrap_card_total": round(totals["handtrap_total"] / deck_count, 2),
                "average_boardbreaker_card_total": round(totals["boardbreaker_total"] / deck_count, 2),
            }
        return component_averages

    def _resolve_deck_group_component(
        self,
        *,
        normalized_deck_name: str,
        card_name: str,
        card_archetype: Any,
        classification: str,
        card_type: Any,
        frame_type: Any,
        race: Any,
        effect_text: Any,
    ) -> tuple[str, str]:
        component_name, component_type, _ = self._resolve_deck_group_component_and_role(
            normalized_deck_name=normalized_deck_name,
            card_name=card_name,
            card_archetype=card_archetype,
            classification=classification,
            card_type=card_type,
            frame_type=frame_type,
            race=race,
            effect_text=effect_text,
        )
        return (component_name, component_type)

    def _resolve_deck_group_component_and_role(
        self,
        *,
        normalized_deck_name: str,
        card_name: str,
        card_archetype: Any,
        classification: str,
        card_type: Any,
        frame_type: Any,
        race: Any,
        effect_text: Any,
    ) -> tuple[str, str, str | None]:
        normalized_archetype = str(card_archetype).strip().lower() if card_archetype is not None else ""
        if normalized_archetype and (
            normalized_deck_name.find(normalized_archetype) >= 0 or normalized_archetype.find(normalized_deck_name) >= 0
        ):
            return (str(card_archetype), "main_engine", None)

        if classification == "non_engine":
            role_scores = classify_non_engine_role(
                card_name=card_name,
                card_type=card_type,
                frame_type=frame_type,
                race=race,
                effect_text=effect_text,
            )
            if role_scores.role == "handtrap":
                return ("Handtraps", "non_engine_handtrap", "handtrap")
            if role_scores.role == "boardbreaker":
                return ("Boardbreaker", "non_engine_boardbreaker", "boardbreaker")
            return ("Weitere Non-Engine", "non_engine_other", role_scores.role)

        return ("Restliche Engine", "rest_engine", None)

    def _deck_group_component_rank(self, component_type: str) -> int:
        ranks = {
            "main_engine": 1,
            "non_engine_handtrap": 2,
            "non_engine_boardbreaker": 3,
            "non_engine_other": 4,
            "rest_engine": 5,
        }
        return ranks.get(component_type, 99)

    def _format_detailed_component_label(self, component_name: Any, component_type: Any) -> str | None:
        normalized_component_type = str(component_type) if component_type is not None else ""
        if normalized_component_type in {"main_engine", "rest_engine"}:
            return "Engine"
        if normalized_component_type in {
            "non_engine_handtrap",
            "non_engine_boardbreaker",
            "non_engine_other",
        }:
            return "Non-Engine"
        if normalized_component_type == "extra":
            return "Extra Deck"
        return str(component_name) if component_name is not None else None

    def _card_cost_bucket_label(self, price_eur: Any) -> str:
        if price_eur is None:
            return "Keine Preisdaten"
        normalized_price = float(price_eur)
        if normalized_price >= 10.0:
            return "Hoch"
        if normalized_price >= 3.0:
            return "Mittel"
        return "Niedrig"

    def _empty_section_role_totals(self) -> dict[str, float]:
        return {
            "total": 0.0,
            "cardmarket_cost_eur": 0.0,
            "engine": 0.0,
            "non_engine_total": 0.0,
            "handtrap": 0.0,
            "boardbreaker": 0.0,
            "non_engine_other": 0.0,
            "floodgate": 0.0,
            "protection": 0.0,
            "draw_engine": 0.0,
            "unknown_non_engine": 0.0,
        }

    def _get_deck_analysis_card_rows(
        self,
        *,
        deck_site_id: int | None = None,
        deck_name: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[sqlite3.Row]:
        if (deck_site_id is None) == (deck_name is None):
            raise ValueError("Exactly one of deck_site_id or deck_name must be provided.")

        selection_sql = "WHERE deck_site_id = ?" if deck_site_id is not None else "WHERE deck_name = ?"
        selection_value: Any = deck_site_id if deck_site_id is not None else deck_name

        return self._fetch_all(
            f"""
            {self._non_engine_classification_cte(start_date, end_date)}
            , selected_decks AS (
                SELECT deck_site_id, deck_name
                FROM filtered_decks
                {selection_sql}
            ),
            per_deck_cards AS (
                SELECT
                    sd.deck_site_id,
                    sd.deck_name,
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT)) AS card_name,
                    MAX(c.card_archetype) AS card_archetype,
                    MAX(c.card_type) AS card_type,
                    MAX(c.card_race) AS card_race,
                    MAX(c.frame_type) AS frame_type,
                    MAX(CASE WHEN c.effect_text IS NOT NULL AND LOWER(TRIM(c.effect_text)) NOT IN ('none', 'null', 'n/a', 'na') THEN c.effect_text END) AS effect_text,
                    MAX(COALESCE(cc.classification, 'engine')) AS classification,
                    SUM(dc.quantity) AS quantity,
                    SUM(dc.quantity * c.cardmarket_price_eur) AS total_cardmarket_cost_eur
                FROM deck_cards dc
                JOIN selected_decks sd ON sd.deck_site_id = dc.deck_site_id
                LEFT JOIN cards c ON c.card_passcode = dc.card_passcode
                LEFT JOIN classified_cards cc
                  ON cc.section = dc.section
                 AND cc.card_name = COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
                GROUP BY
                    sd.deck_site_id,
                    sd.deck_name,
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
            )
            SELECT
                deck_site_id,
                deck_name,
                section,
                card_name,
                card_archetype,
                card_type,
                card_race,
                frame_type,
                effect_text,
                classification,
                quantity,
                total_cardmarket_cost_eur
            FROM per_deck_cards
            ORDER BY
                deck_name ASC,
                deck_site_id ASC,
                CASE section
                    WHEN 'main' THEN 1
                    WHEN 'extra' THEN 2
                    WHEN 'side' THEN 3
                    ELSE 4
                END,
                card_name ASC
            """,
            self._non_engine_classification_parameters(start_date, end_date) + (selection_value,),
        )

    def _build_deck_analysis_totals(self, rows: list[sqlite3.Row]) -> dict[int, dict[str, Any]]:
        analyses: dict[int, dict[str, Any]] = {}
        for row in rows:
            deck_site_id = int(row["deck_site_id"])
            deck_name = str(row["deck_name"])
            section = str(row["section"])
            quantity = float(row["quantity"])
            total_cardmarket_cost_eur = (
                float(row["total_cardmarket_cost_eur"]) if row["total_cardmarket_cost_eur"] is not None else 0.0
            )
            analysis = analyses.setdefault(
                deck_site_id,
                {
                    "deck_name": deck_name,
                    "sections": {
                        "main": self._empty_section_role_totals(),
                        "extra": self._empty_section_role_totals(),
                        "side": self._empty_section_role_totals(),
                    },
                    "role_costs": {
                        "engine": 0.0,
                        "handtrap": 0.0,
                        "boardbreaker": 0.0,
                        "non_engine_other": 0.0,
                    },
                    "main_copy_counts": {
                        "one_of": 0,
                        "two_of": 0,
                        "three_of": 0,
                    },
                },
            )
            section_totals = analysis["sections"][section]
            section_totals["total"] += quantity
            section_totals["cardmarket_cost_eur"] += total_cardmarket_cost_eur

            if section == "main":
                if quantity == 1.0:
                    analysis["main_copy_counts"]["one_of"] += 1
                elif quantity == 2.0:
                    analysis["main_copy_counts"]["two_of"] += 1
                elif quantity == 3.0:
                    analysis["main_copy_counts"]["three_of"] += 1

            if section not in {"main", "side"}:
                continue

            _, component_type, role = self._resolve_deck_group_component_and_role(
                normalized_deck_name=deck_name.strip().lower(),
                card_name=str(row["card_name"]),
                card_archetype=row["card_archetype"],
                classification=str(row["classification"]),
                card_type=row["card_type"],
                frame_type=row["frame_type"],
                race=row["card_race"],
                effect_text=row["effect_text"],
            )
            if component_type in {"main_engine", "rest_engine"}:
                section_totals["engine"] += quantity
                analysis["role_costs"]["engine"] += total_cardmarket_cost_eur
                continue

            section_totals["non_engine_total"] += quantity
            if role == "handtrap":
                section_totals["handtrap"] += quantity
                analysis["role_costs"]["handtrap"] += total_cardmarket_cost_eur
            elif role == "boardbreaker":
                section_totals["boardbreaker"] += quantity
                analysis["role_costs"]["boardbreaker"] += total_cardmarket_cost_eur
            else:
                section_totals["non_engine_other"] += quantity
                analysis["role_costs"]["non_engine_other"] += total_cardmarket_cost_eur
                if role == "floodgate":
                    section_totals["floodgate"] += quantity
                elif role == "protection":
                    section_totals["protection"] += quantity
                elif role == "draw_engine":
                    section_totals["draw_engine"] += quantity
                else:
                    section_totals["unknown_non_engine"] += quantity

        return analyses

    def _calculate_deck_role_metrics_from_analysis(
        self,
        *,
        deck_site_id: int,
        deck_name: str,
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        main_totals = analysis["sections"]["main"]
        extra_totals = analysis["sections"]["extra"]
        side_totals = analysis["sections"]["side"]
        role_costs = analysis["role_costs"]

        main_total = float(main_totals["total"])
        extra_total = float(extra_totals["total"])
        side_total = float(side_totals["total"])

        def pct(numerator: float, denominator: float) -> float:
            if denominator <= 0:
                return 0.0
            return round(numerator * 100.0 / denominator, 2)

        main_cardmarket_cost_eur = round(float(main_totals["cardmarket_cost_eur"]), 2)
        extra_cardmarket_cost_eur = round(float(extra_totals["cardmarket_cost_eur"]), 2)
        side_cardmarket_cost_eur = round(float(side_totals["cardmarket_cost_eur"]), 2)

        return {
            "deck_site_id": deck_site_id,
            "deck_name": deck_name,
            "main_card_total": int(round(main_total)),
            "extra_card_total": int(round(extra_total)),
            "side_card_total": int(round(side_total)),
            "main_engine_copies": round(float(main_totals["engine"]), 2),
            "main_non_engine_copies": round(float(main_totals["non_engine_total"]), 2),
            "side_non_engine_copies": round(float(side_totals["non_engine_total"]), 2),
            "side_handtrap_copies": round(float(side_totals["handtrap"]), 2),
            "side_boardbreaker_copies": round(float(side_totals["boardbreaker"]), 2),
            "side_non_engine_other_copies": round(float(side_totals["non_engine_other"]), 2),
            "main_engine_share_pct": pct(float(main_totals["engine"]), main_total),
            "main_non_engine_share_pct": pct(float(main_totals["non_engine_total"]), main_total),
            "side_non_engine_share_pct": pct(float(side_totals["non_engine_total"]), side_total),
            "side_handtrap_share_pct": pct(float(side_totals["handtrap"]), side_total),
            "side_boardbreaker_share_pct": pct(float(side_totals["boardbreaker"]), side_total),
            "side_non_engine_other_share_pct": pct(float(side_totals["non_engine_other"]), side_total),
            "main_cardmarket_cost_eur": main_cardmarket_cost_eur,
            "extra_cardmarket_cost_eur": extra_cardmarket_cost_eur,
            "side_cardmarket_cost_eur": side_cardmarket_cost_eur,
            "main_side_cardmarket_cost_eur": round(main_cardmarket_cost_eur + side_cardmarket_cost_eur, 2),
            "engine_cardmarket_cost_eur": round(float(role_costs["engine"]), 2),
            "handtrap_cardmarket_cost_eur": round(float(role_costs["handtrap"]), 2),
            "boardbreaker_cardmarket_cost_eur": round(float(role_costs["boardbreaker"]), 2),
            "non_engine_other_cardmarket_cost_eur": round(float(role_costs["non_engine_other"]), 2),
            "main_one_of_count": int(analysis["main_copy_counts"]["one_of"]),
            "main_two_of_count": int(analysis["main_copy_counts"]["two_of"]),
            "main_three_of_count": int(analysis["main_copy_counts"]["three_of"]),
            "main_archetypal_share_pct": pct(float(main_totals["engine"]), main_total),
            "main_generic_share_pct": pct(float(main_totals["non_engine_total"]), main_total),
        }

    def _get_monthly_deck_section_role_totals(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> dict[int, dict[str, Any]]:
        rows = self._fetch_all(
            f"""
            {self._non_engine_classification_cte(start_date, end_date)}
            , per_deck_section_cards AS (
                SELECT
                    fd.deck_site_id,
                    fd.deck_name,
                    strftime('%Y-%m-01', fd.tournament_date) AS month_start,
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT)) AS card_name,
                    MAX(c.card_archetype) AS card_archetype,
                    MAX(c.card_type) AS card_type,
                    MAX(c.card_race) AS card_race,
                    MAX(c.frame_type) AS frame_type,
                    MAX(CASE WHEN c.effect_text IS NOT NULL AND LOWER(TRIM(c.effect_text)) NOT IN ('none', 'null', 'n/a', 'na') THEN c.effect_text END) AS effect_text,
                    MAX(COALESCE(cc.classification, 'engine')) AS classification,
                    SUM(dc.quantity) AS copies_in_deck
                FROM filtered_decks fd
                JOIN deck_cards dc ON dc.deck_site_id = fd.deck_site_id
                LEFT JOIN cards c ON c.card_passcode = dc.card_passcode
                LEFT JOIN classified_cards cc
                  ON cc.section = dc.section
                 AND cc.card_name = COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
                WHERE dc.section IN ('main', 'side')
                GROUP BY
                    fd.deck_site_id,
                    fd.deck_name,
                    strftime('%Y-%m-01', fd.tournament_date),
                    dc.section,
                    COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
            )
            SELECT
                deck_site_id,
                deck_name,
                month_start,
                section,
                card_name,
                card_archetype,
                card_type,
                card_race,
                frame_type,
                effect_text,
                classification,
                copies_in_deck
            FROM per_deck_section_cards
            WHERE month_start IS NOT NULL
            ORDER BY month_start ASC, deck_site_id ASC, section ASC, card_name ASC
            """,
            self._non_engine_classification_parameters(start_date, end_date),
        )
        if not rows:
            return {}

        per_deck_totals: dict[int, dict[str, Any]] = {}
        for row in rows:
            deck_site_id = int(row["deck_site_id"])
            month_start = str(row["month_start"])
            deck_name = str(row["deck_name"])
            section = str(row["section"])
            deck_totals = per_deck_totals.setdefault(
                deck_site_id,
                {
                    "month_start": month_start,
                    "deck_name": deck_name,
                    "sections": {
                        "main": self._empty_section_role_totals(),
                        "side": self._empty_section_role_totals(),
                    },
                },
            )
            section_totals = deck_totals["sections"][section]
            copies_in_deck = float(row["copies_in_deck"])
            section_totals["total"] += copies_in_deck

            _, component_type, role = self._resolve_deck_group_component_and_role(
                normalized_deck_name=deck_name.strip().lower(),
                card_name=str(row["card_name"]),
                card_archetype=row["card_archetype"],
                classification=str(row["classification"]),
                card_type=row["card_type"],
                frame_type=row["frame_type"],
                race=row["card_race"],
                effect_text=row["effect_text"],
            )
            if component_type in {"main_engine", "rest_engine"}:
                section_totals["engine"] += copies_in_deck
                continue

            section_totals["non_engine_total"] += copies_in_deck
            if role == "handtrap":
                section_totals["handtrap"] += copies_in_deck
            elif role == "boardbreaker":
                section_totals["boardbreaker"] += copies_in_deck
            else:
                section_totals["non_engine_other"] += copies_in_deck
                if role == "floodgate":
                    section_totals["floodgate"] += copies_in_deck
                elif role == "protection":
                    section_totals["protection"] += copies_in_deck
                elif role == "draw_engine":
                    section_totals["draw_engine"] += copies_in_deck
                else:
                    section_totals["unknown_non_engine"] += copies_in_deck

        return per_deck_totals

    def _get_monthly_deck_name_result_rows(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[sqlite3.Row]:
        cte_sql, cte_parameters = self._deck_summaries_with_prices_cte(start_date, end_date)
        return self._fetch_all(
            f"""
            WITH {cte_sql}
            SELECT
                strftime('%Y-%m-01', tournament_date) AS month_start,
                deck_name,
                COUNT(*) AS result_count
            FROM filtered_deck_summaries
            WHERE tournament_date IS NOT NULL
            GROUP BY strftime('%Y-%m-01', tournament_date), deck_name
            ORDER BY month_start ASC, result_count DESC, deck_name ASC
            """,
            cte_parameters,
        )

    def _fetch_all(self, query: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        if not self.database_path.exists():
            return []
        with self._connect() as connection:
            return connection.execute(query, parameters).fetchall()

    def _fetch_one(self, query: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        if not self.database_path.exists():
            return None
        with self._connect() as connection:
            return connection.execute(query, parameters).fetchone()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _deck_summaries_with_prices_cte(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> tuple[str, tuple[Any, ...]]:
        filter_sql, filter_parameters = self._date_filter_clause(
            "dsv.tournament_date",
            start_date,
            end_date,
            prefix="WHERE",
        )
        return (
            f"""
            deck_cardmarket_totals AS (
                SELECT
                    dc.deck_site_id,
                    ROUND(COALESCE(SUM(dc.quantity * c.cardmarket_price_eur), 0), 2) AS cardmarket_deck_price_eur
                FROM deck_cards dc
                LEFT JOIN cards c ON c.card_passcode = dc.card_passcode
                GROUP BY dc.deck_site_id
            ),
            deck_summaries_with_prices AS (
                SELECT
                    dsv.*,
                    COALESCE(dct.cardmarket_deck_price_eur, 0.0) AS cardmarket_deck_price_eur
                FROM dashboard_deck_summary_v dsv
                LEFT JOIN deck_cardmarket_totals dct ON dct.deck_site_id = dsv.deck_site_id
            ),
            filtered_deck_summaries AS (
                SELECT *
                FROM deck_summaries_with_prices dsv
                {filter_sql}
            )
        """,
            filter_parameters,
        )

    def _non_engine_classification_parameters(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> tuple[Any, ...]:
        return self._date_filter_parameters(start_date, end_date) + (
            NON_ENGINE_MIN_TOTAL_DECKS,
            NON_ENGINE_MIN_DECK_GROUPS,
            NON_ENGINE_MIN_GROUP_SPREAD_RATIO,
            NON_ENGINE_MAX_GROUP_SHARE,
            NON_ENGINE_MAX_ARCHETYPE_MATCH_SHARE,
            NON_ENGINE_SPLASH_MIN_TOTAL_DECKS,
            NON_ENGINE_SPLASH_MIN_DECK_GROUPS,
            NON_ENGINE_SPLASH_MAX_GROUP_SHARE,
        )

    def _non_engine_classification_cte(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> str:
        filter_sql, _ = self._date_filter_clause(
            "t.tournament_date",
            start_date,
            end_date,
            prefix="WHERE",
        )
        return f"""
            WITH filtered_decks AS (
                SELECT
                    d.*,
                    t.tournament_date
                FROM decks d
                JOIN tournaments t ON t.tournament_site_id = d.tournament_site_id
                {filter_sql}
            ),
            deck_group_totals AS (
                SELECT
                    deck_name,
                    COUNT(DISTINCT deck_site_id) AS deck_count
                FROM filtered_decks
                GROUP BY deck_name
            ),
            global_deck_totals AS (
                SELECT
                    COUNT(*) AS total_deck_groups,
                    COALESCE(SUM(deck_count), 0) AS total_decks
                FROM deck_group_totals
            ),
            card_group_usage AS (
                SELECT
                    pdc.deck_name,
                    pdc.section,
                    MIN(pdc.card_passcode) AS card_passcode,
                    pdc.card_name,
                    MAX(pdc.card_archetype) AS card_archetype,
                    COUNT(*) AS decks_with_card,
                    SUM(pdc.copies_in_deck) AS total_copies,
                    SUM(pdc.total_cardmarket_cost_eur) AS total_cardmarket_cost_eur,
                    dgt.deck_count AS deck_group_deck_count
                FROM (
                    SELECT
                        d.deck_name,
                        d.deck_site_id,
                        dc.section,
                        MIN(dc.card_passcode) AS card_passcode,
                        COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT)) AS card_name,
                        MAX(c.card_archetype) AS card_archetype,
                        SUM(dc.quantity) AS copies_in_deck,
                        SUM(dc.quantity * c.cardmarket_price_eur) AS total_cardmarket_cost_eur
                    FROM deck_cards dc
                    JOIN filtered_decks d ON d.deck_site_id = dc.deck_site_id
                    LEFT JOIN cards c ON c.card_passcode = dc.card_passcode
                    WHERE dc.section IN ('main', 'side')
                    GROUP BY
                        d.deck_name,
                        d.deck_site_id,
                        dc.section,
                        COALESCE(NULLIF(dc.card_name, ''), c.canonical_name, CAST(dc.card_passcode AS TEXT))
                ) pdc
                JOIN deck_group_totals dgt ON dgt.deck_name = pdc.deck_name
                GROUP BY
                    pdc.deck_name,
                    pdc.section,
                    pdc.card_name,
                    dgt.deck_count
            ),
            card_global_stats AS (
                SELECT
                    section,
                    MIN(card_passcode) AS card_passcode,
                    card_name,
                    MAX(card_archetype) AS card_archetype,
                    COUNT(DISTINCT deck_name) AS deck_group_count,
                    SUM(decks_with_card) AS total_decks_with_card,
                    SUM(total_copies) AS total_copies,
                    SUM(total_cardmarket_cost_eur) AS total_cardmarket_cost_eur,
                    SUM(total_copies) * 1.0 / SUM(decks_with_card) AS average_copies_when_present
                FROM card_group_usage
                GROUP BY section, card_name
            ),
            card_group_concentration AS (
                SELECT
                    cgu.section,
                    cgu.card_name,
                    MAX(cgu.decks_with_card * 1.0 / cgs.total_decks_with_card) AS max_group_share,
                    MAX(cgu.decks_with_card * 1.0 / cgu.deck_group_deck_count) AS max_group_inclusion_rate,
                    SUM(
                        CASE
                            WHEN cgu.card_archetype IS NOT NULL
                                 AND LENGTH(TRIM(cgu.card_archetype)) > 0
                                 AND (
                                     LOWER(cgu.deck_name) LIKE '%' || LOWER(cgu.card_archetype) || '%'
                                     OR LOWER(cgu.card_archetype) LIKE '%' || LOWER(cgu.deck_name) || '%'
                                 )
                            THEN cgu.decks_with_card
                            ELSE 0
                        END
                    ) * 1.0 / cgs.total_decks_with_card AS archetype_match_share
                FROM card_group_usage cgu
                JOIN card_global_stats cgs
                  ON cgs.section = cgu.section
                 AND cgs.card_name = cgu.card_name
                GROUP BY cgu.section, cgu.card_name
            ),
            classified_cards AS (
                SELECT
                    cgs.section,
                    cgs.card_passcode,
                    cgs.card_name,
                    cgs.card_archetype,
                    cgs.deck_group_count,
                    cgs.total_decks_with_card,
                    cgs.total_copies,
                    cgs.total_copies * 1.0 / gdt.total_decks AS average_copies_per_deck,
                    cgs.average_copies_when_present,
                    cgs.total_cardmarket_cost_eur * 1.0 / cgs.total_copies AS average_cardmarket_price_eur,
                    gdt.total_deck_groups,
                    gdt.total_decks,
                    cgs.deck_group_count * 1.0 / gdt.total_deck_groups AS deck_group_spread_ratio,
                    cgs.total_decks_with_card * 1.0 / gdt.total_decks AS global_inclusion_rate,
                    cgc.max_group_share,
                    cgc.max_group_inclusion_rate,
                    COALESCE(cgc.archetype_match_share, 0.0) AS archetype_match_share,
                    CASE
                        WHEN cgs.total_decks_with_card >= ?
                             AND cgs.deck_group_count >= ?
                             AND cgs.deck_group_count * 1.0 / gdt.total_deck_groups >= ?
                             AND cgc.max_group_share <= ?
                            AND COALESCE(cgc.archetype_match_share, 0.0) <= ?
                        THEN 'non_engine'
                        WHEN cgs.total_decks_with_card >= ?
                             AND cgs.deck_group_count >= ?
                             AND cgc.max_group_share <= ?
                            AND COALESCE(cgc.archetype_match_share, 0.0) < 0.9
                        THEN 'candidate_splash'
                        ELSE 'engine'
                    END AS classification
                FROM card_global_stats cgs
                JOIN card_group_concentration cgc
                  ON cgc.section = cgs.section
                                 AND cgc.card_name = cgs.card_name
                CROSS JOIN global_deck_totals gdt
                WHERE gdt.total_deck_groups > 0
                  AND gdt.total_decks > 0
            )
        """

    def _date_filter_parameters(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> tuple[Any, ...]:
        parameters: list[Any] = []
        normalized_start = self._normalize_date_value(start_date)
        normalized_end = self._normalize_date_value(end_date)
        if normalized_start is not None:
            parameters.append(normalized_start)
        if normalized_end is not None:
            parameters.append(normalized_end)
        return tuple(parameters)

    def _date_filter_clause(
        self,
        column_name: str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        *,
        prefix: str = "WHERE",
    ) -> tuple[str, tuple[Any, ...]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        normalized_start = self._normalize_date_value(start_date)
        normalized_end = self._normalize_date_value(end_date)
        if normalized_start is not None:
            clauses.append(f"{column_name} >= ?")
            parameters.append(normalized_start)
        if normalized_end is not None:
            clauses.append(f"{column_name} <= ?")
            parameters.append(normalized_end)
        if not clauses:
            return "", ()
        return f"{prefix} " + " AND ".join(clauses), tuple(parameters)

    def _normalize_date_value(self, value: date | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, date):
            return value.isoformat()
        normalized = str(value).strip()
        return normalized or None


def resolve_dashboard_db_path(default_path: str | Path = DEFAULT_DATABASE_PATH) -> Path:
    default = Path(default_path)
    argv = sys.argv[1:]
    for index, value in enumerate(argv):
        if value == "--db-path" and index + 1 < len(argv):
            return Path(argv[index + 1])
    return default