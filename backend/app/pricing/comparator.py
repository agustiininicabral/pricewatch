from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from app.collectors.contracts import (
    Availability,
    ProductObservation,
    ValidationStatus,
)

CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")


class ShippingStatus(StrEnum):
    FREE = "free"
    PAID = "paid"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProductIdentity:
    """A manually or authoritatively verified canonical product/variant match."""

    canonical_key: str
    variant_key: str | None = None
    verified: bool = False

    def __post_init__(self) -> None:
        if not self.canonical_key.strip():
            raise ValueError("canonical_key no puede estar vacío")
        if self.variant_key is not None and not self.variant_key.strip():
            raise ValueError("variant_key debe omitirse o contener una clave")


@dataclass(frozen=True, slots=True)
class ShippingCost:
    status: ShippingStatus
    amount_minor: int | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ShippingStatus):
            raise ValueError("status debe ser un valor ShippingStatus")
        if self.status is ShippingStatus.UNKNOWN:
            if self.amount_minor is not None or self.currency is not None:
                raise ValueError("El envío desconocido no admite importe ni moneda")
        elif self.status is ShippingStatus.FREE:
            if self.amount_minor != 0 or self.currency is not None:
                raise ValueError("El envío gratuito se representa con importe cero")
        else:
            if (
                type(self.amount_minor) is not int
                or self.amount_minor <= 0
                or self.currency is None
                or not CURRENCY_PATTERN.fullmatch(self.currency)
            ):
                raise ValueError(
                    "El envío con costo requiere importe positivo y moneda explícita"
                )


@dataclass(frozen=True, slots=True)
class OfferCandidate:
    identity: ProductIdentity
    observation: ProductObservation
    shipping: ShippingCost


@dataclass(frozen=True, slots=True)
class ExcludedOffer:
    source_url: str
    reason: str


@dataclass(frozen=True, slots=True)
class OfferEvaluation:
    source_url: str
    title: str
    currency: str
    price_minor: int
    shipping_status: ShippingStatus
    shipping_minor: int | None
    total_minor: int
    difference_from_cheapest_minor: int | None


@dataclass(frozen=True, slots=True)
class ComparisonGroup:
    canonical_key: str
    variant_key: str | None
    currency: str
    offers: tuple[OfferEvaluation, ...]
    cheapest_offer: OfferEvaluation | None
    winner_reason: str | None
    blocking_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    groups: tuple[ComparisonGroup, ...]
    excluded: tuple[ExcludedOffer, ...]
    summary: str


def _currency_is_valid(currency: str | None) -> bool:
    return currency is not None and CURRENCY_PATTERN.fullmatch(currency) is not None


def _exclusion_reason(candidate: OfferCandidate) -> str | None:
    observation = candidate.observation
    if not candidate.identity.verified:
        return "La identidad del producto o variante no está verificada."
    if (
        type(observation.amount_minor) is not int
        or observation.amount_minor <= 0
    ):
        return "El precio está ausente o es inválido."
    if not _currency_is_valid(observation.currency):
        return "La moneda del producto está ausente o no es válida."
    if observation.validation_status is not ValidationStatus.VERIFIED:
        return "Los datos de la publicación están pendientes de revisión."
    if observation.availability is not Availability.IN_STOCK:
        return "La disponibilidad no confirma stock."
    if candidate.shipping.status is ShippingStatus.PAID:
        if candidate.shipping.currency != observation.currency:
            return "La moneda del envío no coincide con la del producto."
    return None


def compare_offers(candidates: Iterable[OfferCandidate]) -> ComparisonResult:
    """Rank verified offers by known total, partitioned by exact identity and currency.

    No exchange rates, shipping estimates, or product identity are inferred.
    """
    excluded: list[ExcludedOffer] = []
    buckets: dict[tuple[str, str | None, str], list[tuple[OfferCandidate, int]]] = {}
    blocked: dict[tuple[str, str | None, str], list[str]] = {}

    for candidate in candidates:
        observation = candidate.observation
        reason = _exclusion_reason(candidate)
        if reason is not None:
            excluded.append(ExcludedOffer(observation.source_url, reason))
            continue
        assert observation.amount_minor is not None
        assert observation.currency is not None
        key = (
            candidate.identity.canonical_key,
            candidate.identity.variant_key,
            observation.currency,
        )
        if candidate.shipping.status is ShippingStatus.UNKNOWN:
            excluded.append(
                ExcludedOffer(
                    observation.source_url,
                    "El costo total es desconocido porque no se conoce el envío.",
                )
            )
            blocked.setdefault(key, []).append(
                f"{observation.source_url}: envío desconocido"
            )
            continue

        shipping_minor = (
            0
            if candidate.shipping.status is ShippingStatus.FREE
            else candidate.shipping.amount_minor
        )
        assert shipping_minor is not None
        total_minor = observation.amount_minor + shipping_minor
        buckets.setdefault(key, []).append((candidate, total_minor))

    groups: list[ComparisonGroup] = []
    all_keys = sorted(
        set(buckets) | set(blocked),
        key=lambda item: (item[0], item[1] or "", item[2]),
    )
    for canonical_key, variant_key, currency in all_keys:
        key = (canonical_key, variant_key, currency)
        offers = buckets.get(key, [])
        blockers = tuple(blocked.get(key, []))
        ordered = sorted(
            offers,
            key=lambda item: (
                item[1],
                item[0].observation.source_url,
            ),
        )
        cheapest_total = ordered[0][1] if ordered and not blockers else None
        evaluations_list: list[OfferEvaluation] = []
        for candidate, total_minor in ordered:
            amount_minor = candidate.observation.amount_minor
            if amount_minor is None:
                raise RuntimeError("La oferta verificada perdió su importe.")
            evaluations_list.append(
                OfferEvaluation(
                    source_url=candidate.observation.source_url,
                    title=candidate.observation.title,
                    currency=currency,
                    price_minor=amount_minor,
                    shipping_status=candidate.shipping.status,
                    shipping_minor=(
                        0
                        if candidate.shipping.status is ShippingStatus.FREE
                        else candidate.shipping.amount_minor
                    ),
                    total_minor=total_minor,
                    difference_from_cheapest_minor=(
                        None
                        if cheapest_total is None
                        else total_minor - cheapest_total
                    ),
                )
            )
        evaluations = tuple(evaluations_list)
        has_winner = bool(evaluations) and not blockers
        groups.append(
            ComparisonGroup(
                canonical_key=canonical_key,
                variant_key=variant_key,
                currency=currency,
                offers=evaluations,
                cheapest_offer=evaluations[0] if has_winner else None,
                winner_reason=(
                    None
                    if has_winner
                    else (
                        "No se puede confirmar una oferta más económica: "
                        "hay ofertas comparables con envío desconocido."
                        if blockers
                        else "No hay ofertas verificadas con costo total conocido."
                    )
                ),
                blocking_reasons=blockers,
            )
        )

    result_groups = tuple(groups)
    if not result_groups or not any(group.offers for group in result_groups):
        summary = (
            "No hay ofertas verificadas con costo total conocido suficientes "
            "para determinar una ganadora."
        )
    elif any(group.cheapest_offer is None for group in result_groups):
        summary = (
            "La comparación determina resultados únicamente por producto, "
            "variante y moneda; uno o más grupos no tienen ganador por datos "
            "insuficientes."
        )
    else:
        summary = (
            "Los resultados son ganadores por producto, variante y moneda; "
            "no se convierten ni comparan monedas distintas."
        )
    return ComparisonResult(
        groups=result_groups,
        excluded=tuple(excluded),
        summary=summary,
    )
