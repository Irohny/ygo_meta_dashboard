from __future__ import annotations

from typing import Any

import streamlit as st

from ygo_crawler.dashboard_cache import (
    load_deck_group_card_options,
    load_deck_group_starter,
    load_deck_name_aggregates_extended,
    load_search_cards,
    load_underused_cards_for_deck_group,
)
from ygo_crawler.dashboard_filters import render_dashboard_date_filter
from ygo_crawler.dashboard_queries import DashboardRepository, resolve_dashboard_db_path

DECK_NAME_STATE_KEY = "deckbuilder_deck_name"
DECK_NAME_PENDING_STATE_KEY = "deckbuilder_deck_name_pending"
SEARCH_QUERY_STATE_KEY = "deckbuilder_search_query"
SEARCH_LIMIT_STATE_KEY = "deckbuilder_search_limit"
SEARCH_TARGET_SECTION_STATE_KEY = "deckbuilder_search_target_section"
SEARCH_MODE_STATE_KEY = "deckbuilder_search_mode"
DECK_GROUP_STATE_KEY = "deckbuilder_deck_group"
DECK_INSTANCE_LINK_STATE_KEY = "deckbuilder_deck_instance_link_id"
UNDERUSED_LIMIT_STATE_KEY = "deckbuilder_underused_limit"
DRAFT_STATE_KEY = "deckbuilder_draft"

_GRID_COLS = 10
_CARD_IMAGE_WIDTH = 72

_SECTION_LIMITS: dict[str, tuple[int | None, int]] = {
    "main": (40, 60),
    "extra": (None, 15),
    "side": (None, 15),
}


def _new_empty_draft() -> dict[str, list[dict[str, Any]]]:
    return {"main": [], "extra": [], "side": []}


def _ensure_state() -> None:
    if DRAFT_STATE_KEY not in st.session_state:
        st.session_state[DRAFT_STATE_KEY] = _new_empty_draft()
    st.session_state.setdefault(DECK_NAME_STATE_KEY, "Mein Deck")
    st.session_state.setdefault(SEARCH_QUERY_STATE_KEY, "")
    st.session_state.setdefault(SEARCH_LIMIT_STATE_KEY, 30)
    st.session_state.setdefault(SEARCH_TARGET_SECTION_STATE_KEY, "main")
    st.session_state.setdefault(SEARCH_MODE_STATE_KEY, "Namenssuche")
    st.session_state.setdefault(DECK_GROUP_STATE_KEY, None)
    st.session_state.setdefault(DECK_INSTANCE_LINK_STATE_KEY, None)
    st.session_state.setdefault(UNDERUSED_LIMIT_STATE_KEY, 25)


def _section_label(section: str) -> str:
    return {
        "main": "Main Deck",
        "extra": "Extra Deck",
        "side": "Side Deck",
    }.get(section, section)


def _draft_sections() -> tuple[str, str, str]:
    return ("main", "extra", "side")


def _total_cards(section_rows: list[dict[str, Any]]) -> int:
    return sum(int(row.get("quantity") or 0) for row in section_rows)


def _all_section_totals(draft: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {
        section: _total_cards(draft.get(section, [])) for section in _draft_sections()
    }


def _upsert_card(
    draft: dict[str, list[dict[str, Any]]],
    *,
    section: str,
    card_name: str,
    card_passcode: int | None,
    image_url_small: str | None,
    quantity_delta: int,
    card_type: str | None = None,
    card_archetype: str | None = None,
    inclusion_rate_pct: float | None = None,
    average_copies_when_present: float | None = None,
    decks_with_card: int | None = None,
    average_copies_per_deck: float | None = None,
) -> None:
    if quantity_delta == 0:
        return
    rows = draft.setdefault(section, [])
    for row in rows:
        if str(row.get("card_name")) == card_name:
            new_quantity = int(row.get("quantity") or 0) + quantity_delta
            if new_quantity <= 0:
                rows.remove(row)
            else:
                row["quantity"] = min(3, new_quantity)
                # Enrich missing metadata if now available
                if card_type is not None and row.get("card_type") is None:
                    row["card_type"] = card_type
                if card_archetype is not None and row.get("card_archetype") is None:
                    row["card_archetype"] = card_archetype
                if image_url_small is not None and row.get("image_url_small") is None:
                    row["image_url_small"] = image_url_small
            return

    if quantity_delta <= 0:
        return
    rows.append(
        {
            "card_name": card_name,
            "card_passcode": card_passcode,
            "quantity": min(3, quantity_delta),
            "image_url_small": image_url_small,
            "card_type": card_type,
            "card_archetype": card_archetype,
            "inclusion_rate_pct": inclusion_rate_pct,
            "average_copies_when_present": average_copies_when_present,
            "decks_with_card": decks_with_card,
            "average_copies_per_deck": average_copies_per_deck,
        }
    )


def _section_is_full(draft: dict[str, list[dict[str, Any]]], section: str) -> bool:
    _, cap = _SECTION_LIMITS.get(section, (None, 9999))
    return _total_cards(draft.get(section, [])) >= cap


def _normalize_group_options(rows: list[dict[str, Any]]) -> list[str]:
    names = [str(row.get("deck_name") or "").strip() for row in rows]
    return sorted({name for name in names if name})


def _resolve_repository() -> DashboardRepository:
    return DashboardRepository(resolve_dashboard_db_path())


def _deck_instance_link_label(row: dict[str, Any]) -> str:
    return " | ".join(
        [
            str(row.get("tournament_date") or "-"),
            f"Platz {row.get('placement') or '-'}",
            str(row.get("tournament_name") or "-"),
            str(row.get("player_name") or "-"),
        ]
    )


def _top_level_card_group(card_type: str | None, *, section: str) -> str:
    normalized = (card_type or "").strip().lower()
    if "monster" in normalized:
        return "Monster"
    if "spell" in normalized or "zauber" in normalized:
        return "Zauber"
    if "trap" in normalized or "falle" in normalized:
        return "Falle"
    if section == "extra":
        # Extra cards are effectively monster cards; fallback avoids noisy "Sonstige" grouping.
        return "Monster"
    return "Sonstige"


def _normalize_sort_value(value: Any) -> str:
    return str(value or "").strip().casefold()


# ---------------------------------------------------------------------------
# Visual card grid for one deck section
# ---------------------------------------------------------------------------


_TYPE_ORDER: dict[str, int] = {"Monster": 0, "Zauber": 1, "Falle": 2, "Sonstige": 3}


def _card_sort_key(
    row: dict[str, Any],
    section: str,
    archetype_rank: dict[tuple[str, str], int],
) -> tuple[int, int, str, str]:
    top = _top_level_card_group(
        row.get("card_type") if isinstance(row.get("card_type"), str) else None,
        section=section,
    )
    archetype = str(row.get("card_archetype") or "")
    return (
        _TYPE_ORDER.get(top, 99),
        archetype_rank.get((top, archetype), 9999),
        _normalize_sort_value(archetype),
        _normalize_sort_value(row.get("card_name")),
    )


def _render_section_grid(
    section: str,
    draft: dict[str, list[dict[str, Any]]],
    *,
    key_prefix: str,
) -> None:
    # Flatten and sort: Monster→Zauber→Falle→Sonstige,
    # then archetype by descending card count, then card name.
    all_rows = list(draft.get(section, []))

    # Step 1: count total cards per (top_group, archetype)
    archetype_counts: dict[tuple[str, str], int] = {}
    for r in all_rows:
        top = _top_level_card_group(
            r.get("card_type") if isinstance(r.get("card_type"), str) else None,
            section=section,
        )
        arch = str(r.get("card_archetype") or "")
        key = (top, arch)
        archetype_counts[key] = archetype_counts.get(key, 0) + int(
            r.get("quantity") or 1
        )

    # Step 2: rank archetypes within each top_group.
    # Named archetypes first (descending card count, then alpha);
    # cards without archetype always rank last within their top group.
    archetype_rank: dict[tuple[str, str], int] = {}

    for top in _TYPE_ORDER:
        group_items = sorted(
            ((k, v) for k, v in archetype_counts.items() if k[0] == top),
            key=lambda x: (
                x[0][1] == "",  # unnamed → last
                -x[1],  # descending card count
                _normalize_sort_value(x[0][1]),  # then alphabetical
            ),
        )
        for rank, (k, _) in enumerate(group_items):
            archetype_rank[k] = rank

    sorted_rows = sorted(
        all_rows,
        key=lambda r: _card_sort_key(r, section, archetype_rank),
    )
    total = _total_cards(sorted_rows)

    # --- Section header with inline validation badge ---
    if section == "main":
        if total < 40:
            badge = f":red[{total} / 60]  *(min. 40)*"
        elif total > 60:
            badge = f":red[{total} / 60]  *(max. 60)*"
        else:
            badge = f":green[{total} / 60]"
    else:
        badge = f":red[{total} / 15]" if total > 15 else f":green[{total} / 15]"

    ctrl_l, ctrl_r = st.columns([5, 1])
    ctrl_l.markdown(f"#### {_section_label(section)} &nbsp; {badge}")
    if ctrl_r.button(
        "Leeren",
        key=f"{key_prefix}_clear_{section}",
        use_container_width=True,
    ):
        draft[section] = []
        st.rerun()

    if not sorted_rows:
        st.caption("Leer – Karten über die Suche rechts hinzufügen.")
        return

    for chunk_start in range(0, len(sorted_rows), _GRID_COLS):
        chunk = sorted_rows[chunk_start : chunk_start + _GRID_COLS]

        cols = st.columns(_GRID_COLS)
        for j, row in enumerate(chunk):
            name = str(row.get("card_name") or "")
            qty = int(row.get("quantity") or 0)
            img = row.get("image_url_small")
            key_base = f"{key_prefix}_{section}_{chunk_start}_{j}"
            with cols[j]:
                with st.container(border=True):
                    if img:
                        st.image(img, use_container_width=True)
                    else:
                        short = (name[:12] + "…") if len(name) > 13 else name
                        st.markdown(
                            '<div style="'
                            "width:100%;"
                            "height:100px;"
                            "background:#2a2a2a;"
                            "border:1px solid #555;"
                            "border-radius:4px;"
                            "display:flex;"
                            "align-items:center;"
                            "justify-content:center;"
                            "text-align:center;"
                            "font-size:10px;"
                            "color:#ccc;"
                            "padding:4px;"
                            f'">🃏 {short}</div>',
                            unsafe_allow_html=True,
                        )
                    st.caption(f"**{qty}×**")
                    b_inc, b_dec, b_rm = st.columns(3)
                    if b_inc.button(
                        "+",
                        key=f"inc_{key_base}",
                        disabled=_section_is_full(draft, section) or qty >= 3,
                        use_container_width=True,
                        help=f"{name} +1",
                    ):
                        _upsert_card(
                            draft,
                            section=section,
                            card_name=name,
                            card_passcode=row.get("card_passcode"),
                            image_url_small=row.get("image_url_small"),
                            quantity_delta=1,
                            card_type=(
                                row.get("card_type")
                                if isinstance(row.get("card_type"), str)
                                else None
                            ),
                            card_archetype=(
                                row.get("card_archetype")
                                if isinstance(row.get("card_archetype"), str)
                                else None
                            ),
                            inclusion_rate_pct=row.get("inclusion_rate_pct"),
                            average_copies_when_present=row.get(
                                "average_copies_when_present"
                            ),
                            decks_with_card=row.get("decks_with_card"),
                            average_copies_per_deck=row.get("average_copies_per_deck"),
                        )
                        st.rerun()
                    if b_dec.button(
                        "-",
                        key=f"dec_{key_base}",
                        disabled=qty <= 1,
                        use_container_width=True,
                        help=f"{name} -1",
                    ):
                        _upsert_card(
                            draft,
                            section=section,
                            card_name=name,
                            card_passcode=row.get("card_passcode"),
                            image_url_small=row.get("image_url_small"),
                            quantity_delta=-1,
                        )
                        st.rerun()
                    if b_rm.button(
                        "×",
                        key=f"rm_{key_base}",
                        use_container_width=True,
                        help=f"{name} entfernen",
                    ):
                        _upsert_card(
                            draft,
                            section=section,
                            card_name=name,
                            card_passcode=row.get("card_passcode"),
                            image_url_small=row.get("image_url_small"),
                            quantity_delta=-qty,
                        )
                        st.rerun()


# ---------------------------------------------------------------------------
# Right panel: search
# ---------------------------------------------------------------------------


def _render_search_panel(
    repository: DashboardRepository,
    draft: dict[str, list[dict[str, Any]]],
    start_date: Any,
    end_date: Any,
) -> None:
    with st.container(border=True):

        def _picker_name(row: dict[str, Any]) -> str:
            return str(row.get("card_name") or row.get("Karte") or "")

        def _picker_type(row: dict[str, Any]) -> str | None:
            value = row.get("card_type") or row.get("Kartentyp")
            return value if isinstance(value, str) else None

        def _picker_archetype(row: dict[str, Any]) -> str | None:
            value = row.get("card_archetype") or row.get("Archetyp")
            return value if isinstance(value, str) else None

        def _render_picker_cards(
            rows: list[dict[str, Any]],
            *,
            target_section: str,
            key_prefix: str,
            show_source_hint: str | None = None,
        ) -> None:
            if show_source_hint:
                st.caption(show_source_hint)
            if not rows:
                st.caption("Keine Karten gefunden.")
                return

            rows = sorted(
                rows,
                key=lambda row: (
                    _TYPE_ORDER.get(
                        _top_level_card_group(
                            _picker_type(row), section=target_section
                        ),
                        99,
                    ),
                    _normalize_sort_value(_picker_archetype(row)),
                    _normalize_sort_value(_picker_name(row)),
                ),
            )

            for i in range(0, len(rows), 3):
                chunk = rows[i : i + 3]
                cols = st.columns(3)
                for j, row in enumerate(chunk):
                    name = _picker_name(row)
                    if not name:
                        continue
                    img = row.get("image_url_small") or row.get("Bild")
                    key_base = f"{key_prefix}_{i}_{j}"
                    with cols[j]:
                        if img:
                            st.image(img, width=_CARD_IMAGE_WIDTH)
                        else:
                            short = (name[:12] + "…") if len(name) > 13 else name
                            st.markdown(
                                f'<div style="'
                                f"width:{_CARD_IMAGE_WIDTH}px;"
                                "height:100px;"
                                "background:#2a2a2a;"
                                "border:1px solid #555;"
                                "border-radius:4px;"
                                "display:flex;"
                                "align-items:center;"
                                "justify-content:center;"
                                "text-align:center;"
                                "font-size:10px;"
                                "color:#ccc;"
                                "padding:4px;"
                                f'">🃏 {short}</div>',
                                unsafe_allow_html=True,
                            )
                        short = (name[:13] + "…") if len(name) > 14 else name
                        source_label = str(row.get("option_source") or "").strip()
                        st.caption(
                            f"{short} · {source_label}" if source_label else short
                        )
                        b1, b3 = st.columns(2)
                        disabled = _section_is_full(draft, target_section)
                        if b1.button(
                            "+1",
                            key=f"pick1_{key_base}",
                            disabled=disabled,
                            use_container_width=True,
                            help=f"{name} +1",
                        ):
                            _upsert_card(
                                draft,
                                section=target_section,
                                card_name=name,
                                card_passcode=(
                                    int(row["card_passcode"])
                                    if row.get("card_passcode") is not None
                                    else None
                                ),
                                image_url_small=img,
                                quantity_delta=1,
                                card_type=_picker_type(row),
                                card_archetype=_picker_archetype(row),
                                inclusion_rate_pct=row.get("inclusion_rate_pct"),
                                average_copies_when_present=row.get(
                                    "average_copies_when_present"
                                ),
                                decks_with_card=row.get("decks_with_card"),
                                average_copies_per_deck=row.get(
                                    "average_copies_per_deck"
                                ),
                            )
                            st.rerun()
                        if b3.button(
                            "+3",
                            key=f"pick3_{key_base}",
                            disabled=disabled,
                            use_container_width=True,
                            help=f"{name} +3",
                        ):
                            _upsert_card(
                                draft,
                                section=target_section,
                                card_name=name,
                                card_passcode=(
                                    int(row["card_passcode"])
                                    if row.get("card_passcode") is not None
                                    else None
                                ),
                                image_url_small=img,
                                quantity_delta=3,
                                card_type=_picker_type(row),
                                card_archetype=_picker_archetype(row),
                                inclusion_rate_pct=row.get("inclusion_rate_pct"),
                                average_copies_when_present=row.get(
                                    "average_copies_when_present"
                                ),
                                decks_with_card=row.get("decks_with_card"),
                                average_copies_per_deck=row.get(
                                    "average_copies_per_deck"
                                ),
                            )
                            st.rerun()

        def _render_picker_table(
            rows: list[dict[str, Any]],
            *,
            target_section: str,
            key_prefix: str,
            show_source_hint: str | None = None,
        ) -> None:
            if show_source_hint:
                st.caption(show_source_hint)
            if not rows:
                st.caption("Keine Karten gefunden.")
                return

            rows = sorted(
                rows,
                key=lambda row: (
                    _TYPE_ORDER.get(
                        _top_level_card_group(
                            _picker_type(row), section=target_section
                        ),
                        99,
                    ),
                    _normalize_sort_value(_picker_archetype(row)),
                    _normalize_sort_value(_picker_name(row)),
                ),
            )

            h1, h2, h3 = st.columns([1.0, 5.0, 2.2])
            h1.caption("Bild")
            h2.caption("Karte")
            h3.caption("Aktion")

            disabled = _section_is_full(draft, target_section)
            for idx, row in enumerate(rows):
                name = _picker_name(row)
                if not name:
                    continue
                c1, c2, c3 = st.columns([1.0, 5.0, 2.2])
                image = row.get("image_url_small") or row.get("Bild")
                if image:
                    c1.image(image, width=36)
                else:
                    c1.caption("🃏")
                c2.caption(name)
                b1, b3 = c3.columns(2)
                if b1.button(
                    "+1",
                    key=f"tab1_{key_prefix}_{idx}",
                    disabled=disabled,
                    use_container_width=True,
                    help=f"{name} +1",
                ):
                    _upsert_card(
                        draft,
                        section=target_section,
                        card_name=name,
                        card_passcode=(
                            int(row["card_passcode"])
                            if row.get("card_passcode") is not None
                            else None
                        ),
                        image_url_small=image,
                        quantity_delta=1,
                        card_type=_picker_type(row),
                        card_archetype=_picker_archetype(row),
                        inclusion_rate_pct=row.get("inclusion_rate_pct"),
                        average_copies_when_present=row.get(
                            "average_copies_when_present"
                        ),
                        decks_with_card=row.get("decks_with_card"),
                        average_copies_per_deck=row.get("average_copies_per_deck"),
                    )
                    st.rerun()
                if b3.button(
                    "+3",
                    key=f"tab3_{key_prefix}_{idx}",
                    disabled=disabled,
                    use_container_width=True,
                    help=f"{name} +3",
                ):
                    _upsert_card(
                        draft,
                        section=target_section,
                        card_name=name,
                        card_passcode=(
                            int(row["card_passcode"])
                            if row.get("card_passcode") is not None
                            else None
                        ),
                        image_url_small=image,
                        quantity_delta=3,
                        card_type=_picker_type(row),
                        card_archetype=_picker_archetype(row),
                        inclusion_rate_pct=row.get("inclusion_rate_pct"),
                        average_copies_when_present=row.get(
                            "average_copies_when_present"
                        ),
                        decks_with_card=row.get("decks_with_card"),
                        average_copies_per_deck=row.get("average_copies_per_deck"),
                    )
                    st.rerun()

        st.markdown("#### Kartensuche")
        search_mode = st.segmented_control(
            "Quelle",
            options=["Namenssuche", "Gruppenoptionen"],
            key=SEARCH_MODE_STATE_KEY,
        )
        target_section = st.session_state.get(SEARCH_TARGET_SECTION_STATE_KEY, "main")

        if search_mode == "Namenssuche":
            target_section = st.selectbox(
                "Zu Sektion",
                options=list(_draft_sections()),
                key=SEARCH_TARGET_SECTION_STATE_KEY,
                format_func=_section_label,
            )
            query = st.text_input(
                "Kartenname",
                key=SEARCH_QUERY_STATE_KEY,
                placeholder="z. B. Ash Blossom",
                label_visibility="collapsed",
            )
            if not query.strip():
                st.caption("Suchbegriff eingeben…")
                return

            limit = int(st.session_state.get(SEARCH_LIMIT_STATE_KEY, 30))
            results = load_search_cards(repository, query=query, limit=limit)
            if not results:
                st.warning("Keine Karten gefunden.")
                return

            _render_picker_cards(
                results,
                target_section=target_section,
                key_prefix=f"search_{target_section}",
            )
        else:
            deck_group = st.session_state.get(DECK_GROUP_STATE_KEY)
            if not deck_group:
                st.caption("Bitte zuerst eine Deckgruppe wählen.")
                return

            group_rows = load_deck_group_card_options(
                repository,
                deck_name=str(deck_group),
                start_date=start_date,
                end_date=end_date,
            )
            rare_rows = load_underused_cards_for_deck_group(
                repository,
                deck_name=str(deck_group),
                start_date=start_date,
                end_date=end_date,
                limit=int(st.session_state.get(UNDERUSED_LIMIT_STATE_KEY, 25)),
            )

            merged_by_key: dict[tuple[str, str], dict[str, Any]] = {}

            for row in group_rows:
                card_name = str(row.get("Karte") or row.get("card_name") or "").strip()
                if not card_name:
                    continue
                card_passcode = row.get("card_passcode")
                key = (
                    str(int(card_passcode)) if card_passcode is not None else "",
                    card_name.casefold(),
                )
                entry = dict(row)
                entry["option_source"] = "Gruppenoption"
                merged_by_key[key] = entry

            for row in rare_rows:
                card_name = str(row.get("card_name") or "").strip()
                if not card_name:
                    continue
                card_passcode = row.get("card_passcode")
                key = (
                    str(int(card_passcode)) if card_passcode is not None else "",
                    card_name.casefold(),
                )
                normalized_rare = {
                    "Karte": card_name,
                    "Bild": row.get("image_url_small"),
                    "card_passcode": (
                        int(card_passcode) if card_passcode is not None else None
                    ),
                    "Kartentyp": row.get("card_type"),
                    "Archetyp": row.get("card_archetype"),
                    "section": row.get("section"),
                    "inclusion_rate_pct": row.get("inclusion_rate_pct"),
                    "average_copies_when_present": row.get(
                        "average_copies_when_present"
                    ),
                    "decks_with_card": row.get("decks_with_card"),
                    "option_source": "Seltene Vorschläge",
                }
                existing = merged_by_key.get(key)
                if existing is None:
                    merged_by_key[key] = normalized_rare
                    continue
                existing["option_source"] = "Gruppenoption · Selten"
                for field in (
                    "inclusion_rate_pct",
                    "average_copies_when_present",
                    "decks_with_card",
                ):
                    if (
                        existing.get(field) is None
                        and normalized_rare.get(field) is not None
                    ):
                        existing[field] = normalized_rare[field]

            current_names = {
                _normalize_sort_value(row.get("card_name"))
                for section in _draft_sections()
                for row in draft.get(section, [])
                if str(row.get("card_name") or "").strip()
            }
            current_ids = {
                int(row.get("card_passcode"))
                for section in _draft_sections()
                for row in draft.get(section, [])
                if row.get("card_passcode") is not None
            }
            options = [
                row
                for row in merged_by_key.values()
                if (
                    _normalize_sort_value(row.get("Karte") or row.get("card_name"))
                    not in current_names
                    and (
                        row.get("card_passcode") is None
                        or int(row.get("card_passcode")) not in current_ids
                    )
                )
            ]
            if not options:
                st.caption(
                    "Keine weiteren Karten aus der gewählten Deckgruppe vorhanden."
                )
                return

            _render_picker_table(
                options,
                target_section=target_section,
                key_prefix=f"group_{target_section}",
                show_source_hint=(
                    "Gruppenoptionen inkl. seltener Vorschläge, die im aktuellen Deck noch nicht enthalten sind."
                ),
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    _ensure_state()

    pending_deck_name = st.session_state.pop(DECK_NAME_PENDING_STATE_KEY, None)
    if pending_deck_name is not None:
        st.session_state[DECK_NAME_STATE_KEY] = pending_deck_name

    database_path = resolve_dashboard_db_path()
    repository = DashboardRepository(database_path)

    st.title("🏗️ Deckbuilder")
    st.markdown(
        """
        <style>
        /* Compact deck-grid buttons */
        div[data-testid="stButton"] button {
            padding: 0px 2px;
            min-height: 24px;
            font-size: 11px;
            line-height: 1;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    status_message = repository.status_message()
    if status_message is not None:
        st.warning(status_message)
        st.stop()

    start_date, end_date = render_dashboard_date_filter(repository)

    # --- Toolbar ---
    aggregate_rows = load_deck_name_aggregates_extended(
        repository, limit=1000, start_date=start_date, end_date=end_date
    )
    deck_groups = _normalize_group_options(aggregate_rows)
    if not deck_groups:
        st.info("Keine Deckgruppen im aktiven Zeitraum verfügbar.")
        st.stop()

    current_group = st.session_state.get(DECK_GROUP_STATE_KEY)
    if current_group not in deck_groups:
        st.session_state[DECK_GROUP_STATE_KEY] = deck_groups[0]

    tb1, tb2, tb3, tb4, tb5 = st.columns([3, 3, 2, 2, 2])
    tb1.text_input("Deckname", key=DECK_NAME_STATE_KEY, label_visibility="collapsed")
    tb2.selectbox(
        "Deckgruppe",
        options=deck_groups,
        key=DECK_GROUP_STATE_KEY,
        label_visibility="collapsed",
    )
    if tb3.button("Startdeck laden", use_container_width=True):
        selected = st.session_state.get(DECK_GROUP_STATE_KEY)
        if selected:
            starter = load_deck_group_starter(
                repository,
                deck_name=str(selected),
                start_date=start_date,
                end_date=end_date,
            )
            st.session_state[DRAFT_STATE_KEY] = {
                "main": starter.get("main", []),
                "extra": starter.get("extra", []),
                "side": starter.get("side", []),
            }
            st.session_state[DECK_NAME_PENDING_STATE_KEY] = f"{selected} Draft"
            st.rerun()
    if tb4.button("Draft leeren", use_container_width=True):
        st.session_state[DRAFT_STATE_KEY] = _new_empty_draft()
        st.rerun()
    tb5.caption("Nur Session State.")

    selected_group = st.session_state.get(DECK_GROUP_STATE_KEY)
    if selected_group:
        deck_instances = repository.list_deck_instances_for_name(
            str(selected_group),
            limit=250,
            start_date=start_date,
            end_date=end_date,
        )
        if deck_instances:
            instance_ids = [int(row["deck_site_id"]) for row in deck_instances]
            current_instance_id = st.session_state.get(DECK_INSTANCE_LINK_STATE_KEY)
            if current_instance_id not in instance_ids:
                st.session_state[DECK_INSTANCE_LINK_STATE_KEY] = instance_ids[0]

            instance_lookup = {int(row["deck_site_id"]): row for row in deck_instances}
            link_col_1, link_col_2 = st.columns([4, 2])
            link_col_1.selectbox(
                "Deckliste aus Deckgruppe",
                options=instance_ids,
                key=DECK_INSTANCE_LINK_STATE_KEY,
                format_func=lambda value: _deck_instance_link_label(
                    instance_lookup[int(value)]
                ),
                label_visibility="collapsed",
            )
            selected_instance = instance_lookup.get(
                int(st.session_state[DECK_INSTANCE_LINK_STATE_KEY])
            )
            selected_url = (
                str(selected_instance.get("deck_url") or "").strip()
                if selected_instance is not None
                else ""
            )
            if selected_url:
                link_col_2.link_button(
                    "Deckliste im neuen Tab",
                    selected_url,
                    use_container_width=True,
                )
            else:
                link_col_2.caption("Keine externe Deckliste vorhanden.")

    st.divider()

    draft = st.session_state[DRAFT_STATE_KEY]

    # --- Two-column layout: deck (left) / search + suggestions (right) ---
    deck_col, search_col = st.columns([3, 1])

    with deck_col:
        for section in _draft_sections():
            with st.container(border=True):
                _render_section_grid(section, draft, key_prefix="deck")
            st.markdown("")

    with search_col:
        _render_search_panel(repository, draft, start_date, end_date)


main()
