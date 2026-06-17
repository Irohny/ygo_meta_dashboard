from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .client import YGOProDeckClient
from .config import (
    CARD_METADATA_BATCH_SIZE,
    CARD_METADATA_VERSION,
    DEFAULT_DATABASE_PATH,
)
from .models import CardRecord
from .storage import SQLiteStorage

_PLACEHOLDER_TEXT_VALUES = {"none", "null", "n/a", "na"}


@dataclass(slots=True, frozen=True)
class CardMetadataEnrichmentSummary:
    candidate_count: int
    requested_count: int
    enriched_count: int
    batch_count: int


def enrich_cards(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    *,
    batch_size: int = CARD_METADATA_BATCH_SIZE,
    limit: int | None = None,
) -> CardMetadataEnrichmentSummary:
    with SQLiteStorage(database_path) as storage:
        storage.initialize()
        return enrich_cards_in_storage(storage, batch_size=batch_size, limit=limit)


def enrich_cards_in_storage(
    storage: SQLiteStorage,
    *,
    batch_size: int = CARD_METADATA_BATCH_SIZE,
    limit: int | None = None,
    client: YGOProDeckClient | None = None,
) -> CardMetadataEnrichmentSummary:
    candidate_rows = storage.list_cards_missing_metadata(limit=limit)
    candidate_count = len(candidate_rows)
    if not candidate_rows:
        return CardMetadataEnrichmentSummary(
            candidate_count=0, requested_count=0, enriched_count=0, batch_count=0
        )

    owns_client = client is None
    api_client = client or YGOProDeckClient()
    safe_batch_size = max(batch_size, 1)
    enriched_records: list[CardRecord] = []
    batch_count = 0
    requested_count = candidate_count

    try:
        pending_rows = {
            int(row["card_passcode"]): str(row["canonical_name"])
            for row in candidate_rows
        }
        pending_ids = list(pending_rows.keys())
        for start_index in range(0, len(pending_ids), safe_batch_size):
            batch_ids = pending_ids[start_index : start_index + safe_batch_size]
            card_infos = api_client.fetch_card_info_by_ids(batch_ids)
            batch_count += 1
            resolved_records = _to_card_records(card_infos)
            enriched_records.extend(resolved_records)

            resolved_ids = {record.card_passcode for record in resolved_records}
            unresolved_ids = [
                passcode for passcode in batch_ids if passcode not in resolved_ids
            ]
            if unresolved_ids:
                unresolved_enriched_at = _utc_now()
                enriched_records.extend(
                    CardRecord(
                        card_passcode=passcode,
                        canonical_name=pending_rows[passcode],
                        last_enriched_at=unresolved_enriched_at,
                        metadata_version=CARD_METADATA_VERSION,
                    )
                    for passcode in unresolved_ids
                )

        if enriched_records:
            storage.upsert_cards(enriched_records)

        return CardMetadataEnrichmentSummary(
            candidate_count=candidate_count,
            requested_count=requested_count,
            enriched_count=len(enriched_records),
            batch_count=batch_count,
        )
    finally:
        if owns_client:
            api_client.close()


def _to_card_records(card_infos: list[dict[str, Any]]) -> list[CardRecord]:
    records: list[CardRecord] = []
    enriched_at = _utc_now()
    for card_info in card_infos:
        passcode = card_info.get("id")
        name = card_info.get("name")
        if (
            not isinstance(passcode, int)
            or not isinstance(name, str)
            or not name.strip()
        ):
            continue
        records.append(
            CardRecord(
                card_passcode=passcode,
                canonical_name=name.strip(),
                card_archetype=_normalize_optional_text(card_info.get("archetype")),
                card_type=_normalize_optional_text(card_info.get("type")),
                card_race=_normalize_optional_text(card_info.get("race")),
                card_attribute=_normalize_optional_text(card_info.get("attribute")),
                frame_type=_normalize_optional_text(card_info.get("frameType")),
                effect_text=_normalize_optional_text(card_info.get("desc")),
                cardmarket_price_eur=_extract_cardmarket_price(card_info),
                image_url_small=_extract_image_url_small(card_info),
                last_enriched_at=enriched_at,
                metadata_version=CARD_METADATA_VERSION,
            )
        )
    return records


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    normalized = value.strip()
    if normalized.lower() in _PLACEHOLDER_TEXT_VALUES:
        return None
    return normalized or None


def _extract_cardmarket_price(card_info: dict[str, Any]) -> float | None:
    raw_prices = card_info.get("card_prices")
    if not isinstance(raw_prices, list) or not raw_prices:
        return None
    first_price = raw_prices[0]
    if not isinstance(first_price, dict):
        return None
    raw_value = first_price.get("cardmarket_price")
    if raw_value is None:
        return None
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


def _extract_image_url_small(card_info: dict[str, Any]) -> str | None:
    raw_images = card_info.get("card_images")
    if not isinstance(raw_images, list) or not raw_images:
        return None
    first_image = raw_images[0]
    if not isinstance(first_image, dict):
        return None
    return _normalize_optional_text(first_image.get("image_url_small"))


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
