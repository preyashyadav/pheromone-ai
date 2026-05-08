from __future__ import annotations

import enum
from typing import Any

from backend.agents.intake_agent import HazardType
from backend.db.models import CustomerProfile


class ConfidenceTier(str, enum.Enum):
    confirmed_affected = "confirmed_affected"
    likely_affected = "likely_affected"
    possible_affected = "possible_affected"
    likely_unaffected = "likely_unaffected"
    confirmed_unaffected = "confirmed_unaffected"
    no_action = "no_action"


def actionability_score(
    *,
    days_since_purchase: float,
    shelf_life_days_remaining: float | None,
    symptom_timeline_days: tuple[int | None, int | None] = (None, None),
) -> float:
    """
    A lightweight deterministic score in [0,1] used for tier mapping.

    Heuristics (Phase 6):
    - If the product is plausibly still consumable (shelf life not expired), higher actionability.
    - If the symptom window (max) hasn't elapsed, higher actionability.
    """
    score = 0.0
    if shelf_life_days_remaining is None:
        score += 0.4
    else:
        score += 0.6 if days_since_purchase <= shelf_life_days_remaining else 0.1

    _, symptom_max = symptom_timeline_days
    if symptom_max is None:
        score += 0.2
    else:
        score += 0.4 if days_since_purchase <= float(symptom_max) else 0.05

    return max(0.0, min(1.0, score))


def map_tier(*, affected_probability: float, actionability: float, had_family_purchase: bool) -> ConfidenceTier:
    """
    Maps (probability, actionability) to one of 6 confidence tiers.

    Thresholds come from Phase 6 build plan.
    """
    p = max(0.0, min(1.0, float(affected_probability)))
    a = max(0.0, min(1.0, float(actionability)))
    actionable = a >= 0.5

    if p > 0.9 and actionable:
        return ConfidenceTier.confirmed_affected
    if 0.5 <= p <= 0.9 and actionable:
        return ConfidenceTier.likely_affected
    if 0.1 <= p < 0.5:
        return ConfidenceTier.possible_affected
    if 0.01 <= p < 0.1:
        return ConfidenceTier.likely_unaffected
    if p < 0.01 and had_family_purchase:
        return ConfidenceTier.confirmed_unaffected
    return ConfidenceTier.no_action


def bump_tier_for_vulnerable_population(
    *, tier: ConfidenceTier, profile: CustomerProfile | None, hazard_type: HazardType
) -> ConfidenceTier:
    """
    Phase 6 vulnerable-population modifier:
    if customer has kids/immunocompromised and hazard is Listeria/Salmonella,
    bump up by one tier.
    """
    if profile is None:
        return tier
    vulnerable = bool(profile.kids_at_home or profile.immunocompromised)
    if not vulnerable:
        return tier
    if hazard_type not in {HazardType.listeria, HazardType.salmonella}:
        return tier

    order = [
        ConfidenceTier.no_action,
        ConfidenceTier.confirmed_unaffected,
        ConfidenceTier.likely_unaffected,
        ConfidenceTier.possible_affected,
        ConfidenceTier.likely_affected,
        ConfidenceTier.confirmed_affected,
    ]
    try:
        idx = order.index(tier)
    except ValueError:
        return tier
    return order[min(idx + 1, len(order) - 1)]

