from __future__ import annotations

from datetime import datetime, timezone


def test_recall_repository_round_trip_crud(repos) -> None:
    recall_case_id = repos.recalls.create_recall_case()

    got = repos.recalls.get_recall_case(recall_case_id)
    assert got is not None

    spec_id = repos.recalls.attach_spec(
        recall_case_id,
        {
            "source": "internal",
            "external_id": None,
            "title": "Test Recall",
            "summary": "Test",
            "published_at_utc": datetime(2026, 5, 1, tzinfo=timezone.utc).isoformat(),
            "affected_upcs": [],
            "affected_facility_ids": [],
            "affected_ingredient_lot_ids": [],
        },
    )
    assert spec_id

    repos.recalls.update_recall_case_state(recall_case_id, "intake_parsed")
    got2 = repos.recalls.get_recall_case(recall_case_id)
    assert got2 is not None
    assert got2.state.value == "intake_parsed"

    repos.recalls.delete_recall_case(recall_case_id)
    got3 = repos.recalls.get_recall_case(recall_case_id)
    assert got3 is None
