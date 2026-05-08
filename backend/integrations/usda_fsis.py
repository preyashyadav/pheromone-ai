from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from backend.integrations.schemas import RawRecallNoticeIn


USDA_FSIS_RECALLS_ENDPOINT = "https://www.fsis.usda.gov/fsis/api/recall/v/1"


def pull_recent_usda_recalls(*, timeout_s: float = 20.0) -> list[dict[str, Any]]:
    with httpx.Client(timeout=timeout_s) as client:
        resp = client.get(USDA_FSIS_RECALLS_ENDPOINT)
        resp.raise_for_status()
        payload = resp.json()

    if isinstance(payload, dict) and "results" in payload and isinstance(payload["results"], list):
        return [r for r in payload["results"] if isinstance(r, dict)]
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    return []


def map_usda_record_to_notice(record: dict[str, Any]) -> RawRecallNoticeIn:
    external_id = record.get("recallNumber") or record.get("recall_number") or record.get("id")
    source_url = record.get("url") or USDA_FSIS_RECALLS_ENDPOINT
    published_at = None
    for k in ("recallDate", "date", "publishDate"):
        v = record.get(k)
        if isinstance(v, str) and v:
            try:
                published_at = datetime.fromisoformat(v.replace("Z", "+00:00"))
                break
            except Exception:
                continue

    return RawRecallNoticeIn(
        source_type="usda_fsis",
        external_id=str(external_id) if external_id is not None else None,
        source_url=str(source_url) if source_url else None,
        published_at_utc=published_at,
        raw_json=record,
        raw_text=(record.get("summary") or record.get("title") or "") if isinstance(record.get("summary") or record.get("title") or "", str) else "",
    )

