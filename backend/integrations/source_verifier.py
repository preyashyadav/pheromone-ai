from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    reason: str


def _host_allowed(host: str, *, allowed_suffixes: Iterable[str]) -> bool:
    h = host.lower().strip(".")
    for suf in allowed_suffixes:
        s = suf.lower().strip(".")
        if h == s or h.endswith("." + s):
            return True
    return False


class SourceVerifier:
    def __init__(self, *, manufacturer_domains: Iterable[str] = ()) -> None:
        self._fda_suffixes = ("fda.gov",)
        self._usda_suffixes = ("usda.gov",)
        self._manufacturer_suffixes = tuple(manufacturer_domains)

    def verify(self, source_url: str | None) -> VerificationResult:
        if not source_url:
            return VerificationResult(False, "missing_source_url")

        parsed = urlparse(source_url)
        if parsed.scheme in ("supplier", "supplier_inbox", "internal", "retailer_internal"):
            return VerificationResult(True, "trusted_local_scheme")

        if parsed.scheme not in ("http", "https"):
            return VerificationResult(False, f"unsupported_scheme:{parsed.scheme}")

        host = parsed.hostname or ""
        if not host:
            return VerificationResult(False, "missing_host")

        if _host_allowed(host, allowed_suffixes=self._fda_suffixes):
            return VerificationResult(True, "fda_allowlist")
        if _host_allowed(host, allowed_suffixes=self._usda_suffixes):
            return VerificationResult(True, "usda_allowlist")
        if self._manufacturer_suffixes and _host_allowed(host, allowed_suffixes=self._manufacturer_suffixes):
            return VerificationResult(True, "manufacturer_allowlist")

        return VerificationResult(False, "host_not_allowlisted")

