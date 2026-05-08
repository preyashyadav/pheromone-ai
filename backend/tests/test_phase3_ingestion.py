from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from backend.integrations.notice_router import NoticeRouter, submit_internal_qa_issue
from backend.integrations.openfda import map_openfda_record_to_notice, pull_recent_fda_recalls
from backend.integrations.schemas import RawRecallNoticeIn
from backend.integrations.source_verifier import SourceVerifier


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "real_recalls"


def _fixture_json_paths() -> list[Path]:
    paths = sorted([p for p in FIXTURES_DIR.glob("*.json") if not p.name.startswith("_")])
    assert len(paths) == 25
    return paths


def test_phase3_offline_replay_ingests_all_25_verified(repos) -> None:
    router = NoticeRouter(repos=repos, verifier=SourceVerifier())

    import json

    stored_ids: set[str] = set()
    for p in _fixture_json_paths():
        record = json.loads(p.read_text(encoding="utf-8"))
        notice = map_openfda_record_to_notice(record)
        res = router.ingest_notice(notice)
        assert res.stored_as == "raw_recall_notice"
        assert res.verified is True
        stored_ids.add(res.id)

    assert repos.recalls.count_raw_recall_notices() == 25
    assert len(stored_ids) == 25


def test_phase3_source_verification_routes_unverified_signal(repos) -> None:
    router = NoticeRouter(repos=repos, verifier=SourceVerifier())

    bad = RawRecallNoticeIn(
        source_type="openfda",
        external_id="F-0000-0000",
        source_url="https://malicious-site.example.com/recalls/1",
        raw_json={"hello": "world"},
        raw_text="fake notice",
    )
    res = router.ingest_notice(bad)
    assert res.stored_as == "unverified_recall_signal"
    assert res.verified is False

    good = RawRecallNoticeIn(
        source_type="openfda",
        external_id="F-0000-0001",
        source_url="https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts",
        raw_json={"hello": "world"},
        raw_text="fake notice",
    )
    res2 = router.ingest_notice(good)
    assert res2.stored_as == "raw_recall_notice"
    assert res2.verified is True


def test_phase3_supplier_inbox_ingests_5_notices(repos) -> None:
    router = NoticeRouter(repos=repos, verifier=SourceVerifier())
    inbox = Path(__file__).parents[1] / "integrations" / "supplier_inbox"
    results = router.ingest_supplier_inbox(inbox)
    assert len(results) == 5
    assert all(r.stored_as == "raw_recall_notice" for r in results)
    assert repos.recalls.count_raw_recall_notices() == 5


def test_phase3_internal_trigger_creates_recall_case_signal_detected(repos) -> None:
    ids = repos.supply_chain.insert_min_supply_chain_rows()
    store_id = ids["store_id"]

    recall_case_id = submit_internal_qa_issue(
        repos=repos,
        store_id=store_id,
        description="Refrigerated case temp excursion; possible spoilage risk",
        severity="high",
        time_window={"start": "2026-05-07T18:00:00Z", "end": "2026-05-08T06:00:00Z"},
    )

    rc = repos.recalls.get_recall_case(uuid.UUID(recall_case_id))
    assert rc is not None
    assert rc.state.value == "signal_detected"
    assert rc.source_type == "retailer_internal"
    assert rc.store_id == store_id


def test_phase3_dedup_same_openfda_recall_number_is_idempotent(repos) -> None:
    router = NoticeRouter(repos=repos, verifier=SourceVerifier())

    import json

    record = json.loads(_fixture_json_paths()[0].read_text(encoding="utf-8"))
    notice = map_openfda_record_to_notice(record)
    router.ingest_notice(notice)
    router.ingest_notice(notice)
    assert repos.recalls.count_raw_recall_notices() == 1


def test_phase3_schema_robustness_malformed_fixtures_ingest(repos) -> None:
    router = NoticeRouter(repos=repos, verifier=SourceVerifier())

    import json

    malformed = {
        "01_F-0399-2025.json",
        "02_F-0729-2025.json",
        "03_H-0270-2026.json",
        "04_H-0030-2025.json",
        "05_H-0286-2026.json",
    }
    for p in _fixture_json_paths():
        if p.name not in malformed:
            continue
        record = json.loads(p.read_text(encoding="utf-8"))
        notice = map_openfda_record_to_notice(record)
        res = router.ingest_notice(notice)
        assert res.stored_as == "raw_recall_notice"
        assert res.verified is True


@pytest.mark.skipif(os.getenv("PHEROMONE_LIVE_API_TESTS") != "1", reason="live API tests disabled")
def test_phase3_live_openfda_pull_recent_returns_records() -> None:
    # This test is intentionally not DB-backed; it validates API availability.
    rows = pull_recent_fda_recalls(days=7, limit=25)
    assert len(rows) >= 1
