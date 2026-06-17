from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(slots=True, frozen=True)
class NonEngineRoleScores:
    role: str
    confidence: str
    handtrap_score: float
    boardbreaker_score: float
    floodgate_score: float
    protection_score: float
    draw_engine_score: float


_WHITESPACE_RE = re.compile(r"\s+")

_HANDTRAP_PATTERNS: tuple[tuple[str, float], ...] = (
    ("discard this card", 4.0),
    ("send this card from your hand", 4.0),
    ("reveal this card in your hand", 3.0),
    ("activate this card from your hand", 2.0),
    ("special summon this card from your hand", 4.0),
    ("during your opponent's turn", 3.0),
    ("during your opponents turn", 3.0),
    ("during either player's turn", 4.0),
    ("during either players turn", 4.0),
    ("when your opponent", 2.5),
    ("if your opponent", 0.5),
    ("quick effect", 2.5),
    ("if you control no cards, you can activate this card from your hand", 6.0),
    ("while you control no monsters", 2.0),
)

_BOARDBREAKER_PATTERNS: tuple[tuple[str, float], ...] = (
    ("your opponent controls", 3.0),
    ("all face-up monsters your opponent controls", 5.0),
    ("all monsters your opponent controls", 5.0),
    ("all cards your opponent controls", 5.0),
    ("destroy all", 3.0),
    ("banish all", 3.0),
    ("return all", 2.5),
    ("shuffle all", 2.5),
    ("tribute all", 3.0),
    ("negate the effects of all", 3.5),
    ("negate their effects", 2.0),
    ("banish cards from their field face-down", 5.0),
    ("destroy all spell and trap cards your opponent controls", 5.0),
    ("using monsters from either field as fusion material", 5.0),
    ("tribute 1 monster your opponent controls", 5.0),
    ("tributes from either side of the field", 5.0),
    ("choose that many effect monsters your opponent controls", 4.0),
    ("at the end of the battle phase", 3.0),
    ("end of the battle phase", 2.0),
    ("take control of 1 monster your opponent controls", 6.0),
    ("look at your opponent's hand", 4.0),
    ("choose 1 card from it to shuffle into the deck", 4.0),
    ("target 1 face-up monster your opponent controls", 4.0),
    ("target 1 face-up monster on the field", 3.0),
    ("apply these effects to 1 face-up monster on the field", 5.0),
    ("cannot attack", 2.0),
    ("cannot be tributed", 2.0),
    ("cannot be used as material", 3.0),
)

_FLOODGATE_PATTERNS: tuple[tuple[str, float], ...] = (
    ("neither player can special summon", 5.0),
    ("players cannot special summon", 5.0),
    ("your opponent cannot special summon", 4.5),
    ("your opponent cannot activate monster effects", 4.0),
    ("cannot special summon", 3.0),
    ("can only", 2.0),
    ("while this card is face-up", 2.0),
    ("while face-up on the field", 2.0),
    ("must set spell cards before activating them", 6.0),
    ("both players must set spell cards before activating them", 6.0),
    ("cannot activate them until their next turn after setting them", 6.0),
    ("sent to the gy is banished instead", 5.0),
    ("any monster sent to the gy is banished instead", 6.0),
)

_PROTECTION_PATTERNS: tuple[tuple[str, float], ...] = (
    ("cannot be destroyed", 5.0),
    ("cannot be targeted", 5.0),
    ("unaffected by your opponent", 5.0),
    ("cards you control cannot", 4.0),
    ("negate the activation", 3.5),
    ("negate the summon", 4.0),
    ("negate its effects", 3.5),
    ("until the end of the next turn, its effects are negated", 4.0),
    ("activated effects and effects on the field", 3.0),
    ("declare 1 card name", 3.0),
    ("would be destroyed", 2.0),
    ("protect", 1.5),
)

_DRAW_ENGINE_PATTERNS: tuple[tuple[str, float], ...] = (
    ("draw 2 cards", 5.0),
    ("draw 1 card", 4.0),
    ("draw cards", 3.0),
    ("excavate cards from the top of your deck", 3.5),
    ("add 1 excavated card to your hand", 4.5),
    ("add 1 card from your deck to your hand", 3.0),
    ("place the rest on the bottom of your deck", 1.5),
)


def classify_non_engine_role(
    *,
    card_name: str | None = None,
    card_type: str | None,
    frame_type: str | None,
    race: str | None,
    effect_text: str | None,
    average_main_copies: float | int | None = None,
    average_side_copies: float | int | None = None,
    main_presence_pct: float | int | None = None,
    side_presence_pct: float | int | None = None,
) -> NonEngineRoleScores:
    normalized_name = _normalize_text(card_name)
    normalized_type = _normalize_token(card_type)
    normalized_frame = _normalize_token(frame_type)
    normalized_race = _normalize_token(race)
    normalized_text = _normalize_text(effect_text)

    scores = {
        "handtrap": _score_patterns(normalized_text, _HANDTRAP_PATTERNS),
        "boardbreaker": _score_patterns(normalized_text, _BOARDBREAKER_PATTERNS),
        "floodgate": _score_patterns(normalized_text, _FLOODGATE_PATTERNS),
        "protection": _score_patterns(normalized_text, _PROTECTION_PATTERNS),
        "draw_engine": _score_patterns(normalized_text, _DRAW_ENGINE_PATTERNS),
    }

    if "monster" in normalized_type:
        if (
            "discard this card" in normalized_text
            or "send this card from your hand" in normalized_text
            or "special summon this card from your hand" in normalized_text
        ):
            scores["handtrap"] += 3.0
        if "quick effect" in normalized_text:
            scores["handtrap"] += 1.0

    if "trap" in normalized_type and "from your hand" in normalized_text:
        scores["handtrap"] += 2.5
    if (
        "trap" in normalized_type
        and "activate this card from your hand" in normalized_text
    ):
        scores["handtrap"] += 4.0

    if normalized_race == "continuous":
        scores["floodgate"] += 2.0
    elif normalized_race == "field":
        scores["floodgate"] += 1.5
    elif normalized_race == "counter":
        scores["protection"] += 2.5

    if normalized_name.startswith("solemn "):
        scores["protection"] += 4.0
    if normalized_name.startswith("pot of "):
        scores["draw_engine"] += 4.0

    if (
        normalized_frame in {"spell", "trap"}
        and "your opponent controls" in normalized_text
    ):
        scores["boardbreaker"] += 1.0
    if (
        "take control of 1 monster your opponent controls" in normalized_text
        and "draw 2 cards" in normalized_text
    ):
        scores["boardbreaker"] += 3.0

    if "cards you control" in normalized_text and (
        "cannot be destroyed" in normalized_text
        or "cannot be targeted" in normalized_text
    ):
        scores["protection"] += 2.0

    if (
        "target 1 monster in your opponent's gy" in normalized_text
        and "effects are negated" in normalized_text
    ):
        scores["protection"] += 3.5
    if (
        "declare 1 card name" in normalized_text
        and "negate its effects" in normalized_text
    ):
        scores["protection"] += 3.0
    if (
        "in response to this card's activation" in normalized_text
        and scores["boardbreaker"] > 0
    ):
        scores["boardbreaker"] += 1.0
    if "until the end of this turn" in normalized_text and scores["boardbreaker"] > 0:
        scores["boardbreaker"] += 1.0
        scores["floodgate"] = max(0.0, scores["floodgate"] - 3.0)
    if (
        "if you control no cards, you can activate this card from your hand"
        in normalized_text
    ):
        scores["handtrap"] += 2.0
        scores["boardbreaker"] = max(0.0, scores["boardbreaker"] - 1.5)
    if (
        "during either player's turn" in normalized_text
        and "special summon both this card from your hand" in normalized_text
    ):
        scores["handtrap"] += 4.0
    if "both players must set spell cards before activating them" in normalized_text:
        scores["floodgate"] += 2.0
    if "any monster sent to the gy is banished instead" in normalized_text:
        scores["floodgate"] += 2.0
    if "until the end of the next turn" in normalized_text and scores["protection"] > 0:
        scores["protection"] += 1.0
    if (
        "activate this card from your hand" in normalized_text
        and "battle phase" in normalized_text
    ):
        scores["boardbreaker"] += 3.5
        scores["handtrap"] = max(0.0, scores["handtrap"] - 4.0)
    if normalized_text == "none":
        scores["handtrap"] = 0.0
        scores["boardbreaker"] = 0.0
        scores["floodgate"] = 0.0
        scores["protection"] = 0.0
        scores["draw_engine"] = 0.0

    main_copies = _to_float(average_main_copies)
    side_copies = _to_float(average_side_copies)
    main_presence = _to_float(main_presence_pct)
    side_presence = _to_float(side_presence_pct)

    if side_copies > main_copies + 0.25:
        scores["boardbreaker"] += 1.0
        scores["floodgate"] += 0.5
    if side_presence > main_presence + 10.0:
        scores["boardbreaker"] += 0.5
        scores["floodgate"] += 0.5
    if (
        main_presence >= side_presence
        and "monster" in normalized_type
        and (
            "discard this card" in normalized_text
            or "special summon this card from your hand" in normalized_text
            or "quick effect" in normalized_text
        )
    ):
        scores["handtrap"] += 1.0

    ordered_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_role, best_score = ordered_scores[0]
    second_score = ordered_scores[1][1]
    gap = best_score - second_score

    if best_score < 3.0:
        role = "unknown_non_engine"
        confidence = "niedrig"
    else:
        role = best_role
        confidence = _confidence_label(best_score, gap)

    return NonEngineRoleScores(
        role=role,
        confidence=confidence,
        handtrap_score=round(scores["handtrap"], 2),
        boardbreaker_score=round(scores["boardbreaker"], 2),
        floodgate_score=round(scores["floodgate"], 2),
        protection_score=round(scores["protection"], 2),
        draw_engine_score=round(scores["draw_engine"], 2),
    )


def format_non_engine_role_label(role: str) -> str:
    labels = {
        "handtrap": "Handtrap",
        "boardbreaker": "Boardbreaker",
        "floodgate": "Floodgate",
        "protection": "Protection",
        "draw_engine": "Draw Engine",
        "unknown_non_engine": "Unklar",
    }
    return labels.get(role, role.replace("_", " ").title())


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", value.strip().lower())


def _normalize_token(value: str | None) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def _score_patterns(text: str, patterns: tuple[tuple[str, float], ...]) -> float:
    score = 0.0
    for pattern, weight in patterns:
        if pattern in text:
            score += weight
    return score


def _to_float(value: float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _confidence_label(best_score: float, gap: float) -> str:
    if best_score >= 7.0 and gap >= 2.5:
        return "hoch"
    if best_score >= 4.5 and gap >= 1.0:
        return "mittel"
    return "niedrig"
