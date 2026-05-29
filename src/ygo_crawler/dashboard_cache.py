from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import streamlit as st

from .dashboard_queries import DashboardRepository


WARMUP_STATE_KEY = "dashboard_cache_warmup_key"


def get_dashboard_data_signature(database_path: str | Path) -> tuple[str, int | None, int | None]:
    normalized_path = _normalize_database_path(database_path)
    try:
        stat_result = Path(normalized_path).stat()
    except OSError:
        return normalized_path, None, None
    return normalized_path, stat_result.st_mtime_ns, stat_result.st_size


def normalize_dashboard_date_value(value: date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    normalized = str(value).strip()
    return normalized or None


def load_available_date_range(repository: DashboardRepository) -> tuple[date, date] | None:
    database_path = _normalize_database_path(repository.database_path)
    database_signature = get_dashboard_data_signature(database_path)
    return _load_available_date_range_cached(database_path, database_signature)


def load_dashboard_home_page_data(
    repository: DashboardRepository,
    start_date: date | str | None,
    end_date: date | str | None,
    *,
    recent_limit: int = 15,
    top_limit: int = 15,
) -> dict[str, Any]:
    database_path, database_signature, normalized_start_date, normalized_end_date = _build_cache_context(
        repository,
        start_date,
        end_date,
    )
    return _load_dashboard_home_page_data_cached(
        database_path,
        database_signature,
        normalized_start_date,
        normalized_end_date,
        recent_limit,
        top_limit,
    )


def load_deck_summaries(
    repository: DashboardRepository,
    *,
    limit: int,
    start_date: date | str | None,
    end_date: date | str | None,
) -> list[dict[str, Any]]:
    database_path, database_signature, normalized_start_date, normalized_end_date = _build_cache_context(
        repository,
        start_date,
        end_date,
    )
    return _load_deck_summaries_cached(
        database_path,
        database_signature,
        limit,
        normalized_start_date,
        normalized_end_date,
    )


def load_deck_name_aggregates(
    repository: DashboardRepository,
    *,
    limit: int,
    start_date: date | str | None,
    end_date: date | str | None,
) -> list[dict[str, Any]]:
    database_path, database_signature, normalized_start_date, normalized_end_date = _build_cache_context(
        repository,
        start_date,
        end_date,
    )
    return _load_deck_name_aggregates_cached(
        database_path,
        database_signature,
        limit,
        normalized_start_date,
        normalized_end_date,
    )


def load_deck_name_aggregates_extended(
    repository: DashboardRepository,
    *,
    limit: int,
    start_date: date | str | None,
    end_date: date | str | None,
) -> list[dict[str, Any]]:
    database_path, database_signature, normalized_start_date, normalized_end_date = _build_cache_context(
        repository,
        start_date,
        end_date,
    )
    return _load_deck_name_aggregates_extended_cached(
        database_path,
        database_signature,
        limit,
        normalized_start_date,
        normalized_end_date,
    )


def load_aggregate_plot_data(
    repository: DashboardRepository,
    *,
    ranked_deck_names: tuple[str, ...],
    minimum_deck_count: int,
    profile_top_n: int,
    sort_field: str,
    start_date: date | str | None,
    end_date: date | str | None,
) -> dict[str, Any]:
    database_path, database_signature, normalized_start_date, normalized_end_date = _build_cache_context(
        repository,
        start_date,
        end_date,
    )
    return _load_aggregate_plot_data_cached(
        database_path,
        database_signature,
        ranked_deck_names,
        minimum_deck_count,
        profile_top_n,
        sort_field,
        normalized_start_date,
        normalized_end_date,
    )


def load_selected_deck_data(
    repository: DashboardRepository,
    *,
    selected_deck_id: int,
    start_date: date | str | None,
    end_date: date | str | None,
) -> dict[str, Any]:
    database_path, database_signature, normalized_start_date, normalized_end_date = _build_cache_context(
        repository,
        start_date,
        end_date,
    )
    return _load_selected_deck_data_cached(
        database_path,
        database_signature,
        selected_deck_id,
        normalized_start_date,
        normalized_end_date,
    )


def load_group_page_data(
    repository: DashboardRepository,
    *,
    selected_deck_name: str,
    start_date: date | str | None,
    end_date: date | str | None,
) -> dict[str, Any]:
    database_path, database_signature, normalized_start_date, normalized_end_date = _build_cache_context(
        repository,
        start_date,
        end_date,
    )
    return _load_group_page_data_cached(
        database_path,
        database_signature,
        selected_deck_name,
        normalized_start_date,
        normalized_end_date,
    )


def load_non_engine_page_bundle(
    repository: DashboardRepository,
    *,
    start_date: date | str | None,
    end_date: date | str | None,
) -> dict[str, Any]:
    database_path, database_signature, normalized_start_date, normalized_end_date = _build_cache_context(
        repository,
        start_date,
        end_date,
    )
    return _load_non_engine_page_bundle_cached(
        database_path,
        database_signature,
        normalized_start_date,
        normalized_end_date,
    )


def load_longterm_page_data(
    repository: DashboardRepository,
    *,
    start_date: date | str | None,
    end_date: date | str | None,
) -> dict[str, Any]:
    database_path, database_signature, normalized_start_date, normalized_end_date = _build_cache_context(
        repository,
        start_date,
        end_date,
    )
    return _load_longterm_page_data_cached(
        database_path,
        database_signature,
        normalized_start_date,
        normalized_end_date,
    )


def warm_dashboard_global_caches(
    repository: DashboardRepository,
    *,
    start_date: date | str | None,
    end_date: date | str | None,
) -> None:
    cache_context = _build_cache_context(repository, start_date, end_date)
    warmup_key = (cache_context[1], cache_context[2], cache_context[3])
    if st.session_state.get(WARMUP_STATE_KEY) == warmup_key:
        return

    load_deck_summaries(
        repository,
        limit=2000,
        start_date=start_date,
        end_date=end_date,
    )
    load_deck_name_aggregates_extended(
        repository,
        limit=1000,
        start_date=start_date,
        end_date=end_date,
    )
    load_non_engine_page_bundle(
        repository,
        start_date=start_date,
        end_date=end_date,
    )
    load_longterm_page_data(
        repository,
        start_date=start_date,
        end_date=end_date,
    )
    st.session_state[WARMUP_STATE_KEY] = warmup_key


def _build_cache_context(
    repository: DashboardRepository,
    start_date: date | str | None,
    end_date: date | str | None,
) -> tuple[str, tuple[str, int | None, int | None], str | None, str | None]:
    database_path = _normalize_database_path(repository.database_path)
    database_signature = get_dashboard_data_signature(database_path)
    return (
        database_path,
        database_signature,
        normalize_dashboard_date_value(start_date),
        normalize_dashboard_date_value(end_date),
    )


def _normalize_database_path(database_path: str | Path) -> str:
    return str(Path(database_path).expanduser().resolve())


@st.cache_data(show_spinner=False, max_entries=16)
def _load_available_date_range_cached(
    database_path: str,
    database_signature: tuple[str, int | None, int | None],
) -> tuple[date, date] | None:
    if database_signature[1] is None:
        return None
    return DashboardRepository(database_path).get_available_date_range()


@st.cache_data(show_spinner=False, max_entries=32)
def _load_dashboard_home_page_data_cached(
    database_path: str,
    database_signature: tuple[str, int | None, int | None],
    start_date: str | None,
    end_date: str | None,
    recent_limit: int,
    top_limit: int,
) -> dict[str, Any]:
    if database_signature[1] is None:
        return {
            "kpis": None,
            "database_summary": None,
            "aggregate_rows": [],
            "deck_rows": [],
            "tournaments": [],
            "skip_summary": [],
            "skipped_sources": [],
        }

    repository = DashboardRepository(database_path)
    deck_rows = repository.list_deck_summaries(limit=recent_limit, start_date=start_date, end_date=end_date)
    page_data: dict[str, Any] = {
        "kpis": repository.get_kpis(start_date, end_date),
        "database_summary": repository.get_database_summary(start_date, end_date),
        "aggregate_rows": repository.list_deck_name_aggregates(limit=top_limit, start_date=start_date, end_date=end_date),
        "deck_rows": deck_rows,
        "tournaments": [],
        "skip_summary": [],
        "skipped_sources": [],
    }
    if deck_rows:
        return page_data

    page_data["tournaments"] = repository.list_tournaments(limit=10, start_date=start_date, end_date=end_date)
    page_data["skip_summary"] = repository.list_skip_reason_summary()
    page_data["skipped_sources"] = repository.list_skipped_sources(limit=20)
    return page_data


@st.cache_data(show_spinner=False, max_entries=32)
def _load_deck_summaries_cached(
    database_path: str,
    database_signature: tuple[str, int | None, int | None],
    limit: int,
    start_date: str | None,
    end_date: str | None,
) -> list[dict[str, Any]]:
    if database_signature[1] is None:
        return []
    return DashboardRepository(database_path).list_deck_summaries(
        limit=limit,
        start_date=start_date,
        end_date=end_date,
    )


@st.cache_data(show_spinner=False, max_entries=32)
def _load_deck_name_aggregates_cached(
    database_path: str,
    database_signature: tuple[str, int | None, int | None],
    limit: int,
    start_date: str | None,
    end_date: str | None,
) -> list[dict[str, Any]]:
    if database_signature[1] is None:
        return []
    return DashboardRepository(database_path).list_deck_name_aggregates(
        limit=limit,
        start_date=start_date,
        end_date=end_date,
    )


@st.cache_data(show_spinner=False, max_entries=32)
def _load_deck_name_aggregates_extended_cached(
    database_path: str,
    database_signature: tuple[str, int | None, int | None],
    limit: int,
    start_date: str | None,
    end_date: str | None,
) -> list[dict[str, Any]]:
    if database_signature[1] is None:
        return []
    return DashboardRepository(database_path).list_deck_name_aggregates_extended(
        limit=limit,
        start_date=start_date,
        end_date=end_date,
    )


@st.cache_data(show_spinner=False, max_entries=64)
def _load_aggregate_plot_data_cached(
    database_path: str,
    database_signature: tuple[str, int | None, int | None],
    ranked_deck_names: tuple[str, ...],
    minimum_deck_count: int,
    profile_top_n: int,
    sort_field: str,
    start_date: str | None,
    end_date: str | None,
) -> dict[str, Any]:
    if database_signature[1] is None:
        return {
            "scatter_rows": [],
            "cost_rows": [],
            "profile_rows": [],
            "trend_rows": [],
            "table_trend_rows": [],
        }

    repository = DashboardRepository(database_path)
    return {
        "scatter_rows": repository.get_deck_name_scatter_rows(
            limit=500,
            min_deck_count=minimum_deck_count,
            start_date=start_date,
            end_date=end_date,
        ),
        "cost_rows": repository.get_deck_name_cost_performance_rows(
            limit=500,
            min_deck_count=minimum_deck_count,
            start_date=start_date,
            end_date=end_date,
        ),
        "profile_rows": repository.get_deck_name_profile_rows(
            limit=profile_top_n,
            sort_field=sort_field,
            min_deck_count=minimum_deck_count,
            start_date=start_date,
            end_date=end_date,
        ),
        "trend_rows": repository.get_deck_name_trend_rows(
            limit=profile_top_n,
            sort_field=sort_field,
            min_deck_count=minimum_deck_count,
            start_date=start_date,
            end_date=end_date,
        ),
        "table_trend_rows": repository.get_deck_name_trend_rows(
            deck_names=list(ranked_deck_names),
            min_deck_count=minimum_deck_count,
            start_date=start_date,
            end_date=end_date,
        ),
    }


@st.cache_data(show_spinner=False, max_entries=128)
def _load_selected_deck_data_cached(
    database_path: str,
    database_signature: tuple[str, int | None, int | None],
    selected_deck_id: int,
    start_date: str | None,
    end_date: str | None,
) -> dict[str, Any]:
    if database_signature[1] is None:
        return {}

    repository = DashboardRepository(database_path)
    return {
        "selected_deck": repository.get_deck_summary_extended(selected_deck_id, start_date, end_date),
        "role_metrics": repository.get_deck_role_metrics(selected_deck_id, start_date, end_date),
        "deck_section_composition": repository.get_deck_section_composition(selected_deck_id, start_date, end_date),
        "deck_vs_group_comparison": repository.get_deck_vs_group_section_comparison(selected_deck_id, start_date, end_date),
        "role_cost_distribution": repository.get_deck_role_cost_distribution(selected_deck_id, start_date, end_date),
        "copy_count_histogram": repository.get_deck_copy_count_histogram(selected_deck_id, start_date, end_date),
        "deck_heatmap_rows": repository.get_deck_section_heatmap_rows(selected_deck_id, start_date, end_date),
        "deck_cards": repository.get_deck_cards_detailed(selected_deck_id, start_date, end_date),
    }


@st.cache_data(show_spinner=False, max_entries=96)
def _load_group_page_data_cached(
    database_path: str,
    database_signature: tuple[str, int | None, int | None],
    selected_deck_name: str,
    start_date: str | None,
    end_date: str | None,
) -> dict[str, Any]:
    if database_signature[1] is None:
        return {}

    repository = DashboardRepository(database_path)
    return {
        "selected_aggregate": repository.get_deck_name_aggregate_extended(selected_deck_name, start_date, end_date),
        "group_role_benchmarks": repository.get_deck_group_role_benchmarks(selected_deck_name, start_date, end_date),
        "deck_section_composition": repository.get_deck_group_section_composition(selected_deck_name, start_date, end_date),
        "aggregated_cards": repository.get_aggregated_deck_cards(selected_deck_name, start_date, end_date),
        "deck_group_trend_rows": repository.get_deck_name_trend_rows(
            deck_names=[selected_deck_name],
            start_date=start_date,
            end_date=end_date,
        ),
        "group_non_engine_cards": repository.list_non_engine_cards_for_deck_group(
            selected_deck_name,
            classification="non_engine",
            limit=250,
            start_date=start_date,
            end_date=end_date,
        ),
        "group_candidate_splash_cards": repository.list_non_engine_cards_for_deck_group(
            selected_deck_name,
            classification="candidate_splash",
            limit=250,
            start_date=start_date,
            end_date=end_date,
        ),
        "deck_instances": repository.list_deck_instances_for_name(
            selected_deck_name,
            limit=250,
            start_date=start_date,
            end_date=end_date,
        ),
    }


@st.cache_data(show_spinner=False, max_entries=32)
def _load_non_engine_page_bundle_cached(
    database_path: str,
    database_signature: tuple[str, int | None, int | None],
    start_date: str | None,
    end_date: str | None,
) -> dict[str, Any]:
    if database_signature[1] is None:
        return {
            "global_non_engine_cards": [],
            "global_candidate_splash_cards": [],
            "monthly_main_share_rows": [],
            "monthly_side_share_rows": [],
            "monthly_subrole_rows": [],
            "monthly_section_balance_rows": [],
        }

    repository = DashboardRepository(database_path)
    return {
        "global_non_engine_cards": repository.list_non_engine_cards(
            classification="non_engine",
            limit=500,
            start_date=start_date,
            end_date=end_date,
        ),
        "global_candidate_splash_cards": repository.list_non_engine_cards(
            classification="candidate_splash",
            limit=500,
            start_date=start_date,
            end_date=end_date,
        ),
        "monthly_main_share_rows": repository.get_monthly_main_deck_share_trends(start_date=start_date, end_date=end_date),
        "monthly_side_share_rows": repository.get_monthly_side_deck_share_trends(start_date=start_date, end_date=end_date),
        "monthly_subrole_rows": repository.get_monthly_non_engine_subrole_trends(start_date=start_date, end_date=end_date),
        "monthly_section_balance_rows": repository.get_monthly_section_engine_vs_non_engine_trends(
            start_date=start_date,
            end_date=end_date,
        ),
    }


@st.cache_data(show_spinner=False, max_entries=32)
def _load_longterm_page_data_cached(
    database_path: str,
    database_signature: tuple[str, int | None, int | None],
    start_date: str | None,
    end_date: str | None,
) -> dict[str, Any]:
    if database_signature[1] is None:
        return {
            "trend_rows": [],
            "side_trend_rows": [],
            "subrole_trend_rows": [],
            "section_trend_rows": [],
            "new_deck_name_rows": [],
            "concentration_rows": [],
            "top_deck_cost_rows": [],
        }

    repository = DashboardRepository(database_path)
    return {
        "trend_rows": repository.get_monthly_main_deck_share_trends(start_date=start_date, end_date=end_date),
        "side_trend_rows": repository.get_monthly_side_deck_share_trends(start_date=start_date, end_date=end_date),
        "subrole_trend_rows": repository.get_monthly_non_engine_subrole_trends(start_date=start_date, end_date=end_date),
        "section_trend_rows": repository.get_monthly_section_engine_vs_non_engine_trends(start_date=start_date, end_date=end_date),
        "new_deck_name_rows": repository.get_monthly_new_deck_name_share_trends(start_date=start_date, end_date=end_date),
        "concentration_rows": repository.get_monthly_deck_result_concentration_trends(start_date=start_date, end_date=end_date),
        "top_deck_cost_rows": repository.get_monthly_top_deck_cost_trends(start_date=start_date, end_date=end_date),
    }