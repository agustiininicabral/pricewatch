from datetime import UTC, datetime

import pytest

from app.collectors import (
    Availability,
    ProductObservation,
    ValidationStatus,
)
from app.pricing import (
    OfferCandidate,
    ProductIdentity,
    ShippingCost,
    ShippingStatus,
    compare_offers,
)


def observation(
    *,
    url: str,
    amount: int | None = 10_000,
    currency: str | None = "ARS",
    availability: Availability = Availability.IN_STOCK,
    validation: ValidationStatus = ValidationStatus.VERIFIED,
    title: str = "Producto de prueba",
) -> ProductObservation:
    return ProductObservation(
        domain="fixture.invalid",
        source_url=url,
        external_id=None,
        title=title,
        amount_minor=amount,
        currency=currency,
        availability=availability,
        observed_at=datetime.now(UTC),
        extraction_method="test",
        validation_status=validation,
    )


def candidate(
    url: str,
    *,
    key: str = "product-1",
    variant: str | None = "blue-128gb",
    amount: int | None = 10_000,
    currency: str | None = "ARS",
    shipping: ShippingCost | None = None,
    availability: Availability = Availability.IN_STOCK,
    validation: ValidationStatus = ValidationStatus.VERIFIED,
    identity_verified: bool = True,
) -> OfferCandidate:
    return OfferCandidate(
        identity=ProductIdentity(key, variant, identity_verified),
        observation=observation(
            url=url,
            amount=amount,
            currency=currency,
            availability=availability,
            validation=validation,
        ),
        shipping=shipping or ShippingCost(ShippingStatus.FREE, amount_minor=0),
    )


def test_ranks_known_totals_and_reports_difference_from_cheapest() -> None:
    result = compare_offers(
        [
            candidate(
                "https://store-a.invalid/product",
                amount=10_000,
                shipping=ShippingCost(
                    ShippingStatus.PAID, amount_minor=1_000, currency="ARS"
                ),
            ),
            candidate(
                "https://store-b.invalid/product",
                amount=10_500,
                shipping=ShippingCost(ShippingStatus.FREE, amount_minor=0),
            ),
        ]
    )

    group = result.groups[0]
    assert [offer.total_minor for offer in group.offers] == [10_500, 11_000]
    assert group.cheapest_offer == group.offers[0]
    assert [offer.difference_from_cheapest_minor for offer in group.offers] == [0, 500]
    assert result.excluded == ()


def test_free_shipping_is_explicit_zero_not_unknown() -> None:
    result = compare_offers([candidate("https://store.invalid/product")])

    offer = result.groups[0].cheapest_offer
    assert offer is not None
    assert offer.shipping_status is ShippingStatus.FREE
    assert offer.shipping_minor == 0
    assert offer.total_minor == offer.price_minor


def test_unknown_shipping_does_not_produce_total_or_winner() -> None:
    result = compare_offers(
        [
            candidate(
                "https://store.invalid/product",
                shipping=ShippingCost(ShippingStatus.UNKNOWN),
            )
        ]
    )

    assert len(result.groups) == 1
    assert result.groups[0].cheapest_offer is None
    assert len(result.excluded) == 1
    assert "envío" in result.excluded[0].reason


def test_unknown_shipping_blocks_definitive_winner_for_same_product() -> None:
    result = compare_offers(
        [
            candidate(
                "https://known.invalid/product",
                amount=10_000,
                shipping=ShippingCost(ShippingStatus.FREE, amount_minor=0),
            ),
            candidate(
                "https://unknown.invalid/product",
                amount=9_000,
                shipping=ShippingCost(ShippingStatus.UNKNOWN),
            ),
        ]
    )

    group = result.groups[0]
    assert group.cheapest_offer is None
    assert group.winner_reason is not None
    assert group.blocking_reasons == (
        "https://unknown.invalid/product: envío desconocido",
    )
    assert group.offers[0].difference_from_cheapest_minor is None


def test_currency_buckets_are_never_converted_or_compared() -> None:
    result = compare_offers(
        [
            candidate("https://ars.invalid/product", currency="ARS"),
            candidate("https://usd.invalid/product", currency="USD"),
        ]
    )

    assert {(group.currency, len(group.offers)) for group in result.groups} == {
        ("ARS", 1),
        ("USD", 1),
    }
    assert {group.cheapest_offer.currency for group in result.groups} == {"ARS", "USD"}


def test_paid_shipping_in_different_currency_is_excluded() -> None:
    result = compare_offers(
        [
            candidate(
                "https://store.invalid/product",
                currency="ARS",
                shipping=ShippingCost(
                    ShippingStatus.PAID, amount_minor=100, currency="USD"
                ),
            )
        ]
    )

    assert result.groups == ()
    assert "no coincide" in result.excluded[0].reason


def test_unverified_identity_is_not_compared() -> None:
    result = compare_offers(
        [candidate("https://store.invalid/product", identity_verified=False)]
    )

    assert result.groups == ()
    assert "identidad" in result.excluded[0].reason


def test_product_identity_is_unverified_by_default() -> None:
    result = compare_offers(
        [
            OfferCandidate(
                identity=ProductIdentity("product-1"),
                observation=observation(url="https://store.invalid/product"),
                shipping=ShippingCost(ShippingStatus.FREE, amount_minor=0),
            )
        ]
    )

    assert result.groups == ()
    assert "identidad" in result.excluded[0].reason
    assert "No hay ofertas verificadas" in result.summary


def test_different_products_and_variants_are_partitioned() -> None:
    result = compare_offers(
        [
            candidate("https://a.invalid/phone", key="phone-a"),
            candidate("https://b.invalid/phone", key="phone-b"),
            candidate("https://c.invalid/variant", variant="black-128gb"),
        ]
    )

    assert {
        (group.canonical_key, group.variant_key) for group in result.groups
    } == {
        ("phone-a", "blue-128gb"),
        ("phone-b", "blue-128gb"),
        ("product-1", "black-128gb"),
    }
    assert all(len(group.offers) == 1 for group in result.groups)


@pytest.mark.parametrize(
    ("amount", "currency", "validation", "availability", "reason_fragment"),
    [
        (None, "ARS", ValidationStatus.PENDING_REVIEW, Availability.IN_STOCK, "precio"),
        (10_000, None, ValidationStatus.PENDING_REVIEW, Availability.IN_STOCK, "moneda"),
        (10_000, "ARS", ValidationStatus.PENDING_REVIEW, Availability.IN_STOCK, "revisión"),
        (10_000, "ARS", ValidationStatus.VERIFIED, Availability.OUT_OF_STOCK, "stock"),
        (10_000, "ARS", ValidationStatus.PENDING_REVIEW, Availability.UNKNOWN, "revisión"),
    ],
)
def test_pending_missing_and_unavailable_data_are_excluded(
    amount, currency, validation, availability, reason_fragment
) -> None:
    result = compare_offers(
        [
            candidate(
                "https://store.invalid/product",
                amount=amount,
                currency=currency,
                validation=validation,
                availability=availability,
            )
        ]
    )

    assert result.groups == ()
    assert reason_fragment in result.excluded[0].reason


def test_invalid_price_is_rejected_by_observation_contract() -> None:
    with pytest.raises(ValueError, match="entero positivo"):
        observation(url="https://store.invalid/product", amount=-1)


def test_no_verified_offers_reports_no_winner_and_reasons() -> None:
    result = compare_offers(
        [
            candidate(
                "https://store.invalid/a",
                validation=ValidationStatus.PENDING_REVIEW,
            ),
            candidate(
                "https://store.invalid/b",
                shipping=ShippingCost(ShippingStatus.UNKNOWN),
            ),
        ]
    )

    assert len(result.groups) == 1
    assert result.groups[0].cheapest_offer is None
    assert result.groups[0].winner_reason is not None
    assert len(result.excluded) == 2
    assert "No hay ofertas verificadas" in result.summary
