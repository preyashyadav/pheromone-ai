from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import os
import uuid

from sqlalchemy import create_engine

from backend.db.repositories import Repositories
from backend.db.repositories import (
    CustomerRepository,
    InventoryRepository,
    RecallRepository,
    SupplyChainRepository,
    make_session_factory,
)
from backend.integrations.schemas import RawRecallNoticeIn
from backend.integrations.source_verifier import SourceVerifier


@dataclass(frozen=True)
class RouteResult:
    stored_as: str  # "raw_recall_notice" | "unverified_recall_signal" | "recall_case"
    id: str
    verified: bool


class NoticeRouter:
    def __init__(self, *, repos: Repositories, verifier: SourceVerifier | None = None) -> None:
        self._repos = repos
        self._verifier = verifier or SourceVerifier()

    def ingest_notice(self, notice: RawRecallNoticeIn) -> RouteResult:
        vr = self._verifier.verify(notice.source_url)
        if not vr.verified:
            signal_id = self._repos.recalls.upsert_unverified_recall_signal(
                source_url=notice.source_url,
                reason=vr.reason,
                raw_payload={"notice": notice.model_dump()},
            )
            return RouteResult(stored_as="unverified_recall_signal", id=str(signal_id), verified=False)

        notice_id = self._repos.recalls.upsert_raw_recall_notice(
            source_type=notice.source_type,
            external_id=notice.external_id,
            source_url=notice.source_url,
            verified=True,
            published_at=notice.published_at_utc,
            raw_json=notice.raw_json,
            raw_text=notice.raw_text,
        )
        return RouteResult(stored_as="raw_recall_notice", id=str(notice_id), verified=True)

    def ingest_supplier_inbox(self, inbox_dir: Path) -> list[RouteResult]:
        results: list[RouteResult] = []
        for p in sorted(inbox_dir.glob("*.txt")):
            txt = p.read_text(encoding="utf-8")
            notice = RawRecallNoticeIn(
                source_type="supplier",
                external_id=None,
                source_url=f"supplier://inbox/{p.name}",
                published_at_utc=datetime.now(tz=UTC),
                raw_json={"filename": p.name},
                raw_text=txt,
            )
            results.append(self.ingest_notice(notice))
        return results


def submit_internal_qa_issue(
    store_id: uuid.UUID,
    description: str,
    severity: str,
    time_window: dict[str, Any],
    repos: Repositories | None = None,
) -> str:
    if repos is None:
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            raise RuntimeError("DATABASE_URL is not set")
        engine = create_engine(db_url, pool_pre_ping=True)
        session_factory = make_session_factory(engine)
        repos = Repositories(
            supply_chain=SupplyChainRepository(session_factory),
            inventory=InventoryRepository(session_factory),
            customers=CustomerRepository(session_factory),
            recalls=RecallRepository(session_factory),
        )

    recall_case_id = repos.recalls.create_recall_case_signal_detected(
        source_type="retailer_internal",
        store_id=store_id,
        source_details={
            "description": description,
            "severity": severity,
            "time_window": time_window,
        },
    )
    return str(recall_case_id)
