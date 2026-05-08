from __future__ import annotations

import json
import re
from pathlib import Path
import os

import httpx

import pytest

from backend.agents.intake_agent import HazardType, IntakeAgent, RecallSpec, Severity, VllmClientConfig
from backend.integrations.openfda import map_openfda_record_to_notice
from backend.integrations.schemas import RawRecallNoticeIn


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "real_recalls"
SUPPLIER_INBOX_DIR = Path(__file__).parents[1] / "integrations" / "supplier_inbox"


def _fixture_json_paths() -> list[Path]:
    paths = sorted([p for p in FIXTURES_DIR.glob("*.json") if not p.name.startswith("_")])
    assert len(paths) == 25
    return paths


def _agent() -> IntakeAgent:
    mode = os.getenv("PHEROMONE_LLM_MODE", "mock").strip().lower()
    if mode == "real":
        base_url = os.getenv("VLLM_BASE_URL", "").strip()
        assert base_url, "PHEROMONE_LLM_MODE=real requires VLLM_BASE_URL"
        model = os.getenv("VLLM_QWEN3_32B_MODEL", "Qwen/Qwen3-32B").strip() or "Qwen/Qwen3-32B"
        return IntakeAgent(VllmClientConfig(base_url=base_url, model=model))

    # Default: in-process mock transport that returns RecallSpec-shaped JSON (exercises the LLM path without binding sockets).
    from backend.mock_vllm_server import _build_recall_spec_like_json

    def handler(request: httpx.Request) -> httpx.Response:
        req = json.loads(request.content.decode("utf-8"))
        messages = req.get("messages") or []
        last_user = ""
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "user":
                last_user = str(m.get("content") or "")
                break
        model = req.get("model") or "Qwen/Qwen3-32B"
        payload = {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(_build_recall_spec_like_json(last_user))}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="http://mock.local", timeout=10.0)
    return IntakeAgent(VllmClientConfig(base_url="http://mock.local", model="Qwen/Qwen3-32B"), client=client)


def _load_index_ground_truth() -> dict[str, tuple[HazardType, Severity]]:
    """
    Parses backend/tests/fixtures/real_recalls/INDEX.md and returns:
      filename -> (hazard_type, severity)
    """
    idx_path = FIXTURES_DIR / "INDEX.md"
    lines = idx_path.read_text(encoding="utf-8").splitlines()
    gt: dict[str, tuple[HazardType, Severity]] = {}
    for ln in lines:
        if not ln.startswith("| `") or ".json`" not in ln:
            continue
        # | `01_foo.json` | ... | hazard | severity | ...
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        filename = cells[0].strip("`")
        hazard_s = cells[3].strip()
        severity_s = cells[4].strip()
        try:
            gt[filename] = (HazardType(hazard_s), Severity(severity_s))
        except Exception:
            continue
    assert len(gt) == 25
    return gt


def _critical_conf(spec: RecallSpec) -> float:
    conf = spec.extraction_confidence
    return min(conf.get("product_identifiers", 0.0), conf.get("hazard_type", 0.0), conf.get("severity", 0.0))


def test_phase4_intake_openfda_25_fixtures_high_confidence() -> None:
    agent = _agent()
    good = 0
    for p in _fixture_json_paths():
        record = json.loads(p.read_text(encoding="utf-8"))
        notice = map_openfda_record_to_notice(record)
        spec = agent.parse(notice)
        assert spec.recall_id == (notice.external_id or "unknown")
        assert spec.source_type == "openfda"
        assert spec.raw_notice_text == notice.raw_text
        assert isinstance(spec.product_identifiers, list)
        assert isinstance(spec.extraction_confidence, dict)
        if _critical_conf(spec) > 0.8:
            good += 1
    assert good >= 20


def test_phase4_intake_malformed_fixtures_low_confidence_flags() -> None:
    agent = _agent()
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
        spec = agent.parse(notice)
        # These fixtures are missing/garbled key fields; agent should route them to human review.
        assert spec.requires_human_review is True
        # Never fabricate: if product description missing, product_identifiers can be empty.
        if not (record.get("product_description") or "").strip():
            assert spec.product_identifiers == []


def test_phase4_intake_supplier_inbox_extracts_product_lot_hazard_severity() -> None:
    agent = _agent()
    paths = sorted([p for p in SUPPLIER_INBOX_DIR.glob("*.txt") if p.is_file()])
    assert len(paths) == 5

    expectations: dict[str, HazardType] = {
        "01_clean_ingredient_recall.txt": HazardType.salmonella,
        "02_ambiguous_lot_codes.txt": HazardType.other,  # investigation; hazard unknown
        "03_multi_product_implication.txt": HazardType.allergen,
        "04_packaging_issue.txt": HazardType.other,
        "05_retraction_prior_notice.txt": HazardType.other,
    }

    for p in paths:
        raw_text = p.read_text(encoding="utf-8")
        notice = RawRecallNoticeIn(
            source_type="supplier",
            external_id=p.stem,
            source_url=None,
            published_at_utc=None,
            raw_json={},
            raw_text=raw_text,
        )
        spec = agent.parse(notice)
        assert spec.source_type == "supplier"
        assert len(spec.product_identifiers) >= 1
        assert spec.hazard_type == expectations[p.name]
        assert spec.severity in {Severity.critical, Severity.high, Severity.medium, Severity.low, Severity.unknown}

    # Spot-check a couple of key extractions.
    spec1 = agent.parse(
        RawRecallNoticeIn(source_type="supplier", external_id="01", raw_text=paths[0].read_text(encoding="utf-8"), raw_json={})
    )
    assert any("NV-CU-041526-A" in lc.value for lc in spec1.lot_codes)
    assert "CA" in spec1.affected_distribution


def test_phase4_intake_internal_trigger_normalizes_without_fetch() -> None:
    agent = _agent()
    notice = RawRecallNoticeIn(
        source_type="retailer_internal",
        external_id="store-4-fridge",
        source_url=None,
        published_at_utc=None,
        raw_json={"time_window": {"start": "2026-05-07T18:00:00Z", "end": "2026-05-08T06:00:00Z"}},
        raw_text="Refrigerated case temp excursion; possible spoilage risk",
    )
    spec = agent.parse(notice)
    assert spec.source_type == "retailer_internal"
    assert len(spec.product_identifiers) >= 1
    assert spec.hazard_type in {HazardType.other, HazardType.foreign_object}


def test_phase4_intake_hazard_and_severity_against_ground_truth() -> None:
    agent = _agent()
    gt = _load_index_ground_truth()
    correct_hazard = 0
    correct_severity = 0

    for p in _fixture_json_paths():
        record = json.loads(p.read_text(encoding="utf-8"))
        notice = map_openfda_record_to_notice(record)
        spec = agent.parse(notice)

        expected_hazard, expected_severity = gt[p.name]
        if spec.hazard_type == expected_hazard:
            correct_hazard += 1
        if spec.severity == expected_severity:
            correct_severity += 1

    assert correct_hazard >= 23
    assert correct_severity >= 22


def test_phase4_intake_idempotency_structured_fields_stable() -> None:
    agent = _agent()
    record = json.loads(_fixture_json_paths()[10].read_text(encoding="utf-8"))
    notice = map_openfda_record_to_notice(record)
    a = agent.parse(notice)
    b = agent.parse(notice)
    assert a.model_dump(exclude={"parsed_at"}) == b.model_dump(exclude={"parsed_at"})


def test_phase4_intake_no_pii_in_structured_output_fields() -> None:
    agent = _agent()
    email_fixture = (SUPPLIER_INBOX_DIR / "01_clean_ingredient_recall.txt").read_text(encoding="utf-8")
    notice = RawRecallNoticeIn(source_type="supplier", external_id="pii-test", raw_text=email_fixture, raw_json={})
    spec = agent.parse(notice)

    pii_re = re.compile(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,})|(\\b\\d{3}[\\s.-]?\\d{3}[\\s.-]?\\d{4}\\b)")
    structured_text = " ".join(
        [
            spec.hazard_details,
            spec.remedy_instructions,
            " ".join(spec.affected_distribution),
            " ".join(spec.affected_facilities),
            " ".join(pi.product_name for pi in spec.product_identifiers),
        ]
    )
    assert pii_re.search(structured_text) is None
