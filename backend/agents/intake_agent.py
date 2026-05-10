from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import calendar
import enum
import json
import os
import re
from typing import Any, Iterable, Mapping

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Severity(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    unknown = "unknown"


class HazardType(str, enum.Enum):
    salmonella = "salmonella"
    listeria = "listeria"
    ecoli = "ecoli"
    allergen = "allergen"
    foreign_object = "foreign_object"
    undeclared_ingredient = "undeclared_ingredient"
    other = "other"


class ProductIdentifier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand: str | None = None
    product_name: str = ""
    upc: str | None = None
    package_size: str | None = None
    image_url: HttpUrl | None = None


class ExtractedString(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    confidence: float = Field(ge=0.0, le=1.0)


class DateRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date | None = None
    end: date | None = None


class RecallSpec(BaseModel):
    """
    Structured intake output contract.

    Note: `raw_notice_text` intentionally preserves original content for audit even if it contains PII.
    All other free-text fields are redacted.
    """

    model_config = ConfigDict(extra="forbid")

    recall_id: str
    source_type: str
    source_url: str | None = None
    parsed_at: datetime

    product_identifiers: list[ProductIdentifier] = Field(default_factory=list)
    lot_codes: list[ExtractedString] = Field(default_factory=list)
    best_by_dates: list[DateRange] = Field(default_factory=list)
    affected_facilities: list[str] = Field(default_factory=list)
    affected_distribution: list[str] = Field(default_factory=list)

    severity: Severity = Severity.unknown
    hazard_type: HazardType = HazardType.other
    hazard_details: str = ""
    symptom_timeline_days: tuple[int | None, int | None] = (None, None)
    remedy_instructions: str = ""

    extraction_confidence: dict[str, float] = Field(default_factory=dict)
    requires_human_review: bool = False

    raw_notice_text: str = ""


@dataclass(frozen=True)
class VllmClientConfig:
    base_url: str = "http://127.0.0.1:8001"
    model: str = "Qwen/Qwen3-32B"
    api_key: str | None = None
    timeout_s: float = 60.0


_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
_PHONE_RE = re.compile(r"(?:(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?)\d{3}[\s.-]?\d{4}\b")
_UPC_RE = re.compile(r"\b\d{12}\b")


def _redact_pii(text: str) -> str:
    if not text:
        return ""
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _PHONE_RE.sub("[REDACTED_PHONE]", text)
    return text


def _safe_float(v: Any, *, default: float) -> float:
    try:
        f = float(v)
        if f != f:  # NaN
            return default
        return max(0.0, min(1.0, f))
    except Exception:
        return default


def _get_notice_attr(raw_notice: Any, name: str) -> Any:
    if hasattr(raw_notice, name):
        return getattr(raw_notice, name)
    if isinstance(raw_notice, Mapping):
        return raw_notice.get(name)
    return None


def _notice_raw_text(raw_notice: Any) -> str:
    return str(_get_notice_attr(raw_notice, "raw_text") or "")


def _notice_raw_json(raw_notice: Any) -> dict[str, Any]:
    raw = _get_notice_attr(raw_notice, "raw_json")
    return raw if isinstance(raw, dict) else {}


def _notice_source_type(raw_notice: Any) -> str:
    return str(_get_notice_attr(raw_notice, "source_type") or "")


def _notice_source_url(raw_notice: Any) -> str | None:
    url = _get_notice_attr(raw_notice, "source_url")
    return str(url) if isinstance(url, str) and url.strip() else None


def _notice_external_id(raw_notice: Any) -> str | None:
    v = _get_notice_attr(raw_notice, "external_id")
    return str(v) if isinstance(v, str) and v.strip() else None


def _notice_published_at(raw_notice: Any) -> datetime | None:
    v = _get_notice_attr(raw_notice, "published_at_utc") or _get_notice_attr(raw_notice, "published_at")
    return v if isinstance(v, datetime) else None


def _notice_created_at(raw_notice: Any) -> datetime | None:
    v = _get_notice_attr(raw_notice, "created_at")
    return v if isinstance(v, datetime) else None


def _parse_openfda_classification(value: str | None) -> Severity:
    if not value:
        return Severity.unknown
    v = value.strip().lower()
    if v.startswith("class ii"):
        return Severity.high
    if v.startswith("class i"):
        return Severity.critical
    if v.startswith("class iii"):
        return Severity.medium
    return Severity.unknown


_ALLERGEN_KEYWORDS = {
    "milk",
    "egg",
    "eggs",
    "wheat",
    "soy",
    "soya",
    "peanut",
    "peanuts",
    "tree nut",
    "almond",
    "almonds",
    "sesame",
    "fish",
    "shellfish",
}


def _infer_hazard_type(text: str) -> HazardType:
    t = (text or "").lower()
    if "salmonella" in t:
        return HazardType.salmonella
    if "listeria" in t:
        return HazardType.listeria
    if "e. coli" in t or "e coli" in t or "ecoli" in t:
        return HazardType.ecoli
    if "undeclared" in t or "allergen" in t:
        if any(k in t for k in _ALLERGEN_KEYWORDS):
            return HazardType.allergen
        return HazardType.undeclared_ingredient
    if "metal" in t or "glass" in t or "plastic" in t or "foreign object" in t or "foreign material" in t:
        return HazardType.foreign_object
    if "misbrand" in t or "misbranded" in t or "nutrition facts" in t or ("label" in t and "undeclared" in t):
        return HazardType.undeclared_ingredient
    return HazardType.other


def _extract_upcs(text: str) -> list[str]:
    return list(dict.fromkeys(_UPC_RE.findall(text or "")))


def _split_product_chunks(product_description: str) -> list[str]:
    if not product_description.strip():
        return []
    # openFDA product_description sometimes includes multiple products on one line separated by UPC markers.
    chunks = re.split(r"\bUPC\b", product_description, flags=re.IGNORECASE)
    cleaned = [c.strip(" -\t\n\r") for c in chunks if c.strip()]
    # If split yields too many tiny chunks, fall back to the whole string.
    if len(cleaned) >= 2 and all(len(c) < 15 for c in cleaned):
        return [product_description.strip()]
    return cleaned[:10]


def _make_products_from_openfda(record: Mapping[str, Any]) -> list[ProductIdentifier]:
    desc = str(record.get("product_description") or "").strip()
    if not desc:
        return []
    upcs = _extract_upcs(desc)
    chunks = _split_product_chunks(desc)
    products: list[ProductIdentifier] = []
    for i, chunk in enumerate(chunks):
        upc = upcs[i] if i < len(upcs) else (upcs[0] if upcs else None)
        products.append(ProductIdentifier(product_name=chunk[:500].strip(), upc=upc))
    return products or [ProductIdentifier(product_name=desc[:500].strip(), upc=upcs[0] if upcs else None)]


_LOT_TOKEN_RE = re.compile(r"\b[A-Z0-9][A-Z0-9-]{3,}\b")


def _extract_lot_codes(text: str) -> list[ExtractedString]:
    if not text:
        return []
    candidates: list[ExtractedString] = []
    # Priority: text following explicit markers.
    marker_re = re.compile(r"(?i)\b(lot|lots|lot code|lot codes|batch|batch codes)\b[:\s]*([^\n]+)")
    for m in marker_re.finditer(text):
        tail = m.group(2)[:400]
        for tok in _LOT_TOKEN_RE.findall(tail.upper()):
            if tok in {"USA", "CANADA"}:
                continue
            candidates.append(ExtractedString(value=tok, confidence=0.85))

    # Fallback: scan the whole text for plausible codes, but lower confidence.
    if not candidates:
        for tok in _LOT_TOKEN_RE.findall(text.upper()):
            if tok in {"USA", "CANADA"}:
                continue
            if tok.isdigit() and len(tok) == 12:  # UPC-like
                continue
            candidates.append(ExtractedString(value=tok, confidence=0.6))

    dedup: dict[str, ExtractedString] = {}
    for c in candidates:
        prev = dedup.get(c.value)
        if prev is None or c.confidence > prev.confidence:
            dedup[c.value] = c
    return list(dedup.values())[:30]


_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _parse_date_token(token: str) -> date | None:
    t = token.strip()
    if not t:
        return None
    # 2026-05-08
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(t, fmt).date()
        except Exception:
            pass
    # OCT 01 2024
    m = re.match(r"(?i)^\s*([A-Z]{3,4})\s+(\d{1,2})\s+(\d{4})\s*$", t)
    if m:
        mon = _MONTHS.get(m.group(1).lower())
        if mon:
            try:
                return date(int(m.group(3)), int(mon), int(m.group(2)))
            except Exception:
                return None
    return None


_MONTH_YEAR_RE = re.compile(
    r"(?i)\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)[A-Z]*[\s\-\/]+(\d{4})\b"
)


def _month_year_range(token: str) -> DateRange | None:
    m = _MONTH_YEAR_RE.search(token or "")
    if not m:
        return None

    mon = m.group(1).upper()
    year = int(m.group(2))
    month_map = {
        "JAN": 1,
        "FEB": 2,
        "MAR": 3,
        "APR": 4,
        "MAY": 5,
        "JUN": 6,
        "JUL": 7,
        "AUG": 8,
        "SEP": 9,
        "SEPT": 9,
        "OCT": 10,
        "NOV": 11,
        "DEC": 12,
    }
    month = month_map.get(mon)
    if not month:
        return None
    last = calendar.monthrange(year, month)[1]
    return DateRange(start=date(year, month, 1), end=date(year, month, last))


def _extract_best_by_ranges(text: str) -> list[DateRange]:
    if not text:
        return []
    ranges: list[DateRange] = []
    # "Best By Dates: OCT 01 2024 to OCT 11 2025"
    m = re.search(r"(?i)\bbest\s*by\s*dates?\b[:\s]*([^\n]+)", text)
    if m:
        tail = m.group(1)
        parts = re.split(r"(?i)\bto\b|-|—|–", tail)
        if len(parts) >= 2:
            start = _parse_date_token(parts[0])
            end = _parse_date_token(parts[1])
            if start or end:
                ranges.append(DateRange(start=start, end=end))
        else:
            end = _parse_date_token(tail)
            if end:
                ranges.append(DateRange(start=None, end=end))
    # "Best By: 04/15/2027"
    m2 = re.search(r"(?i)\bbest\s*by\b[:\s]+([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}|[A-Z]{3,4}\\s+\\d{1,2}\\s+\\d{4}|\\d{4}-\\d{2}-\\d{2})", text)
    if m2:
        end = _parse_date_token(m2.group(1))
        if end:
            ranges.append(DateRange(start=None, end=end))

    # Month-year token (e.g., "Use by : JULY-2027").
    if not ranges:
        my = _month_year_range(text)
        if my:
            ranges.append(my)
    return ranges


def _distribution_to_list(text: str) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    # Keep as a single entry unless there are obvious separators.
    parts = [p.strip(" -\t") for p in re.split(r"[;\n]+", t) if p.strip()]
    return parts[:20]


_FACILITY_RE = re.compile(r"\b([A-Z]{2,4}-\d{1,3})\b")


def _extract_facility_codes(text: str) -> list[str]:
    if not text:
        return []
    codes = [m.group(1) for m in _FACILITY_RE.finditer(text.upper())]
    # Normalize repeated.
    return list(dict.fromkeys(codes))[:10]


def _extract_supplier_distribution(raw_text: str) -> list[str]:
    m = re.search(r"(?i)\bshipped\s+to\b:\s*([A-Z]{2}(?:\s*,\s*[A-Z]{2})+)", raw_text)
    if not m:
        return []
    states = [s.strip().upper() for s in m.group(1).split(",") if s.strip()]
    return states[:20]


def _baseline_extract(raw_notice: Any) -> RecallSpec:
    raw_json = _notice_raw_json(raw_notice)
    raw_text = _notice_raw_text(raw_notice)
    source_type = _notice_source_type(raw_notice)
    source_url = _notice_source_url(raw_notice)
    published_at = _notice_published_at(raw_notice)
    parsed_at = _notice_created_at(raw_notice) or published_at or datetime.now(tz=UTC)

    recall_id = (
        _notice_external_id(raw_notice)
        or str(raw_json.get("recall_number") or raw_json.get("event_id") or "").strip()
        or "unknown"
    )

    reason_val = raw_json.get("reason_for_recall")
    reason_s = reason_val if isinstance(reason_val, str) else ""
    hazard_text = str(reason_s or raw_text or "")
    hazard_type = _infer_hazard_type(hazard_text)

    severity = Severity.unknown
    if source_type == "openfda":
        severity = _parse_openfda_classification(str(raw_json.get("classification") or ""))
    elif "class i" in raw_text.lower() or "critical" in raw_text.lower():
        severity = Severity.critical
    elif "high" in raw_text.lower():
        severity = Severity.high
    elif "medium" in raw_text.lower():
        severity = Severity.medium
    elif "low" in raw_text.lower():
        severity = Severity.low
    elif "market withdrawal" in raw_text.lower() or "not a health hazard" in raw_text.lower():
        severity = Severity.low
    elif hazard_type in {HazardType.salmonella, HazardType.listeria, HazardType.ecoli}:
        severity = Severity.high
    elif hazard_type in {HazardType.allergen, HazardType.undeclared_ingredient, HazardType.foreign_object}:
        severity = Severity.medium

    products: list[ProductIdentifier] = []
    if source_type == "openfda":
        products = _make_products_from_openfda(raw_json)
    else:
        # Supplier/internal: first non-empty line is usually a subject-like product reference.
        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        if lines:
            products = [ProductIdentifier(product_name=lines[0][:500])]

    lot_codes = _extract_lot_codes(str(raw_json.get("code_info") or raw_text or ""))
    best_by = _extract_best_by_ranges(str(raw_json.get("code_info") or raw_text or ""))
    if source_type == "openfda":
        distribution = _distribution_to_list(str(raw_json.get("distribution_pattern") or ""))
    else:
        distribution = _extract_supplier_distribution(raw_text)

    facilities = _extract_facility_codes(str(raw_json.get("code_info") or "") + "\n" + raw_text)

    # Confidence: structured sources get high confidence by default.
    conf: dict[str, float] = {}
    prod_conf = 0.9 if products else 0.4
    if source_type == "openfda":
        prod_desc = str(raw_json.get("product_description") or "")
        code_info_val = raw_json.get("code_info")
        code_info_s = code_info_val if isinstance(code_info_val, str) else ""
        # Treat embedded HTML or very short code_info as a sign of messy input.
        if "<" in prod_desc or ">" in prod_desc:
            prod_conf = min(prod_conf, 0.55)
        if "***" in prod_desc or "supplement facts" in prod_desc.lower():
            prod_conf = min(prod_conf, 0.55)
        if not isinstance(code_info_val, str):
            prod_conf = min(prod_conf, 0.55)
        if not code_info_s.strip():
            prod_conf = min(prod_conf, 0.55)
    conf["product_identifiers"] = prod_conf
    if hazard_type != HazardType.other and reason_s.strip():
        conf["hazard_type"] = 0.95
    elif hazard_type != HazardType.other:
        conf["hazard_type"] = 0.75
    else:
        # If openFDA is missing reason_for_recall, treat hazard inference as low-confidence.
        if source_type == "openfda" and not reason_s.strip():
            conf["hazard_type"] = 0.55
        elif source_type == "openfda" and reason_s.strip():
            # openFDA usually provides a clear reason even when it's not one of our named hazard types.
            conf["hazard_type"] = 0.85
        else:
            ht = hazard_text.lower()
            if any(w in ht for w in ("investigating", "potential contamination", "potential issue", "concern")):
                conf["hazard_type"] = 0.55
            else:
                conf["hazard_type"] = 0.8 if hazard_text.strip() else 0.4
    conf["severity"] = 0.9 if severity != Severity.unknown else 0.55
    conf["lot_codes"] = 0.85 if lot_codes else 0.55
    conf["best_by_dates"] = 0.8 if best_by else 0.5
    conf["affected_distribution"] = 0.75 if distribution else 0.5

    hazard_details = _redact_pii(str(raw_json.get("reason_for_recall") or hazard_text or ""))
    remedy = ""
    if source_type == "retailer_internal":
        remedy = _redact_pii(raw_text[:800])

    spec = RecallSpec(
        recall_id=recall_id,
        source_type=source_type,
        source_url=source_url,
        parsed_at=parsed_at,
        product_identifiers=products,
        lot_codes=lot_codes,
        best_by_dates=best_by,
        affected_facilities=facilities,
        affected_distribution=distribution,
        severity=severity,
        hazard_type=hazard_type,
        hazard_details=hazard_details[:800],
        symptom_timeline_days=(None, None),
        remedy_instructions=remedy[:1000],
        extraction_confidence=conf,
        raw_notice_text=raw_text,
    )
    return spec


def _is_json_object(s: str) -> bool:
    st = (s or "").strip()
    return st.startswith("{") and st.endswith("}")


class IntakeAgent:
    """
    Phase 4: Intake Agent.

    Calls Qwen3-32B via vLLM (OpenAI-compatible) with JSON Schema constrained output.
    Falls back to deterministic extraction when the endpoint is unavailable or returns non-JSON.
    """

    def __init__(self, config: VllmClientConfig, *, client: httpx.Client | None = None) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=config.timeout_s, base_url=config.base_url)
        self.last_llm_usage: dict[str, Any] | None = None

    def parse(self, raw_notice: Any, *, related_notices: Iterable[Any] | None = None) -> RecallSpec:
        baseline = _baseline_extract(raw_notice)
        raw_text = baseline.raw_notice_text

        spec = self._try_llm_extract(baseline, raw_text) or baseline

        # Merge back deterministic/authoritative baseline signals for OpenFDA.
        if baseline.source_type == "openfda":
            raw_json = _notice_raw_json(raw_notice)
            classification = str(raw_json.get("classification") or "").strip()

            # 1) OpenFDA classification is authoritative for severity (when present).
            if classification and baseline.severity != Severity.unknown:
                conf = dict(spec.extraction_confidence)
                conf["severity"] = max(
                    _safe_float(conf.get("severity"), default=0.5),
                    _safe_float(baseline.extraction_confidence.get("severity"), default=0.5),
                )
                spec = spec.model_copy(update={"severity": baseline.severity, "extraction_confidence": conf})

            # 2) If baseline flagged "messy" product identifiers, don't let LLM override review gating.
            for key in ("product_identifiers", "hazard_type"):
                base_val = _safe_float(baseline.extraction_confidence.get(key), default=0.5)
                if base_val <= 0.55:
                    conf = dict(spec.extraction_confidence)
                    conf[key] = min(_safe_float(conf.get(key), default=0.5), base_val)
                    spec = spec.model_copy(update={"extraction_confidence": conf})

            # 3) If baseline extracted confident best-by dates (incl. month-year), prefer it for stability.
            base_bb_conf = _safe_float(baseline.extraction_confidence.get("best_by_dates"), default=0.5)
            if baseline.best_by_dates and base_bb_conf >= 0.8:
                conf = dict(spec.extraction_confidence)
                conf["best_by_dates"] = max(_safe_float(conf.get("best_by_dates"), default=0.5), base_bb_conf)
                spec = spec.model_copy(update={"best_by_dates": baseline.best_by_dates, "extraction_confidence": conf})

        if related_notices:
            spec = self._cross_check(spec, related_notices)

        spec = self._finalize(spec)
        return spec

    def _try_llm_extract(self, baseline: RecallSpec, raw_text: str) -> RecallSpec | None:
        # Escape hatch for development/test runs that explicitly want deterministic-only behavior.
        if os.getenv("PHEROMONE_INTAKE_SKIP_LLM", "").strip() == "1":
            return None

        schema = RecallSpec.model_json_schema()
        system_prompt = (
            "You are IntakeAgent for a grocery recall OS.\n"
            "Task: extract a RecallSpec from messy recall notices.\n"
            "Rules:\n"
            "- Never fabricate: if a field is unknown, leave it empty/unknown and lower confidence.\n"
            "- Do not include emails or phone numbers in any fields except raw_notice_text.\n"
            "- Provide extraction_confidence per field as floats 0.0-1.0.\n"
            "\n"
            "CRITICAL ANTI-HALLUCINATION:\n"
            "- If a field cannot be confidently extracted from the notice, leave it empty (empty list / empty string / unknown)\n"
            "  AND set its confidence < 0.50. Do NOT guess. Do NOT infer plausible-looking values.\n"
            "- Empty + low confidence is correct; fabricated + high confidence is a serious error.\n"
            "\n"
            "Confidence guidance:\n"
            "- >=0.95 : Appears verbatim in the notice (explicit UPC digits, exact lot code, stated FDA class).\n"
            "- 0.80-0.94 : Unambiguous from the notice text (e.g., 'tested positive Salmonella' -> hazard_type=salmonella).\n"
            "- 0.50-0.79 : Plausible but not clearly stated.\n"
            "- <0.50 : Missing/uncertain; value should be empty/unknown.\n"
            "\n"
            "Allowed hazard_type values (use exactly one):\n"
            "- salmonella : Salmonella bacterial contamination\n"
            "- listeria : Listeria monocytogenes contamination\n"
            "- ecoli : E. coli contamination\n"
            "- allergen : Undeclared allergen (e.g., undeclared wheat/peanut/soy/milk)\n"
            "- foreign_object : Physical contamination (glass/metal/plastic)\n"
            "- undeclared_ingredient : Undeclared non-allergen ingredient / misbranding ingredient issue\n"
            "- other : Use only if none of the above clearly applies\n"
            "\n"
            "Severity guidance (prefer authoritative FDA classes when present):\n"
            "- If the notice includes 'classification: Class I' -> severity=critical\n"
            "- If the notice includes 'classification: Class II' -> severity=high\n"
            "- If the notice includes 'classification: Class III' -> severity=medium\n"
            "- Otherwise -> severity=unknown and lower confidence\n"
            "\n"
            "Output requirements:\n"
            "- Output ONLY valid JSON that conforms to the RecallSpec schema. No markdown. No commentary. No <think>.\n"
        )

        few_shots = [
            # Few-shot 1: rich, complete OpenFDA-style notice.
            {
                "role": "user",
                "content": (
                    "product_description: Beef & Lamb Gyro Sandwich Express Meal Kit. Net wt. 31.8oz. "
                    "UPC 0 13454 38313 1. Each kit contains 6 Pitas, Gyro Meat, Tzatziki Sauce 3oz cups, "
                    "Fire Feta Sauce, Feta Cheese Crumbles.\n"
                    "reason_for_recall: Salmonella. Kit contains implicated cucumber in the tzatziki sauce 3oz cup.\n"
                    "recalling_firm: Reser's Fine Foods, Inc.\n"
                    "code_info: Kit has use by dates: 12/24/2024 12/25/2024 12/28/2024 1/2/2025 1/6/2025\n"
                    "distribution_pattern: Distributed in AZ, CA, CO, FL, GA, IL, IN, KS, LA, MD, MN, MO, NC, NY, OH, OK, TX, UT and WY.\n"
                    "classification: Class I\n"
                ),
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "recall_id": "UNKNOWN",
                        "source_type": "openfda",
                        "source_url": None,
                        "parsed_at": "2026-05-08T00:00:00Z",
                        "product_identifiers": [
                            {
                                "brand": None,
                                "product_name": "Beef & Lamb Gyro Sandwich Express Meal Kit",
                                "upc": "013454383131",
                                "package_size": "31.8oz",
                                "image_url": None,
                            }
                        ],
                        "lot_codes": [],
                        "best_by_dates": [{"start": None, "end": "2025-01-06"}],
                        "affected_facilities": [],
                        "affected_distribution": ["AZ", "CA", "CO", "FL", "GA", "IL", "IN", "KS", "LA", "MD", "MN", "MO", "NC", "NY", "OH", "OK", "TX", "UT", "WY"],
                        "severity": "critical",
                        "hazard_type": "salmonella",
                        "hazard_details": "Salmonella contamination risk.",
                        "symptom_timeline_days": [1, 30],
                        "remedy_instructions": "Do not consume; discard or return for refund.",
                        "extraction_confidence": {"product_identifiers": 0.9, "hazard_type": 0.9, "severity": 0.95},
                        "requires_human_review": False,
                        "raw_notice_text": "",
                    }
                ),
            },
            # Few-shot 2: partial data (month-year use-by).
            {
                "role": "user",
                "content": (
                    "product_description: SOMA KITCHEN NATURAL ASAFOETIDA Net Wt. 4 oz (0.25 lb) "
                    "Use by : JULY-2027 Lot : NATL/ASFTP/G/24 UPC : 4 973993 173586\n"
                    "reason_for_recall: Undeclared wheat.\n"
                    "code_info: Use by : JULY-2027 Lot : NATL/ASFTP/G/24 UPC : 4 973993 173586\n"
                    "distribution_pattern: U.S. distribution: CA\n"
                    "classification: Class II\n"
                ),
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "recall_id": "UNKNOWN",
                        "source_type": "openfda",
                        "source_url": None,
                        "parsed_at": "2026-05-08T00:00:00Z",
                        "product_identifiers": [
                            {
                                "brand": "SOMA KITCHEN",
                                "product_name": "NATURAL ASAFOETIDA",
                                "upc": None,
                                "package_size": "4 oz",
                                "image_url": None,
                            }
                        ],
                        "lot_codes": [{"value": "NATL/ASFTP/G/24", "confidence": 0.9}],
                        "best_by_dates": [{"start": "2027-07-01", "end": "2027-07-31"}],
                        "affected_facilities": [],
                        "affected_distribution": ["CA"],
                        "severity": "high",
                        "hazard_type": "allergen",
                        "hazard_details": "Undeclared wheat allergen.",
                        "symptom_timeline_days": [None, None],
                        "remedy_instructions": "",
                        "extraction_confidence": {"product_identifiers": 0.85, "hazard_type": 0.9, "severity": 0.95},
                        "requires_human_review": False,
                        "raw_notice_text": "",
                    }
                ),
            },
            # Few-shot 3: sparse/malformed (missing product_description) -> leave product_identifiers empty.
            {
                "role": "user",
                "content": (
                    "reason_for_recall: Product tested positive Salmonella.\n"
                    "code_info: Lots: 25006, 25035, 25044\n"
                    "distribution_pattern: United States\n"
                    "classification: Class I\n"
                ),
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "recall_id": "UNKNOWN",
                        "source_type": "openfda",
                        "source_url": None,
                        "parsed_at": "2026-05-08T00:00:00Z",
                        "product_identifiers": [],
                        "lot_codes": [{"value": "25006", "confidence": 0.85}, {"value": "25035", "confidence": 0.85}, {"value": "25044", "confidence": 0.85}],
                        "best_by_dates": [],
                        "affected_facilities": [],
                        "affected_distribution": ["UNITED STATES"],
                        "severity": "critical",
                        "hazard_type": "salmonella",
                        "hazard_details": "Product tested positive for Salmonella.",
                        "symptom_timeline_days": [None, None],
                        "remedy_instructions": "Do not consume; discard or return for refund.",
                        "extraction_confidence": {"product_identifiers": 0.4, "hazard_type": 0.9, "severity": 0.95},
                        "requires_human_review": True,
                        "raw_notice_text": "",
                    }
                ),
            },
            {
                "role": "user",
                "content": "product_description: BrandX Frozen Berries UPC 012345678901\nreason_for_recall: possible Listeria\nclassification: Class I\ncode_info: Lot L1234 best by 2026-01-01 to 2026-03-01\n",
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "recall_id": "F-0000-0000",
                        "source_type": "openfda",
                        "source_url": None,
                        "parsed_at": "2026-05-08T00:00:00Z",
                        "product_identifiers": [
                            {
                                "brand": "BrandX",
                                "product_name": "Frozen Berries",
                                "upc": "012345678901",
                                "package_size": None,
                                "image_url": None,
                            }
                        ],
                        "lot_codes": [{"value": "L1234", "confidence": 0.9}],
                        "best_by_dates": [{"start": "2026-01-01", "end": "2026-03-01"}],
                        "affected_facilities": [],
                        "affected_distribution": [],
                        "severity": "critical",
                        "hazard_type": "listeria",
                        "hazard_details": "Possible Listeria contamination.",
                        "symptom_timeline_days": [1, 30],
                        "remedy_instructions": "Do not consume; discard or return for refund.",
                        "extraction_confidence": {"product_identifiers": 0.9, "hazard_type": 0.95, "severity": 0.9},
                        "requires_human_review": False,
                        "raw_notice_text": "",
                    }
                ),
            },
            {
                "role": "user",
                "content": "Supplier email: We found metal shavings in Product Y. Lot codes: AB-123, AB-124.\n",
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "recall_id": "SUP-1",
                        "source_type": "supplier",
                        "source_url": None,
                        "parsed_at": "2026-05-08T00:00:00Z",
                        "product_identifiers": [
                            {
                                "brand": None,
                                "product_name": "Product Y",
                                "upc": None,
                                "package_size": None,
                                "image_url": None,
                            }
                        ],
                        "lot_codes": [{"value": "AB-123", "confidence": 0.8}, {"value": "AB-124", "confidence": 0.8}],
                        "best_by_dates": [],
                        "affected_facilities": [],
                        "affected_distribution": [],
                        "severity": "high",
                        "hazard_type": "foreign_object",
                        "hazard_details": "Potential metal contamination.",
                        "symptom_timeline_days": [None, None],
                        "remedy_instructions": "Hold product; do not sell; await further instructions.",
                        "extraction_confidence": {"product_identifiers": 0.7, "hazard_type": 0.8, "severity": 0.7},
                        "requires_human_review": True,
                        "raw_notice_text": "",
                    }
                ),
            },
            {
                "role": "user",
                "content": "Messy notice: reason_for_recall: Undeclared wheat allergen. product_description: Cookies.\n",
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "recall_id": "UNKNOWN",
                        "source_type": "openfda",
                        "source_url": None,
                        "parsed_at": "2026-05-08T00:00:00Z",
                        "product_identifiers": [
                            {
                                "brand": None,
                                "product_name": "Cookies",
                                "upc": None,
                                "package_size": None,
                                "image_url": None,
                            }
                        ],
                        "lot_codes": [],
                        "best_by_dates": [],
                        "affected_facilities": [],
                        "affected_distribution": [],
                        "severity": "unknown",
                        "hazard_type": "allergen",
                        "hazard_details": "Undeclared wheat allergen.",
                        "symptom_timeline_days": [None, None],
                        "remedy_instructions": "",
                        "extraction_confidence": {"product_identifiers": 0.6, "hazard_type": 0.8, "severity": 0.4},
                        "requires_human_review": True,
                        "raw_notice_text": "",
                    }
                ),
            },
        ]

        user_prompt = raw_text
        # Redact PII before sending to the model to reduce accidental echo.
        user_prompt_redacted = _redact_pii(user_prompt)

        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [{"role": "system", "content": system_prompt}, *few_shots, {"role": "user", "content": user_prompt_redacted}],
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 42,
            "max_tokens": 1400,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
            # vLLM supports OpenAI-compatible schema guidance in JSON Schema mode.
            "response_format": {"type": "json_schema", "json_schema": {"name": "RecallSpec", "schema": schema}},
        }
        headers: dict[str, str] = {}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        try:
            resp = self._client.post("/v1/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage")
            self.last_llm_usage = usage if isinstance(usage, dict) else None
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content")
            )
            if not isinstance(content, str) or not _is_json_object(content):
                return None
            obj = json.loads(content)
            if not isinstance(obj, dict):
                return None
            # Force recall/source provenance from baseline.
            obj["recall_id"] = baseline.recall_id
            obj["source_type"] = baseline.source_type
            obj["source_url"] = baseline.source_url
            obj["raw_notice_text"] = baseline.raw_notice_text
            obj["parsed_at"] = baseline.parsed_at.isoformat().replace("+00:00", "Z")
            return RecallSpec.model_validate(obj)
        except Exception:
            return None

    def _cross_check(self, spec: RecallSpec, related_notices: Iterable[Any]) -> RecallSpec:
        matches = 0
        mismatches = 0
        for n in related_notices:
            other = _baseline_extract(n)
            if other.recall_id != spec.recall_id and other.recall_id != "unknown":
                continue
            if other.hazard_type == spec.hazard_type and other.severity == spec.severity:
                matches += 1
            else:
                mismatches += 1

        boost = 0.1 * matches - 0.15 * mismatches
        if boost == 0:
            return spec

        conf = dict(spec.extraction_confidence)
        for k in ("product_identifiers", "hazard_type", "severity", "lot_codes"):
            conf[k] = max(0.0, min(1.0, conf.get(k, 0.5) + boost))
        return spec.model_copy(update={"extraction_confidence": conf})

    def _finalize(self, spec: RecallSpec) -> RecallSpec:
        # Redact PII in all non-audit free text.
        spec = spec.model_copy(
            update={
                "hazard_details": _redact_pii(spec.hazard_details),
                "remedy_instructions": _redact_pii(spec.remedy_instructions),
                "affected_distribution": [_redact_pii(x) for x in spec.affected_distribution],
                "affected_facilities": [_redact_pii(x) for x in spec.affected_facilities],
            }
        )

        conf = dict(spec.extraction_confidence)
        for k, v in list(conf.items()):
            conf[k] = _safe_float(v, default=0.5)
        critical = ("product_identifiers", "hazard_type", "severity")
        requires_review = any(conf.get(k, 0.0) < 0.6 for k in critical)
        return spec.model_copy(update={"extraction_confidence": conf, "requires_human_review": requires_review})
