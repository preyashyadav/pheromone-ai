from __future__ import annotations

import re


_SPANISH_MARKERS = {
    "retiro",
    "prueba",
    "por qué",
    "peligro",
    "severidad",
    "por favor",
    "reembolso",
    "no consuma",
    "probablemente",
}


def detect_language(text: str) -> str:
    """
    Tiny deterministic language detector for Phase 8 tests.

    This is intentionally conservative and currently only distinguishes `en` vs `es`.
    """
    t = (text or "").lower()
    if not t.strip():
        return "en"
    # If we see multiple strong Spanish markers, label as Spanish.
    hits = sum(1 for m in _SPANISH_MARKERS if m in t)
    if hits >= 2:
        return "es"
    # Very rough: common accented characters.
    if re.search(r"[áéíóúñ¿¡]", t):
        return "es"
    return "en"

