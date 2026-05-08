from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.db.models import NotificationDraft, RecallCase


def test_concurrent_notification_drafts_inserts_no_deadlock(engine) -> None:
    with Session(engine) as s:
        rc = RecallCase()
        s.add(rc)
        s.commit()
        recall_case_id = rc.id

    def _insert_one(i: int) -> None:
        with Session(engine) as s2:
            s2.add(
                NotificationDraft(
                    recall_case_id=recall_case_id,
                    customer_id=None,
                    channel="email",
                    confidence_tier="confirmed_unaffected",
                    draft={"i": i, "created_at": datetime.now(tz=timezone.utc).isoformat()},
                )
            )
            s2.commit()

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        futures = [ex.submit(_insert_one, i) for i in range(100)]
        for f in futures:
            f.result(timeout=30)
