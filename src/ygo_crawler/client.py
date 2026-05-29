from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .config import CARD_INFO_API_URL, DEFAULT_TIMEOUT_SECONDS, DEFAULT_USER_AGENT


@dataclass(slots=True, frozen=True)
class FetchedPage:
    requested_url: str
    final_url: str
    text: str


class YGOProDeckClient:
    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._client = httpx.Client(
            follow_redirects=True,
            headers={"User-Agent": user_agent},
            timeout=timeout_seconds,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> YGOProDeckClient:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def fetch(self, url: str) -> FetchedPage:
        response = self._client.get(url)
        response.raise_for_status()
        return FetchedPage(
            requested_url=url,
            final_url=str(response.url),
            text=response.text,
        )

    def fetch_json(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
        response = self._client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def fetch_card_info_by_ids(self, passcodes: list[int]) -> list[dict[str, Any]]:
        if not passcodes:
            return []
        payload = self.fetch_json(CARD_INFO_API_URL, params={"id": ",".join(str(passcode) for passcode in passcodes)})
        if not isinstance(payload, dict):
            raise ValueError("Unexpected card info API response format")
        data = payload.get("data", [])
        if not isinstance(data, list):
            raise ValueError("Unexpected card info API payload")
        return [row for row in data if isinstance(row, dict)]