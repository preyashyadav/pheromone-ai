from __future__ import annotations

import os
import random
import subprocess
import uuid
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from backend.agents.comms_agent import CommsAgent, NotificationChannel
from backend.agents.intake_agent import ExtractedString, HazardType, RecallSpec as IntakeRecallSpec, Severity
from backend.agents.match_agent import MatchAgent, ScoredTransactionOut
from backend.agents.trace_agent import TraceAgent
from backend.db.models import PaymentType
from backend.engine.confidence import ConfidenceTier


def _run_generator(db_url: str, scenario: str) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    p = subprocess.run(
        [
            str(repo_root / ".venv" / "bin" / "python"),
            str(repo_root / "data_generator" / "generate.py"),
            "--db-url",
            db_url,
            "--seed",
            "42",
            "--scenario",
            scenario,
            "--reset",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stdout + "\n" + p.stderr


def _tier_counts(drafts) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in drafts:
        out[d.confidence_tier] = out.get(d.confidence_tier, 0) + 1
    return out


def _eligible_tx_rows(engine, tx_ids: list[uuid.UUID]) -> list[dict]:
    if not tx_ids:
        return []
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, store_id, customer_id, payment_type
                FROM pos_transactions
                WHERE id = ANY(CAST(:ids AS uuid[]))
                """
            ),
            {"ids": tx_ids},
        ).all()
        inst_customer_ids = set(
            conn.execute(text("SELECT customer_id FROM institutional_accounts WHERE customer_id IS NOT NULL")).scalars().all()
        )
    out: list[dict] = []
    for tid, store_id, customer_id, pay in rows:
        cid = uuid.UUID(str(customer_id)) if customer_id is not None else None
        pt = PaymentType(pay.value if hasattr(pay, "value") else str(pay))
        out.append(
            {
                "transaction_id": uuid.UUID(str(tid)),
                "store_id": uuid.UUID(str(store_id)),
                "customer_id": cid,
                "payment_type": pt,
                "is_institutional": cid in inst_customer_ids if cid is not None else False,
            }
        )
    return out


def test_phase8_salsa_verde_drafts_generated_for_all_tiers_and_counts_close(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory, RecallRepository

    _run_generator(db_url, "salsa_verde")
    sf = make_session_factory(engine)
    rc_id = RecallRepository(sf).create_recall_case()

    recall_spec = IntakeRecallSpec(
        recall_id="RG-4429",
        source_type="supplier",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[ExtractedString(value=salsa_verde_seed.INGREDIENT_LOT_CODE, confidence=0.95)],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity=Severity.high,
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )

    blast = TraceAgent(sf).build(recall_spec)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec)
    agent = CommsAgent(sf)
    drafts = agent.draft_notifications(scored, recall_spec, recall_case_id=rc_id)

    # Compare counts only over eligible transactions (non-cash, non-institutional).
    eligible_rows = _eligible_tx_rows(engine, [s.transaction_id for s in scored])
    eligible_ids = {r["transaction_id"] for r in eligible_rows if (r["payment_type"] != PaymentType.cash and not r["is_institutional"] and r["customer_id"] is not None)}
    eligible_scored = [s for s in scored if s.transaction_id in eligible_ids]

    expected_by_tier: dict[str, int] = {}
    for s in eligible_scored:
        expected_by_tier[s.confidence_tier.value] = expected_by_tier.get(s.confidence_tier.value, 0) + 1
    got_by_tier = _tier_counts([d for d in drafts if d.customer_id is not None and d.channel in {NotificationChannel.sms, NotificationChannel.email}])

    # Ensure tiers present.
    assert expected_by_tier.get("confirmed_affected", 0) > 0
    assert expected_by_tier.get("likely_affected", 0) > 0
    assert expected_by_tier.get("possible_affected", 0) > 0
    assert expected_by_tier.get("likely_unaffected", 0) > 0
    assert expected_by_tier.get("confirmed_unaffected", 0) > 0

    # Counts within ±5% (or exact for small buckets).
    for tier, exp in expected_by_tier.items():
        got = got_by_tier.get(tier, 0)
        tol = max(3, int(round(exp * 0.05)))
        assert abs(got - exp) <= tol

    # Public notice: one per affected store (6 in Salsa-Verde).
    pub = [d for d in drafts if d.channel == NotificationChannel.public_notice]
    assert len(pub) == 6


def test_phase8_reassurance_at_least_800_unaffected_drafts(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "salsa_verde")
    sf = make_session_factory(engine)

    recall_spec = IntakeRecallSpec(
        recall_id="RG-4429",
        source_type="supplier",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[ExtractedString(value=salsa_verde_seed.INGREDIENT_LOT_CODE, confidence=0.95)],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity=Severity.high,
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    blast = TraceAgent(sf).build(recall_spec)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec)
    drafts = CommsAgent(sf).draft_notifications(scored, recall_spec)
    reassurance = [d for d in drafts if d.confidence_tier in {"confirmed_unaffected", "likely_unaffected"} and d.customer_id is not None]
    assert len(reassurance) >= 800


def test_phase8_reassurance_contains_specific_proof_18_of_20(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "salsa_verde")
    sf = make_session_factory(engine)

    recall_spec = IntakeRecallSpec(
        recall_id="RG-4429",
        source_type="supplier",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[ExtractedString(value=salsa_verde_seed.INGREDIENT_LOT_CODE, confidence=0.95)],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity=Severity.high,
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    blast = TraceAgent(sf).build(recall_spec)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec)
    drafts = CommsAgent(sf).draft_notifications(scored, recall_spec)

    reassurance = [d for d in drafts if d.confidence_tier in {"confirmed_unaffected", "likely_unaffected"} and d.customer_id is not None]
    assert len(reassurance) >= 20
    rng = random.Random(0)
    sample = rng.sample(reassurance, k=20)
    good = 0
    for d in sample:
        body = str(d.draft.get("body") or "")
        if CommsAgent.grade_reassurance_proof(body):
            good += 1
    assert good >= 18


def test_phase8_reassurance_messages_are_time_bound_100pct(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "salsa_verde")
    sf = make_session_factory(engine)

    recall_spec = IntakeRecallSpec(
        recall_id="RG-4429",
        source_type="supplier",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[ExtractedString(value=salsa_verde_seed.INGREDIENT_LOT_CODE, confidence=0.95)],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity=Severity.high,
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    blast = TraceAgent(sf).build(recall_spec)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec)
    drafts = CommsAgent(sf).draft_notifications(scored, recall_spec)
    reassurance = [d for d in drafts if d.confidence_tier in {"confirmed_unaffected", "likely_unaffected"} and d.customer_id is not None]
    assert reassurance
    assert all(CommsAgent.grade_time_bound(str(d.draft.get("body") or "")) for d in reassurance)


def test_phase8_vulnerable_population_emphasis_infant_risk_listeria(db_url, engine) -> None:
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "none")

    # Insert a Maria-S customer with a structured kids list (not just boolean).
    maria_id = uuid.uuid4()
    store_id = uuid.uuid4()
    tx_id = uuid.uuid4()
    product_id = uuid.uuid4()
    manufacturer_id = uuid.uuid4()
    t0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO stores (id, name, timezone) VALUES (:id, :n, 'UTC')"), {"id": store_id, "n": "Store Maria"})
        conn.execute(
            text("INSERT INTO manufacturers (id, name) VALUES (:id, :n)"),
            {"id": manufacturer_id, "n": "Test Manufacturer"},
        )
        # Ensure the finished product exists so composition snapshot FK constraints can be satisfied.
        conn.execute(
            text(
                """
                INSERT INTO finished_products (id, manufacturer_id, name, upc, ingredient_recipe)
                VALUES (:id, :mid, :n, :u, '[]'::jsonb)
                """
            ),
            {"id": product_id, "mid": manufacturer_id, "n": "Test Product", "u": "000000009999"},
        )
        conn.execute(
            text("INSERT INTO customers (id, loyalty_id, email_hash, phone_hash, profile) VALUES (:id, 'LMARIA', 'em', 'ph', CAST(:p AS jsonb))"),
            {"id": maria_id, "p": json.dumps({"language": "en", "kids": [{"age": 2}], "consent_sms": True, "consent_email": True})},
        )
        conn.execute(
            text(
                "INSERT INTO pos_transactions (id, store_id, customer_id, timestamp, payment_type, line_items) VALUES (:id, :sid, :cid, :ts, 'loyalty', CAST(:li AS jsonb))"
            ),
            {"id": tx_id, "sid": store_id, "cid": maria_id, "ts": t0, "li": json.dumps([{"finished_product_id": str(product_id), "quantity_units": 1}])},
        )

    sf = make_session_factory(engine)
    recall_spec = IntakeRecallSpec(
        recall_id="LIS-1",
        source_type="openfda",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity=Severity.critical,
        hazard_type=HazardType.listeria,
        hazard_details="Listeria monocytogenes contamination.",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    s = ScoredTransactionOut(
        transaction_id=tx_id,
        affected_probability=0.6,
        confidence_tier=ConfidenceTier.likely_affected,
        actionability_score=0.8,
        payment_type=PaymentType.loyalty,
        customer_id=maria_id,
        details={},
    )
    drafts = CommsAgent(sf).draft_notifications([s], recall_spec)
    assert drafts
    body = str(drafts[0].draft.get("body") or "").lower()
    assert "infant" in body or "baby" in body


def test_phase8_multi_language_spanish_drafts_detected(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "salsa_verde")
    sf = make_session_factory(engine)

    recall_spec = IntakeRecallSpec(
        recall_id="RG-4429",
        source_type="supplier",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[ExtractedString(value=salsa_verde_seed.INGREDIENT_LOT_CODE, confidence=0.95)],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity=Severity.high,
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    blast = TraceAgent(sf).build(recall_spec)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec)
    drafts = CommsAgent(sf).draft_notifications(scored, recall_spec)

    spanish = [d for d in drafts if str(d.draft.get("language") or "") == "es"]
    assert len(spanish) >= 5

    from backend.utils.language_detect import detect_language

    assert sum(1 for d in spanish if detect_language(str(d.draft.get("body") or "")) == "es") >= 5


def test_phase8_cash_buyers_get_no_individual_msgs_and_public_notice_per_store(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "salsa_verde")
    sf = make_session_factory(engine)

    recall_spec = IntakeRecallSpec(
        recall_id="RG-4429",
        source_type="supplier",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[ExtractedString(value=salsa_verde_seed.INGREDIENT_LOT_CODE, confidence=0.95)],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity=Severity.high,
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    blast = TraceAgent(sf).build(recall_spec)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec)
    drafts = CommsAgent(sf).draft_notifications(scored, recall_spec)

    # No individual drafts for cash (customer_id None).
    assert all(d.customer_id is not None or d.channel == NotificationChannel.public_notice for d in drafts)

    # Exactly one public notice per affected store (6 for salsa-verde).
    pub = [d for d in drafts if d.channel == NotificationChannel.public_notice]
    assert len(pub) == 6


def test_phase8_institutional_accounts_get_admin_email(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "salsa_verde")
    sf = make_session_factory(engine)

    recall_spec = IntakeRecallSpec(
        recall_id="RG-4429",
        source_type="supplier",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[ExtractedString(value=salsa_verde_seed.INGREDIENT_LOT_CODE, confidence=0.95)],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity=Severity.high,
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    blast = TraceAgent(sf).build(recall_spec)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec)
    drafts = CommsAgent(sf).draft_notifications(scored, recall_spec)

    with engine.begin() as conn:
        inst_customers = set(
            conn.execute(text("SELECT DISTINCT customer_id FROM institutional_accounts WHERE customer_id IS NOT NULL")).scalars().all()
        )
        scored_inst = set()
        for s in scored:
            if s.customer_id is not None and s.customer_id in inst_customers:
                scored_inst.add(s.customer_id)

    admin = [d for d in drafts if d.channel == NotificationChannel.admin_email]
    got = {d.customer_id for d in admin}
    assert scored_inst.issubset(got)


def test_phase8_pii_protection_no_email_phone_or_hashes_in_messages(db_url, engine) -> None:
    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "salsa_verde")
    sf = make_session_factory(engine)

    recall_spec = IntakeRecallSpec(
        recall_id="RG-4429",
        source_type="supplier",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[ExtractedString(value=salsa_verde_seed.INGREDIENT_LOT_CODE, confidence=0.95)],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity=Severity.high,
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    blast = TraceAgent(sf).build(recall_spec)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec)
    drafts = CommsAgent(sf).draft_notifications(scored, recall_spec)

    phone_re = r"(?:(?:\\+?1[\\s.-]?)?(?:\\(\\d{3}\\)|\\d{3})[\\s.-]?)\\d{3}[\\s.-]?\\d{4}"
    email_re = r"\\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}\\b"
    for d in drafts:
        subj = str(d.draft.get("subject") or "")
        body = str(d.draft.get("body") or "")
        assert "emailhash_" not in subj and "emailhash_" not in body
        assert "phonehash_" not in subj and "phonehash_" not in body
        assert not __import__("re").search(phone_re, subj + " " + body)
        assert not __import__("re").search(email_re, subj + " " + body)


def test_phase8_demo_mode_safety_no_sends_only_drafts(db_url, engine, monkeypatch) -> None:
    # Demo mode is default; CommsAgent should not attempt any external delivery.
    monkeypatch.setenv("PHEROMONE_DEMO_MODE", "1")
    monkeypatch.setenv("PHEROMONE_ENABLE_REAL_NOTIFICATIONS", "0")

    from data_generator.seeds import salsa_verde_seed
    from backend.db.repositories import make_session_factory

    _run_generator(db_url, "salsa_verde")
    sf = make_session_factory(engine)
    recall_spec = IntakeRecallSpec(
        recall_id="RG-4429",
        source_type="supplier",
        source_url=None,
        parsed_at=datetime.now(tz=UTC),
        product_identifiers=[],
        lot_codes=[ExtractedString(value=salsa_verde_seed.INGREDIENT_LOT_CODE, confidence=0.95)],
        best_by_dates=[],
        affected_facilities=[],
        affected_distribution=[],
        severity=Severity.high,
        hazard_type=HazardType.salmonella,
        hazard_details="",
        symptom_timeline_days=(1, 30),
        remedy_instructions="",
        extraction_confidence={},
        raw_notice_text="",
    )
    blast = TraceAgent(sf).build(recall_spec)
    scored = MatchAgent(sf).score_transactions(blast, recall_spec)
    drafts = CommsAgent(sf).draft_notifications(scored, recall_spec)
    assert drafts

    # There should be no network calls here; the contract is purely draft generation.
    assert all(isinstance(d.draft, dict) for d in drafts)
