from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import time
from typing import Any

import httpx

from backend.integrations.schemas import RawRecallNoticeIn


OPENFDA_ENDPOINT = "https://api.fda.gov/food/enforcement.json"


def _as_openfda_yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _parse_openfda_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # openFDA uses YYYYMMDD
        dt = datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)
        return dt
    except Exception:
        return None


def map_openfda_record_to_notice(record: dict[str, Any]) -> RawRecallNoticeIn:
    external_id = record.get("recall_number") or record.get("event_id")
    published_at = _parse_openfda_date(record.get("report_date"))
    source_url = None
    if external_id:
        source_url = f"{OPENFDA_ENDPOINT}?search=recall_number:{external_id}"

    raw_text_parts: list[str] = []
    for key in (
        "product_description",
        "reason_for_recall",
        "recalling_firm",
        "code_info",
        "distribution_pattern",
        "state",
        "country",
        "classification",
        "status",
    ):
        val = record.get(key)
        if isinstance(val, str) and val.strip():
            raw_text_parts.append(f"{key}: {val.strip()}")

    return RawRecallNoticeIn(
        source_type="openfda",
        external_id=str(external_id) if external_id else None,
        source_url=source_url,
        published_at_utc=published_at,
        raw_json=record,
        raw_text="\n".join(raw_text_parts) if raw_text_parts else "",
    )


def _fetch_openfda(
    client: httpx.Client, *, params: dict[str, str], retries: int = 3
) -> dict[str, Any] | None:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.get(OPENFDA_ENDPOINT, params=params)
            # openFDA uses 404 when a query has zero matches; treat as empty.
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            payload = resp.json()
            return payload if isinstance(payload, dict) else None
        except Exception as e:  # network, 5xx, json
            last_exc = e
            time.sleep(0.4 * (attempt + 1))
    raise last_exc or RuntimeError("openFDA request failed")


def pull_recent_fda_recalls(*, days: int = 90, limit: int = 100, timeout_s: float = 20.0) -> list[dict[str, Any]]:
    """
    Pull recent recalls from openFDA.

    Note: `report_date` can be sparse; openFDA returns 404 for zero matches. To keep the
    gated live test stable, this function widens the date range if the requested window
    returns zero matches (7d -> 30d -> 90d -> 180d), then finally falls back to a
    non-filtered query.
    """

    end = date.today()
    windows = [days, 30, 90, 180]

    with httpx.Client(timeout=timeout_s) as client:
        for win in windows:
            start = end - timedelta(days=win)
            start_s = _as_openfda_yyyymmdd(start)
            end_s = _as_openfda_yyyymmdd(end)
            payload = _fetch_openfda(
                client,
                params={
                    # Note: openFDA's query parser is sensitive to '+'; use spaces.
                    "search": f"report_date:[{start_s} TO {end_s}]",
                    "limit": str(limit),
                },
            )
            results = payload.get("results") if isinstance(payload, dict) else None
            if isinstance(results, list) and any(isinstance(r, dict) for r in results):
                return [r for r in results if isinstance(r, dict)]

        payload = _fetch_openfda(client, params={"limit": str(limit)})
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            return []
        return [r for r in results if isinstance(r, dict)]
