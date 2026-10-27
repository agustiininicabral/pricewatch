from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import AlertEvent, AlertRule, PriceObservation, StoreListing


def evaluate_rule(session: Session, rule: AlertRule) -> list[AlertEvent]:
    """Create idempotent pending events from latest valid persisted observations.

    This service never sends messages or fetches prices. It evaluates only data already
    stored in PriceWatch, allowing deterministic tests without network access.
    """
    listings = session.scalars(
        select(StoreListing)
        .where(
            StoreListing.product_id == rule.product_id,
            StoreListing.is_enabled.is_(True),
        )
        .order_by(StoreListing.id)
    ).all()
    created: list[AlertEvent] = []

    for listing in listings:
        if rule.variant_id is not None and listing.variant_id != rule.variant_id:
            continue
        observations = session.scalars(
            select(PriceObservation)
            .where(PriceObservation.listing_id == listing.id)
            .order_by(PriceObservation.observed_at.desc(), PriceObservation.id.desc())
            .limit(2)
        ).all()
        if not observations:
            continue

        current = observations[0]
        if not current.is_valid or current.currency != rule.currency:
            continue

        triggers: list[tuple[str, dict[str, int | str]]] = []
        if rule.target_amount_minor is not None and current.amount_minor <= rule.target_amount_minor:
            triggers.append(("target_reached", {
                "listing_id": listing.id,
                "observation_id": current.id,
                "amount_minor": current.amount_minor,
                "currency": current.currency,
                "target_amount_minor": rule.target_amount_minor,
            }))

        if rule.minimum_reduction_basis_points is not None and len(observations) > 1:
            previous = observations[1]
            if previous.is_valid and previous.currency == current.currency and previous.amount_minor > current.amount_minor:
                reduction = ((previous.amount_minor - current.amount_minor) * 10_000) // previous.amount_minor
                if reduction >= rule.minimum_reduction_basis_points:
                    triggers.append(("price_reduction", {
                        "listing_id": listing.id,
                        "observation_id": current.id,
                        "previous_observation_id": previous.id,
                        "previous_amount_minor": previous.amount_minor,
                        "amount_minor": current.amount_minor,
                        "currency": current.currency,
                        "reduction_basis_points": reduction,
                        "minimum_reduction_basis_points": rule.minimum_reduction_basis_points,
                    }))

        for event_type, payload in triggers:
            key = f"rule:{rule.id}:observation:{current.id}:{event_type}"
            exists = session.scalar(select(AlertEvent.id).where(AlertEvent.deduplication_key == key))
            if exists is not None:
                continue
            event = AlertEvent(
                rule_id=rule.id,
                deduplication_key=key,
                event_type=event_type,
                state="pending",
                payload=payload,
            )
            session.add(event)
            session.flush()
            created.append(event)

    return created
