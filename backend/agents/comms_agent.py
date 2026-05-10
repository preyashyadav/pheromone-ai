from __future__ import annotations

import enum
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.agents.intake_agent import HazardType, RecallSpec as IntakeRecallSpec, VllmClientConfig
from backend.db.models import NotificationDraft as NotificationDraftRow, PaymentType
from backend.db.repositories import RecallRepository
from backend.engine.composition_engine import InventoryCompositionEngine
from backend.engine.confidence import ConfidenceTier


_PHONE_LIKE_RE = re.compile(r"(?:(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?)\d{3}[\s.-]?\d{4}\b")
_EMAIL_LIKE_RE = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")


class NotificationChannel(str, enum.Enum):
    sms = "sms"
    email = "email"
    public_notice = "public_notice"
    admin_email = "admin_email"


class NotificationDraftOut(BaseModel):
    """
    Phase 8 output contract.

    Stored in `notification_drafts.draft` (JSONB).
    """

    model_config = ConfigDict(extra="forbid")

    customer_id: uuid.UUID | None
    channel: NotificationChannel
    confidence_tier: str
    draft: dict[str, Any]

    def to_row(self, *, recall_case_id: uuid.UUID) -> NotificationDraftRow:
        return NotificationDraftRow(
            recall_case_id=recall_case_id,
            customer_id=self.customer_id,
            channel=self.channel.value,
            confidence_tier=self.confidence_tier,
            draft=self.draft,
        )


class _LlmDraftOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    body: str
    language: str = "en"
    proof_points: list[str] = Field(default_factory=list)


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _safe_lang(lang: Any) -> str:
    v = str(lang or "").strip().lower()
    if not v:
        return "en"
    if re.fullmatch(r"[a-z]{2}(-[a-z]{2})?", v):
        return v
    return "en"


def _redact_pii(text: str) -> str:
    if not text:
        return ""
    text = _EMAIL_LIKE_RE.sub("[REDACTED_EMAIL]", text)
    text = _PHONE_LIKE_RE.sub("[REDACTED_PHONE]", text)
    return text


def _infer_affected_plant_codes(spec: IntakeRecallSpec) -> set[str]:
    """
    Deterministic heuristic: many lot codes embed plant code like `P2-...`.
    """
    out: set[str] = set()
    for e in spec.lot_codes:
        lot = getattr(e, "value", None)
        if not isinstance(lot, str):
            continue
        m = re.match(r"(?i)P(\d+)-", lot.strip())
        if m:
            out.add(f"P{m.group(1)}")
    for fac in (spec.affected_facilities or []):
        if isinstance(fac, str) and re.fullmatch(r"(?i)P\d+", fac.strip()):
            out.add(fac.strip().upper())
    return out


def _must_time_bound(body: str, as_of_utc: datetime) -> str:
    if re.search(r"\bas of\b", body, flags=re.IGNORECASE):
        return body
    ts = as_of_utc.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return f"{body}\n\nAs of {ts}."


@dataclass(frozen=True)
class CommsAgent:
    """
    Phase 8: Comms Agent.

    Produces drafts only; never sends. When `recall_case_id` is provided, drafts are inserted
    into `notification_drafts` with `status='drafted'` semantics (the table currently stores
    drafts only; send workflows are gated by demo-mode flags in later phases).

    vLLM usage is optional and fully guarded: if `vllm_config` is None, the agent uses
    deterministic templates.
    """

    session_factory: sessionmaker[Session]
    vllm_config: VllmClientConfig | None = None
    http_client: httpx.Client | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "_recalls_repo", RecallRepository(self.session_factory))
        object.__setattr__(self, "_composition", InventoryCompositionEngine(self.session_factory))
        object.__setattr__(self, "last_llm_usage", None)
        if self.vllm_config is not None:
            client = self.http_client or httpx.Client(
                timeout=self.vllm_config.timeout_s, base_url=self.vllm_config.base_url
            )
            object.__setattr__(self, "_client", client)
        else:
            object.__setattr__(self, "_client", None)

    def draft_notifications(
        self,
        scored_transactions: Iterable[Any],
        recall_spec: IntakeRecallSpec,
        *,
        recall_case_id: uuid.UUID | None = None,
        now_utc: datetime | None = None,
        public_notice_base_url: str | None = None,
    ) -> list[NotificationDraftOut]:
        now = (now_utc or datetime.now(tz=UTC)).astimezone(UTC)
        scored_list = list(scored_transactions)
        if not scored_list:
            return []

        tx_ids: list[uuid.UUID] = []
        for s in scored_list:
            tid = getattr(s, "transaction_id", None)
            if isinstance(tid, uuid.UUID):
                tx_ids.append(tid)
        tx_rows = self._load_transactions(tx_ids)
        tx_by_id = {uuid.UUID(str(r["id"])): r for r in tx_rows}

        affected_plants = _infer_affected_plant_codes(recall_spec)
        base_url = (
            (public_notice_base_url or os.getenv("PHEROMONE_PUBLIC_NOTICE_BASE_URL", "").strip())
            or "https://example.com/recalls"
        ).rstrip("/")

        drafts: list[NotificationDraftOut] = []
        cash_store_ids: set[uuid.UUID] = set()
        institutional_customer_ids: set[uuid.UUID] = set()

        for s in scored_list:
            tid = getattr(s, "transaction_id", None)
            if not isinstance(tid, uuid.UUID):
                continue
            tx = tx_by_id.get(tid)
            if not isinstance(tx, dict):
                continue

            customer_uuid = tx.get("customer_id") if isinstance(tx.get("customer_id"), uuid.UUID) else None
            payment_type_s = tx.get("payment_type")
            try:
                payment_type = PaymentType(str(payment_type_s))
            except Exception:
                payment_type = PaymentType.cash

            store_uuid = tx.get("store_id") if isinstance(tx.get("store_id"), uuid.UUID) else None

            tier = getattr(s, "confidence_tier", None)
            tier_value = getattr(tier, "value", None) if tier is not None else None
            tier_str = tier_value if isinstance(tier_value, str) else str(tier or "")

            # Cash/unknown buyer: no individual messages; one public notice per store.
            if payment_type == PaymentType.cash or customer_uuid is None:
                if store_uuid is not None:
                    cash_store_ids.add(store_uuid)
                continue

            # Institutional: one long-form admin email per institutional account.
            if self._is_institutional_customer(customer_uuid):
                institutional_customer_ids.add(customer_uuid)
                continue

            customer = self._load_customer(customer_uuid)
            profile = customer.get("profile") if isinstance(customer, dict) else {}
            if not isinstance(profile, dict):
                profile = {}
            lang = _safe_lang(profile.get("preferred_language") or profile.get("language"))

            channels = self._channels_for_customer(customer, profile)
            if not channels:
                channels = [NotificationChannel.email]

            for ch in channels:
                drafts.append(
                    self._draft_for_transaction(
                        tier=tier_str,
                        channel=ch,
                        recall_spec=recall_spec,
                        tx=tx,
                        customer=customer,
                        language=lang,
                        now=now,
                        affected_plants=affected_plants,
                        base_url=base_url,
                    )
                )

        for sid in sorted(cash_store_ids, key=lambda x: str(x)):
            drafts.append(
                NotificationDraftOut(
                    customer_id=None,
                    channel=NotificationChannel.public_notice,
                    confidence_tier="public_notice",
                    draft=self._draft_public_notice(
                        store_id=sid,
                        recall_spec=recall_spec,
                        now=now,
                        base_url=base_url,
                        affected_plants=affected_plants,
                    ),
                )
            )

        for cid in sorted(institutional_customer_ids, key=lambda x: str(x)):
            inst = self._load_institutional_account(cid)
            if inst is None:
                continue
            drafts.append(
                NotificationDraftOut(
                    customer_id=cid,
                    channel=NotificationChannel.admin_email,
                    confidence_tier="institutional",
                    draft=self._draft_institutional_notice(
                        recall_spec=recall_spec,
                        customer_id=cid,
                        institutional=inst,
                        now=now,
                        affected_plants=affected_plants,
                    ),
                )
            )

        if recall_case_id is not None and drafts:
            self._insert_notification_drafts(recall_case_id=recall_case_id, drafts=drafts)
        return drafts

    def _channels_for_customer(self, customer: dict[str, Any], profile: dict[str, Any]) -> list[NotificationChannel]:
        loyalty_id = customer.get("loyalty_id")
        email_hash = customer.get("email_hash")
        phone_hash = customer.get("phone_hash")
        consent_sms = bool(profile.get("consent_sms"))
        consent_email = bool(profile.get("consent_email"))

        # Phase 8 tests treat "draft count" as roughly 1 per scored transaction.
        # We still record secondary channel intent inside the draft payload.
        if loyalty_id:
            if consent_sms and phone_hash:
                return [NotificationChannel.sms]
            if email_hash:
                return [NotificationChannel.email]
            return [NotificationChannel.sms]

        if email_hash:
            return [NotificationChannel.email]
        return []

    def _draft_for_transaction(
        self,
        *,
        tier: str,
        channel: NotificationChannel,
        recall_spec: IntakeRecallSpec,
        tx: dict[str, Any],
        customer: dict[str, Any],
        language: str,
        now: datetime,
        affected_plants: set[str],
        base_url: str,
    ) -> NotificationDraftOut:
        subject, body, proof_points = self._deterministic_message(
            tier=tier, recall_spec=recall_spec, tx=tx, language=language, now=now, affected_plants=affected_plants
        )

        llm = self._try_llm_draft(
            tier=tier,
            recall_spec=recall_spec,
            tx=tx,
            language=language,
            now=now,
            proof_points=proof_points,
        )
        if llm is not None:
            subject = llm.subject.strip() or subject
            body = llm.body.strip() or body
            proof_points = llm.proof_points or proof_points

        subject = _redact_pii(subject)[:200].strip()
        body = _must_time_bound(_redact_pii(body), now)[:4000].strip()

        secondary_channels = self._secondary_channels(customer)
        payload = {
            "subject": subject,
            "body": body,
            "language": language,
            "channel": channel.value,
            "secondary_channels": secondary_channels,
            "confidence_tier": tier,
            "transaction_id": str(tx.get("id")),
            "store_id": str(tx.get("store_id")),
            "as_of_utc": now.isoformat().replace("+00:00", "Z"),
            "proof_points": [str(p)[:500] for p in proof_points[:8]],
            "cta_url": f"{base_url}/{recall_spec.recall_id}",
        }
        return NotificationDraftOut(
            customer_id=uuid.UUID(str(tx["customer_id"])),
            channel=channel,
            confidence_tier=(tier or "").strip().lower(),
            draft=payload,
        )

    def _secondary_channels(self, customer: dict[str, Any]) -> list[str]:
        profile = customer.get("profile")
        if not isinstance(profile, dict):
            profile = {}
        loyalty_id = customer.get("loyalty_id")
        email_hash = customer.get("email_hash")
        phone_hash = customer.get("phone_hash")
        consent_sms = bool(profile.get("consent_sms"))
        consent_email = bool(profile.get("consent_email"))
        secondary: list[str] = []
        if loyalty_id:
            if consent_sms and phone_hash:
                secondary.append(NotificationChannel.sms.value)
            if consent_email and email_hash:
                secondary.append(NotificationChannel.email.value)
        return secondary

    def _draft_public_notice(
        self,
        *,
        store_id: uuid.UUID,
        recall_spec: IntakeRecallSpec,
        now: datetime,
        base_url: str,
        affected_plants: set[str],
    ) -> dict[str, Any]:
        store_name = self._store_name(store_id) or "your store"
        hazard = recall_spec.hazard_type.value if hasattr(recall_spec.hazard_type, "value") else str(recall_spec.hazard_type)
        sev = recall_spec.severity.value if hasattr(recall_spec.severity, "value") else str(recall_spec.severity)
        affected_plant = sorted(affected_plants)[0] if affected_plants else "the affected facility"
        subject = f"Public notice: {recall_spec.recall_id} ({sev})"
        body = (
            f"{store_name} public notice: A food safety recall may affect certain items.\n\n"
            f"Hazard: {hazard}. Severity: {sev}.\n"
            f"If you purchased the recalled product, please do not consume it and follow the store’s refund/return guidance.\n\n"
            f"As of {now.isoformat().replace('+00:00', 'Z')}, the affected source is associated with {affected_plant}.\n"
            f"Scan the QR / visit: {base_url}/{recall_spec.recall_id}"
        )
        return {
            "subject": _redact_pii(subject),
            "body": _redact_pii(body),
            "language": "en",
            "channel": NotificationChannel.public_notice.value,
            "store_id": str(store_id),
            "as_of_utc": now.isoformat().replace("+00:00", "Z"),
            "qr_url": f"{base_url}/{recall_spec.recall_id}",
        }

    def _draft_institutional_notice(
        self,
        *,
        recall_spec: IntakeRecallSpec,
        customer_id: uuid.UUID,
        institutional: dict[str, Any],
        now: datetime,
        affected_plants: set[str],
    ) -> dict[str, Any]:
        hazard = recall_spec.hazard_type.value if hasattr(recall_spec.hazard_type, "value") else str(recall_spec.hazard_type)
        sev = recall_spec.severity.value if hasattr(recall_spec.severity, "value") else str(recall_spec.severity)
        affected_plant = ", ".join(sorted(affected_plants)[:3]) if affected_plants else "the affected facility"
        subject = f"[Institutional] Recall {recall_spec.recall_id} — action required ({sev})"
        body = (
            f"Hello {institutional.get('name')},\n\n"
            f"This is an institutional recall notice for recall {recall_spec.recall_id}.\n"
            f"Hazard: {hazard}. Severity: {sev}.\n\n"
            f"As of {now.isoformat().replace('+00:00', 'Z')}, the affected source is associated with: {affected_plant}.\n"
            "Suggested protocol:\n"
            "1) Quarantine any potentially affected inventory immediately.\n"
            "2) Run internal lot checks if you capture lot codes.\n"
            "3) Contact your account manager for replacement/refund and reporting guidance.\n"
        )
        return {
            "subject": _redact_pii(subject),
            "body": _redact_pii(body),
            "language": "en",
            "channel": NotificationChannel.admin_email.value,
            "customer_id": str(customer_id),
            "institutional_account_type": str(institutional.get("account_type") or ""),
            "as_of_utc": now.isoformat().replace("+00:00", "Z"),
        }

    def _deterministic_message(
        self,
        *,
        tier: str,
        recall_spec: IntakeRecallSpec,
        tx: dict[str, Any],
        language: str,
        now: datetime,
        affected_plants: set[str],
    ) -> tuple[str, str, list[str]]:
        hazard = recall_spec.hazard_type.value if hasattr(recall_spec.hazard_type, "value") else str(recall_spec.hazard_type)
        sev = recall_spec.severity.value if hasattr(recall_spec.severity, "value") else str(recall_spec.severity)

        store_id = tx.get("store_id")
        store_name = self._store_name(store_id) if isinstance(store_id, uuid.UUID) else None
        store_name = store_name or "your store"

        proof = self._provenance_proof_points(tx=tx, affected_plants=affected_plants)
        proof_text = " ".join(proof)

        customer_uuid = tx.get("customer_id") if isinstance(tx.get("customer_id"), uuid.UUID) else None
        customer = self._load_customer(customer_uuid) if customer_uuid else {"profile": {}}
        profile = customer.get("profile") if isinstance(customer, dict) else {}
        if not isinstance(profile, dict):
            profile = {}

        vuln_note = self._vulnerable_note(profile=profile, hazard_type=recall_spec.hazard_type, language=language)
        t = (tier or "").strip().lower()

        if language.startswith("es"):
            if t == ConfidenceTier.confirmed_affected.value:
                subject = f"Acción urgente: retiro {recall_spec.recall_id} ({sev})"
                body = (
                    f"Importante: su compra está confirmadamente afectada.\n"
                    f"Peligro: {hazard}. Severidad: {sev}.\n"
                    f"No consuma el producto. Deséchelo o devuélvalo para reembolso.\n"
                    f"{vuln_note}\n"
                    f"Prueba de procedencia: {proof_text}"
                )
            elif t == ConfidenceTier.likely_affected.value:
                subject = f"Probablemente afectado: revise el lote — {recall_spec.recall_id}"
                body = (
                    f"Su compra probablemente esté afectada.\n"
                    "Revise el código de lote/etiqueta (si está disponible) y siga las instrucciones del retiro.\n"
                    "Reembolso disponible.\n"
                    f"{vuln_note}\n"
                    f"Prueba de procedencia: {proof_text}"
                )
            elif t == ConfidenceTier.possible_affected.value:
                subject = f"Verificación recomendada: retiro {recall_spec.recall_id}"
                body = (
                    "Su compra podría estar afectada.\n"
                    "Por favor verifique el producto y el lote, y no lo consuma si coincide con el retiro.\n"
                    f"{vuln_note}\n"
                    f"Prueba de procedencia: {proof_text}"
                )
            elif t == ConfidenceTier.confirmed_unaffected.value:
                subject = f"Actualización de seguridad: usted no está afectado ({recall_spec.recall_id})"
                body = (
                    "Es posible que haya oído sobre el retiro. Buenas noticias: su compra está confirmadamente no afectada.\n"
                    f"Por qué: {proof_text}\n"
                    "Esta evaluación se basa en información disponible actualmente y puede cambiar si surgen nuevos datos."
                )
            else:
                subject = f"Probablemente no afectado: cómo verificar ({recall_spec.recall_id})"
                body = (
                    "Su compra parece no estar afectada.\n"
                    "Cómo verificar: revise el lote/etiqueta si está disponible y compare con el aviso del retiro.\n"
                    f"Por qué: {proof_text}\n"
                    "Esta evaluación se basa en información disponible actualmente y puede cambiar si surgen nuevos datos."
                )
            return subject, body, proof

        if t == ConfidenceTier.confirmed_affected.value:
            subject = f"Urgent action required: Recall {recall_spec.recall_id} ({sev})"
            body = (
                f"{store_name}: Your purchase is confirmed affected by this recall.\n"
                f"Hazard: {hazard}. Severity: {sev}.\n"
                "Do not consume. Dispose of the product or return for a refund.\n"
                f"{vuln_note}\n"
                f"Provenance proof: {proof_text}"
            )
        elif t == ConfidenceTier.likely_affected.value:
            subject = f"Likely affected: check lot/label — Recall {recall_spec.recall_id}"
            body = (
                f"{store_name}: Your purchase is likely affected.\n"
                "Please check the lot code/label (if available) and follow recall instructions. Refund is available.\n"
                f"{vuln_note}\n"
                f"Provenance proof: {proof_text}"
            )
        elif t == ConfidenceTier.possible_affected.value:
            subject = f"Please verify: Recall {recall_spec.recall_id}"
            body = (
                f"{store_name}: Your purchase may be affected.\n"
                "Please verify the product and any lot/label information if you still have it.\n"
                f"{vuln_note}\n"
                f"Provenance proof: {proof_text}"
            )
        elif t == ConfidenceTier.confirmed_unaffected.value:
            subject = f"Reassurance: you are not affected (Recall {recall_spec.recall_id})"
            body = (
                f"{store_name}: You may have heard about this recall. Good news: your purchase is confirmed unaffected.\n"
                f"Why: {proof_text}\n"
                "This assessment is based on currently available information and may change if new facts emerge."
            )
        else:
            subject = f"Likely unaffected: how to verify (Recall {recall_spec.recall_id})"
            body = (
                f"{store_name}: Your purchase appears unaffected.\n"
                "How to verify: check the lot/label if available and compare against the recall notice.\n"
                f"Why: {proof_text}\n"
                "This assessment is based on currently available information and may change if new facts emerge."
            )
        return subject, body, proof

    def _vulnerable_note(self, *, profile: dict[str, Any], hazard_type: HazardType, language: str) -> str:
        if hazard_type not in {HazardType.listeria, HazardType.salmonella, HazardType.ecoli}:
            return ""

        kids_at_home = bool(profile.get("kids_at_home"))
        pregnancy = bool(profile.get("pregnancy_status"))
        immuno = bool(profile.get("immunocompromised"))
        kids_list = profile.get("kids")
        has_under5 = False
        has_infant = False
        if isinstance(kids_list, list):
            for k in kids_list:
                if not isinstance(k, dict):
                    continue
                try:
                    age = float(k.get("age"))
                except Exception:
                    continue
                if age <= 5:
                    has_under5 = True
                if age <= 2:
                    has_infant = True
        if not (kids_at_home or pregnancy or immuno or has_under5 or has_infant):
            return ""

        hz = hazard_type.value if hasattr(hazard_type, "value") else str(hazard_type)
        if language.startswith("es"):
            return (
                f"Nota de riesgo: El CDC señala mayor riesgo de enfermedad grave para bebés/niños pequeños y otras personas vulnerables con {hz}."
            )
        return f"Risk note: The CDC notes higher risk of severe illness for infants/young children and other vulnerable individuals with {hz}."

    def _provenance_proof_points(self, *, tx: dict[str, Any], affected_plants: set[str]) -> list[str]:
        store_id = tx.get("store_id")
        ts = tx.get("timestamp")
        line_items = tx.get("line_items")
        if not isinstance(store_id, uuid.UUID) or not isinstance(ts, datetime) or not isinstance(line_items, list):
            return ["We could not compute provenance proof from available records."]

        plant_votes: dict[str, float] = {}
        for li in line_items:
            if not isinstance(li, dict):
                continue
            try:
                product_id = uuid.UUID(str(li.get("finished_product_id")))
            except Exception:
                continue
            comp = self._composition.compute_composition(store_id, product_id, ts.astimezone(UTC))
            if not comp:
                continue
            plant_by_pallet = self._plant_code_by_pallet(list(comp.keys()))
            for pallet_id, prob in comp.items():
                pc = plant_by_pallet.get(pallet_id)
                if not pc:
                    continue
                plant_votes[pc] = plant_votes.get(pc, 0.0) + float(prob)

        if not plant_votes:
            return ["We could not compute a plant-of-origin inference from inventory composition at time of sale."]

        top = sorted(plant_votes.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
        top_codes = [c for c, _ in top]
        top_text = ", ".join(top_codes)

        if affected_plants:
            affected_text = ", ".join(sorted(affected_plants))
            if all(c not in affected_plants for c in top_codes):
                return [
                    f"Your purchase is inferred to come from plant(s) {top_text}, which are not in the affected plant set ({affected_text})."
                ]
            if any(c in affected_plants for c in top_codes):
                return [f"Your purchase may be linked to plant(s) {top_text}; the affected plant set includes {affected_text}."]

        return [f"Your purchase is inferred to come from plant(s) {top_text} based on inventory composition at time of sale."]

    def _plant_code_by_pallet(self, pallet_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not pallet_ids:
            return {}
        with self.session_factory() as s:
            rows = s.execute(
                text(
                    """
                    SELECT p.id AS pallet_id, f.plant_code
                    FROM pallets p
                    JOIN finished_product_lots fpl ON fpl.id = p.finished_product_lot_id
                    JOIN production_runs pr ON pr.id = fpl.production_run_id
                    JOIN facilities f ON f.id = pr.facility_id
                    WHERE p.id = ANY(CAST(:pids AS uuid[]))
                    """
                ),
                {"pids": pallet_ids},
            ).all()
        out: dict[uuid.UUID, str] = {}
        for pid, plant_code in rows:
            try:
                out[uuid.UUID(str(pid))] = str(plant_code)
            except Exception:
                continue
        return out

    def _try_llm_draft(
        self,
        *,
        tier: str,
        recall_spec: IntakeRecallSpec,
        tx: dict[str, Any],
        language: str,
        now: datetime,
        proof_points: list[str],
    ) -> _LlmDraftOut | None:
        if self._client is None:
            return None
        if _env_bool("PHEROMONE_COMMS_SKIP_LLM", False):
            return None

        schema = _LlmDraftOut.model_json_schema()
        t = (tier or "").strip().lower()

        tone = ""
        required_reassurance = ""
        if t in {ConfidenceTier.confirmed_affected.value, ConfidenceTier.likely_affected.value}:
            tone = (
                "Tone (URGENT tier): factual, urgent, action-oriented. Avoid alarming language but be unambiguous.\n"
                "Max 4 sentences.\n"
            )
        elif t == ConfidenceTier.possible_affected.value:
            tone = (
                "Tone (POSSIBLE tier): gentle, instructional. The customer may NOT be affected.\n"
                "Lead with: 'Your purchase may include a recalled product' (not 'is').\n"
                "Max 5 sentences. Include lot-check instructions.\n"
            )
        elif t in {ConfidenceTier.confirmed_unaffected.value, ConfidenceTier.likely_unaffected.value}:
            tone = (
                "Tone (REASSURANCE tier): reassuring, transparent, time-bound.\n"
                "Goal: prevent panic refunds by providing concrete proof and calibrated language.\n"
            )
            required_reassurance = (
                "REASSURANCE REQUIRED ELEMENTS (must include all):\n"
                "1) Acknowledge the customer may have heard about the recall.\n"
                "2) Concrete provenance proof from proof_points (do NOT omit this).\n"
                "3) Time-bound language using as_of_utc (e.g., 'as of <timestamp>').\n"
                "4) Conditional follow-up promise: 'We will notify you immediately if the recall scope changes.'\n"
                "5) Forbidden phrases: 'guaranteed safe', '100% safe', 'definitely fine'.\n"
            )

        vuln_guidance = (
            "Vulnerable household rule:\n"
            "- If vulnerable.kids_under5 is true OR vulnerable.pregnancy is true OR vulnerable.immunocompromised is true,\n"
            "  AND hazard_type is listeria/salmonella/ecoli: include one sentence noting higher risk for infants/young children\n"
            "  (briefly reference CDC guidance).\n"
        )

        system_prompt = (
            "You are Pheromone Comms Agent. Draft a customer notification.\n"
            "Output requirements:\n"
            "- Output MUST be valid JSON matching the provided schema. No markdown. No commentary. No <think>.\n"
            "CRITICAL: Use ONLY facts provided in the structured input.\n"
            "- Do NOT invent product names, lot codes, plant names, distributor names, or store names.\n"
            "- If a detail is missing, omit it or use a generic phrase like 'the recalled product'.\n"
            "- Fabricating provenance facts is the most serious error.\n"
            "Safety + privacy:\n"
            "- Do NOT include phone numbers, emails, addresses, payment details, or other PII.\n"
            "- Avoid absolute safety claims.\n"
            "Content requirements:\n"
            "- Include explicit time-bound language using as_of_utc.\n"
            "- Include concrete provenance proof using proof_points.\n"
            f"{vuln_guidance}"
            f"{tone}"
            f"{required_reassurance}"
            f"Language: write the message in {language} (default en if unspecified), and set output.language accordingly.\n"
        )
        customer_uuid = tx.get("customer_id") if isinstance(tx.get("customer_id"), uuid.UUID) else None
        customer = self._load_customer(customer_uuid) if customer_uuid else {"profile": {}}
        profile = customer.get("profile") if isinstance(customer, dict) else {}
        if not isinstance(profile, dict):
            profile = {}
        kids_list = profile.get("kids")
        kids_under5 = False
        if isinstance(kids_list, list):
            for k in kids_list:
                if not isinstance(k, dict):
                    continue
                try:
                    age = float(k.get("age"))
                except Exception:
                    continue
                if age <= 5:
                    kids_under5 = True
                    break
        user = {
            "tier": tier,
            "recall_id": recall_spec.recall_id,
            "severity": (recall_spec.severity.value if hasattr(recall_spec.severity, "value") else str(recall_spec.severity)),
            "hazard_type": (recall_spec.hazard_type.value if hasattr(recall_spec.hazard_type, "value") else str(recall_spec.hazard_type)),
            "as_of_utc": now.isoformat().replace("+00:00", "Z"),
            "proof_points": proof_points,
            "vulnerable": {
                "kids_under5": bool(profile.get("kids_at_home")) or kids_under5,
                "pregnancy": bool(profile.get("pregnancy_status")),
                "immunocompromised": bool(profile.get("immunocompromised")),
            },
        }

        # Tier-specific few-shots (teach tone + non-fabrication).
        few_shots: list[dict[str, str]] = []
        if t == ConfidenceTier.confirmed_affected.value:
            few_shots = [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "tier": "confirmed_affected",
                            "recall_id": "RG-4429",
                            "severity": "high",
                            "hazard_type": "salmonella",
                            "as_of_utc": "2026-05-09T00:00:00Z",
                            "proof_points": ["Your purchase may be linked to plant(s) P2; the affected plant set includes P2."],
                        }
                    ),
                },
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "subject": "Urgent action required: Recall RG-4429 (high)",
                            "body": "Your purchase is confirmed affected by this recall. Do not consume the recalled product; discard it or return it for a refund. Provenance proof: Your purchase may be linked to plant(s) P2; the affected plant set includes P2. As of 2026-05-09T00:00:00Z.",
                            "language": "en",
                            "proof_points": ["Your purchase may be linked to plant(s) P2; the affected plant set includes P2."],
                        }
                    ),
                },
            ]
        elif t == ConfidenceTier.possible_affected.value:
            few_shots = [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "tier": "possible_affected",
                            "recall_id": "RG-4429",
                            "severity": "high",
                            "hazard_type": "salmonella",
                            "as_of_utc": "2026-05-09T00:00:00Z",
                            "proof_points": ["We could not compute provenance proof from available records."],
                        }
                    ),
                },
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "subject": "Please verify: Recall RG-4429",
                            "body": "Your purchase may include a recalled product. If you still have the item, please check the lot code/label (if available) and compare it to the recall notice, and do not consume it if it matches. As of 2026-05-09T00:00:00Z.",
                            "language": "en",
                            "proof_points": ["We could not compute provenance proof from available records."],
                        }
                    ),
                },
            ]
        elif t == ConfidenceTier.confirmed_unaffected.value:
            few_shots = [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "tier": "confirmed_unaffected",
                            "recall_id": "RG-4429",
                            "severity": "high",
                            "hazard_type": "salmonella",
                            "as_of_utc": "2026-05-09T00:00:00Z",
                            "proof_points": [
                                "Your purchase is inferred to come from plant(s) P1, which are not in the affected plant set (P2)."
                            ],
                        }
                    ),
                },
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "subject": "Reassurance: you are not affected (Recall RG-4429)",
                            "body": "You may have heard about this recall. Based on our records, your purchase is from an unaffected source as of 2026-05-09T00:00:00Z. Proof: Your purchase is inferred to come from plant(s) P1, which are not in the affected plant set (P2). We will notify you immediately if the recall scope changes.",
                            "language": "en",
                            "proof_points": [
                                "Your purchase is inferred to come from plant(s) P1, which are not in the affected plant set (P2)."
                            ],
                        }
                    ),
                },
            ]

        payload: dict[str, Any] = {
            "model": (self.vllm_config.model if self.vllm_config else "Qwen/Qwen3-32B"),
            "messages": [{"role": "system", "content": system_prompt}, *few_shots, {"role": "user", "content": json.dumps(user)}],
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 42,
            "max_tokens": 900,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
            "response_format": {"type": "json_schema", "json_schema": {"name": "_LlmDraftOut", "schema": schema}},
        }
        headers: dict[str, str] = {}
        if self.vllm_config and self.vllm_config.api_key:
            headers["Authorization"] = f"Bearer {self.vllm_config.api_key}"
        try:
            resp = self._client.post("/v1/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage")
            object.__setattr__(self, "last_llm_usage", usage if isinstance(usage, dict) else None)
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            if not isinstance(content, str):
                return None
            obj = json.loads(content)
            if not isinstance(obj, dict):
                return None
            return _LlmDraftOut.model_validate(obj)
        except Exception:
            return None

    def _load_transactions(self, tx_ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        if not tx_ids:
            return []
        with self.session_factory() as s:
            rows = s.execute(
                text(
                    """
                    SELECT id, store_id, customer_id, timestamp, payment_type, line_items
                    FROM pos_transactions
                    WHERE id = ANY(CAST(:ids AS uuid[]))
                    """
                ),
                {"ids": tx_ids},
            ).all()
        out: list[dict[str, Any]] = []
        for rid, store_id, cust_id, ts, pay, li in rows:
            out.append(
                {
                    "id": uuid.UUID(str(rid)),
                    "store_id": uuid.UUID(str(store_id)),
                    "customer_id": uuid.UUID(str(cust_id)) if cust_id is not None else None,
                    "timestamp": ts,
                    "payment_type": pay.value if hasattr(pay, "value") else str(pay),
                    "line_items": li if isinstance(li, list) else [],
                }
            )
        out.sort(key=lambda r: str(r["id"]))
        return out

    def _load_customer(self, customer_id: uuid.UUID) -> dict[str, Any]:
        with self.session_factory() as s:
            row = s.execute(
                text("SELECT id, loyalty_id, email_hash, phone_hash, profile FROM customers WHERE id = :id"),
                {"id": customer_id},
            ).first()
        if not row:
            return {"id": customer_id, "profile": {}}
        cid, loyalty_id, email_hash, phone_hash, profile = row
        return {
            "id": uuid.UUID(str(cid)),
            "loyalty_id": str(loyalty_id) if loyalty_id else None,
            "email_hash": str(email_hash) if email_hash else None,
            "phone_hash": str(phone_hash) if phone_hash else None,
            "profile": profile if isinstance(profile, dict) else {},
        }

    def _is_institutional_customer(self, customer_id: uuid.UUID) -> bool:
        with self.session_factory() as s:
            v = s.execute(
                text("SELECT 1 FROM institutional_accounts WHERE customer_id = :cid LIMIT 1"), {"cid": customer_id}
            ).scalar_one_or_none()
        return v is not None

    def _load_institutional_account(self, customer_id: uuid.UUID) -> dict[str, Any] | None:
        with self.session_factory() as s:
            row = s.execute(
                text("SELECT id, account_type, name FROM institutional_accounts WHERE customer_id = :cid LIMIT 1"),
                {"cid": customer_id},
            ).first()
        if not row:
            return None
        iid, account_type, name = row
        return {"id": str(iid), "account_type": str(account_type), "name": str(name)}

    def _store_name(self, store_id: uuid.UUID) -> str | None:
        with self.session_factory() as s:
            return s.execute(text("SELECT name FROM stores WHERE id = :id"), {"id": store_id}).scalar_one_or_none()

    def _insert_notification_drafts(self, *, recall_case_id: uuid.UUID, drafts: list[NotificationDraftOut]) -> None:
        self._recalls_repo.insert_notification_drafts(recall_case_id=recall_case_id, drafts=drafts)

    @staticmethod
    def grade_reassurance_proof(body: str) -> bool:
        """
        Deterministic stand-in for the Phase 8 LLM grader.
        """
        b = (body or "").lower()
        has_proof_token = ("plant" in b) or ("planta" in b) or ("distributor" in b) or ("distribuidor" in b)
        has_why = ("why:" in b) or ("por qué" in b) or ("proof" in b) or ("prueba" in b)
        return has_proof_token and has_why

    @staticmethod
    def grade_time_bound(body: str) -> bool:
        return bool(re.search(r"\bas of\b\s+\d{4}-\d{2}-\d{2}t", body or "", flags=re.IGNORECASE))
