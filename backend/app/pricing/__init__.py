"""Deterministic price comparison independent of API and persistence."""

from app.pricing.comparator import (
    ComparisonGroup,
    ComparisonResult,
    ExcludedOffer,
    OfferCandidate,
    OfferEvaluation,
    ProductIdentity,
    ShippingCost,
    ShippingStatus,
    compare_offers,
)

__all__ = [
    "ComparisonGroup",
    "ComparisonResult",
    "ExcludedOffer",
    "OfferCandidate",
    "OfferEvaluation",
    "ProductIdentity",
    "ShippingCost",
    "ShippingStatus",
    "compare_offers",
]
