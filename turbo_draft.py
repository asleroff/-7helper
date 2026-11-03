"""Черновики закрытия из Chrome-расширения Турбо ПВЗ (локальный draft API)."""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any

API_URL = os.getenv("TURBO_DRAFT_API_URL", "http://127.0.0.1:8787").rstrip("/")
API_TOKEN = os.getenv("TURBO_DRAFT_API_TOKEN", "dev-extension-token-change-me")


class DraftNotFound(Exception):
    pass


class DraftApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _fetch_sync(point_number: str) -> dict[str, Any]:
    point = "".join(ch for ch in str(point_number) if ch.isdigit())
    if not point:
        raise DraftApiError("Некорректный номер ПП")

    url = f"{API_URL}/api/drafts/{point}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {API_TOKEN}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        if e.code == 404:
            raise DraftNotFound(raw) from e
        if e.code == 401:
            raise DraftApiError("API черновиков: неверный токен", status=401) from e
        raise DraftApiError(f"API черновиков HTTP {e.code}: {raw[:200]}", status=e.code) from e
    except urllib.error.URLError as e:
        raise DraftApiError(
            "Не удалось связаться с API черновиков. "
            "Запусти `python api/server.py` в папке rasshirenie (порт 8787)."
        ) from e


async def fetch_draft(point_number: str) -> dict[str, Any]:
    return await asyncio.to_thread(_fetch_sync, point_number)


def closing_fields_from_draft(payload: dict[str, Any]) -> dict[str, Any]:
    """Маппинг JSON расширения → поля FSM закрытия."""
    draft = payload.get("draft") or payload
    c = draft.get("closing") or {}
    point = str(draft.get("point_number") or "").strip()

    def num(key: str):
        v = c.get(key)
        if v is None or v == "":
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return {
        "point_number": point or None,
        "closing_transport_number": (str(c["transport_number"]).lstrip("#").strip() if c.get("transport_number") is not None else None),
        "closing_transport_date": c.get("transport_date"),
        "closing_time": c.get("closing_time"),
        "closing_accepted_total": num("accepted_total"),
        "closing_tya": num("tya"),
        "closing_ktya": num("ktya"),
        "closing_shortage": num("shortage"),
        "closing_excess": num("excess"),
        "closing_zasyl": num("zasyl"),
        "closing_issued": num("issued"),
        "closing_leftover": num("leftover"),
        "turbo_collected_at": draft.get("collected_at") or payload.get("saved_at"),
        "turbo_preview_text": payload.get("preview_text"),
    }


def missing_closing_fields(fields: dict[str, Any]) -> list[str]:
    """Обязательные поля закрытия из черновика Турбо."""
    required = [
        ("closing_transport_number", "номер перевозки"),
        ("closing_transport_date", "дата перевозки"),
        ("closing_time", "время закрытия"),
        ("closing_accepted_total", "принято"),
        ("closing_tya", "ТЯ"),
        ("closing_ktya", "КТЯ"),
        ("closing_shortage", "недостачи"),
        ("closing_excess", "излишки"),
        ("closing_zasyl", "засылы"),
        ("closing_issued", "выдано"),
        ("closing_leftover", "остатки"),
    ]
    return [label for key, label in required if fields.get(key) is None]
