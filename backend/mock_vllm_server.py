from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from datetime import UTC, datetime


_UPC_RE = re.compile(r"\b\d{12}\b")
_LOT_TOKEN_RE = re.compile(r"\b[A-Z0-9][A-Z0-9-]{3,}\b")


def _extract_first_upc(text: str) -> str | None:
    m = _UPC_RE.search(text or "")
    return m.group(0) if m else None


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


def _infer_hazard_type(text: str) -> str:
    """
    Deterministic heuristic mirroring `backend/agents/intake_agent.py` hazard mapping.
    """
    t = (text or "").lower()
    if "salmonella" in t:
        return "salmonella"
    if "listeria" in t:
        return "listeria"
    if "e. coli" in t or "e coli" in t or "ecoli" in t:
        return "ecoli"
    if "undeclared" in t or "allergen" in t:
        return "allergen" if any(k in t for k in _ALLERGEN_KEYWORDS) else "undeclared_ingredient"
    if "metal" in t or "glass" in t or "plastic" in t or "foreign object" in t or "foreign material" in t:
        return "foreign_object"
    if "misbrand" in t or "misbranded" in t or "nutrition facts" in t or ("label" in t and "undeclared" in t):
        return "undeclared_ingredient"
    return "other"


def _infer_severity(text: str, hazard_type: str) -> str:
    t = (text or "").lower()
    # Prefer openFDA classification when present.
    m = re.search(r"(?i)\bclassification:\s*([^\n]+)", text or "")
    cls = (m.group(1).strip().lower() if m else "")
    if cls.startswith("class ii"):
        return "high"
    if cls.startswith("class i"):
        return "critical"
    if cls.startswith("class iii"):
        return "medium"

    if "critical" in t:
        return "critical"
    if "high" in t:
        return "high"
    if "medium" in t:
        return "medium"
    if "market withdrawal" in t or "not a health hazard" in t or "low" in t:
        return "low"
    if hazard_type in {"salmonella", "listeria", "ecoli"}:
        return "high"
    if hazard_type in {"allergen", "undeclared_ingredient", "foreign_object"}:
        return "medium"
    return "unknown"


def _extract_lot_codes(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    out: list[dict[str, Any]] = []
    marker_re = re.compile(r"(?i)\b(lot|lots|lot code|lot codes|batch|batch codes)\b[:\s]*([^\n]+)")
    for m in marker_re.finditer(text):
        tail = (m.group(2) or "")[:400]
        for tok in _LOT_TOKEN_RE.findall(tail.upper()):
            if tok in {"USA", "CANADA"}:
                continue
            if tok.isdigit() and len(tok) == 12:
                continue
            out.append({"value": tok, "confidence": 0.85})
    if not out:
        for tok in _LOT_TOKEN_RE.findall(text.upper()):
            if tok in {"USA", "CANADA"}:
                continue
            if tok.isdigit() and len(tok) == 12:
                continue
            out.append({"value": tok, "confidence": 0.6})
    # de-dupe
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in out:
        v = str(item.get("value") or "")
        if not v or v in seen:
            continue
        seen.add(v)
        deduped.append(item)
    return deduped[:30]


def _extract_distribution(text: str) -> list[str]:
    if not text:
        return []
    # openFDA often includes "distribution_pattern: ..."
    m = re.search(r"(?i)\bdistribution_pattern:\s*([^\n]+)", text)
    if m:
        s = m.group(1).strip()
        if s:
            parts = [p.strip() for p in re.split(r"[;,]", s) if p.strip()]
            return parts[:20]
    # supplier emails in fixtures use "Shipped to: CA, NV"
    m2 = re.search(r"(?i)\bshipped\s+to\b:\s*([A-Z]{2}(?:\s*,\s*[A-Z]{2})+)", text)
    if m2:
        return [p.strip().upper() for p in m2.group(1).split(",") if p.strip()][:20]
    return []


def _extract_product_name(text: str) -> str:
    if not text:
        return ""
    # openFDA fixture format: "product_description: ..."
    m = re.search(r"(?i)\bproduct_description:\s*([^\n]+)", text)
    if m and m.group(1).strip():
        return m.group(1).strip()[:500]
    # supplier/internal: first line usually carries subject/product
    for ln in (text or "").splitlines():
        if ln.strip():
            return ln.strip()[:500]
    return (text or "")[:500]


def _build_recall_spec_like_json(raw_user_text: str) -> dict[str, Any]:
    upc = _extract_first_upc(raw_user_text)
    # Use reason_for_recall when present (openFDA fixtures), else fall back to whole notice.
    m_reason = re.search(r"(?i)\breason_for_recall:\s*([^\n]+)", raw_user_text or "")
    hazard_text = (m_reason.group(1).strip() if m_reason else raw_user_text)
    hazard_type = _infer_hazard_type(hazard_text)
    severity = _infer_severity(raw_user_text, hazard_type)
    product_name = _extract_product_name(raw_user_text)
    lot_codes = _extract_lot_codes(raw_user_text)
    dist = _extract_distribution(raw_user_text)

    # Confidence heuristics: mirror the IntakeAgent baseline behavior closely enough that
    # Phase 4 tests remain meaningful when exercising the LLM code path via this mock.
    t_lower = (raw_user_text or "").lower()
    is_openfda_like = ("product_description:" in t_lower) or ("classification:" in t_lower)
    # If this looks like openFDA but product_description is missing, don't invent a product line.
    if is_openfda_like and "product_description:" not in t_lower:
        product_name = ""

    prod_conf = 0.9 if product_name else 0.4
    if is_openfda_like:
        # Missing code_info is a strong signal of messy/partial input in our fixtures.
        if "code_info:" not in t_lower:
            prod_conf = min(prod_conf, 0.55)
        if "<" in product_name or ">" in product_name:
            prod_conf = min(prod_conf, 0.55)
        if "***" in product_name or "supplement facts" in product_name.lower():
            prod_conf = min(prod_conf, 0.55)

    has_reason_line = "reason_for_recall:" in t_lower
    hazard_conf = 0.95 if hazard_type != "other" and has_reason_line else (0.55 if not has_reason_line else 0.85)

    conf: dict[str, float] = {
        "product_identifiers": prod_conf,
        "hazard_type": hazard_conf,
        "severity": 0.9 if severity != "unknown" else 0.55,
        "lot_codes": 0.85 if lot_codes else 0.55,
        "affected_distribution": 0.75 if dist else 0.5,
    }

    return {
        "recall_id": "UNKNOWN",
        "source_type": "unknown",
        "source_url": None,
        "parsed_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "product_identifiers": [
            {
                "brand": None,
                "product_name": product_name,
                "upc": upc,
                "package_size": None,
                "image_url": None,
            }
        ]
        if product_name
        else [],
        "lot_codes": lot_codes,
        "best_by_dates": [],
        "affected_facilities": [],
        "affected_distribution": dist,
        "severity": severity,
        "hazard_type": hazard_type,
        "hazard_details": "",
        "symptom_timeline_days": [None, None],
        "remedy_instructions": "",
        "extraction_confidence": conf,
        "requires_human_review": bool(min(conf.get("product_identifiers", 0.0), conf.get("hazard_type", 0.0), conf.get("severity", 0.0)) < 0.6),
        "raw_notice_text": "",
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "PheromoneMockvLLM/0.1"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": {"message": "not found"}})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": {"message": "invalid json"}})
            return

        model = req.get("model") or "Qwen/Qwen3-32B"
        messages = req.get("messages") or []
        last_user = ""
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "user":
                last_user = str(m.get("content") or "")
                break

        # Return RecallSpec-shaped JSON in `message.content` to exercise IntakeAgent's JSON-schema path.
        content = json.dumps(_build_recall_spec_like_json(last_user), ensure_ascii=False)

        payload = {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }
        self._send_json(200, payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 0-only local mock vLLM server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    print(f"Mock vLLM listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
