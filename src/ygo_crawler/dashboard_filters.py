from __future__ import annotations

from datetime import date

import streamlit as st

from .dashboard_cache import load_available_date_range
from .dashboard_queries import DashboardRepository


def render_dashboard_date_filter(repository: DashboardRepository) -> tuple[date | None, date | None]:
    st.sidebar.header("Zeitraum")

    available_range = load_available_date_range(repository)
    if available_range is None:
        st.sidebar.info("Noch kein Datumsbereich verfuegbar.")
        return None, None

    min_date, max_date = available_range
    start_key = "dashboard_start_date"
    end_key = "dashboard_end_date"

    current_start = _initialize_clamped_date_state(start_key, min_date, min_date, max_date)
    current_end = _initialize_clamped_date_state(end_key, max_date, min_date, max_date)
    if current_start > current_end:
        current_start, current_end = current_end, current_start
        st.session_state[start_key] = current_start
        st.session_state[end_key] = current_end

    start_date = st.sidebar.date_input(
        "Von",
        min_value=min_date,
        max_value=max_date,
        key=start_key,
    )
    end_date = st.sidebar.date_input(
        "Bis",
        min_value=min_date,
        max_value=max_date,
        key=end_key,
    )

    if start_date > end_date:
        start_date, end_date = end_date, start_date
        st.session_state[start_key] = start_date
        st.session_state[end_key] = end_date

    st.sidebar.caption(
        f"Verfuegbar: {min_date.strftime('%d.%m.%Y')} bis {max_date.strftime('%d.%m.%Y')}"
    )
    return start_date, end_date


def _clamp_date(value: object, min_date: date, max_date: date) -> date:
    if isinstance(value, date):
        candidate = value
    else:
        try:
            candidate = date.fromisoformat(str(value))
        except ValueError:
            return min_date
    if candidate < min_date:
        return min_date
    if candidate > max_date:
        return max_date
    return candidate


def _initialize_clamped_date_state(key: str, fallback: date, min_date: date, max_date: date) -> date:
    candidate = _clamp_date(st.session_state.get(key, fallback), min_date, max_date)
    if st.session_state.get(key) != candidate:
        st.session_state[key] = candidate
    return candidate
