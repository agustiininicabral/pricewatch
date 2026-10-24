from datetime import UTC

import pytest

from app.collectors import (
    Availability,
    ExtractionFailedError,
    FixtureHtmlAdapter,
    InvalidPriceError,
    ProductObservation,
    SourceUnavailableError,
    StoreAdapter,
    UnsupportedURLError,
    ValidationStatus,
)
from app.collectors import fixture_html

BASE_URL = "https://pricewatch-fixture.invalid"


@pytest.fixture
def adapter() -> FixtureHtmlAdapter:
    return FixtureHtmlAdapter()


def test_valid_fixture_returns_verified_observation(adapter: StoreAdapter) -> None:
    result = adapter.extract(f"{BASE_URL}/valid-stock")

    assert isinstance(result, ProductObservation)
    assert result.domain == adapter.domain
    assert result.source_url == f"{BASE_URL}/valid-stock"
    assert result.external_id == "fixture-001"
    assert result.title == "Auriculares de prueba"
    assert result.amount_minor == 1_299_990
    assert result.currency == "ARS"
    assert result.availability is Availability.IN_STOCK
    assert result.observed_at.utcoffset().total_seconds() == 0
    assert result.extraction_method == "fixture_html"
    assert result.validation_status is ValidationStatus.VERIFIED


def test_missing_price_is_pending_and_not_zero(adapter: FixtureHtmlAdapter) -> None:
    result = adapter.extract(f"{BASE_URL}/missing-price")

    assert result.amount_minor is None
    assert result.availability is Availability.OUT_OF_STOCK
    assert result.validation_status is ValidationStatus.PENDING_REVIEW


def test_inconsistent_fixture_rejects_malformed_price(
    adapter: FixtureHtmlAdapter,
) -> None:
    with pytest.raises(InvalidPriceError):
        adapter.extract(f"{BASE_URL}/inconsistent")


def test_negative_price_is_rejected(adapter: FixtureHtmlAdapter) -> None:
    with pytest.raises(InvalidPriceError):
        adapter.extract(f"{BASE_URL}/negative-price")


@pytest.mark.parametrize("price", ["", "12.3.4", "1,299.00", "-4.00", "0", "0.00"])
def test_rejects_malformed_or_nonpositive_prices(
    adapter: FixtureHtmlAdapter, price: str
) -> None:
    with pytest.raises(InvalidPriceError):
        adapter._parse_price(price)


def test_missing_currency_is_not_assumed_to_be_ars(
    adapter: FixtureHtmlAdapter,
) -> None:
    result = adapter.extract(f"{BASE_URL}/unverified-currency")

    assert result.amount_minor == 25_000
    assert result.currency is None
    assert result.validation_status is ValidationStatus.PENDING_REVIEW


def test_missing_stock_is_unknown_not_extraction_failure(
    adapter: FixtureHtmlAdapter,
) -> None:
    result = adapter._parse_html(
        '<article data-product data-title="Sin dato" '
        'data-price="10.00" data-currency="ARS"></article>',
        f"{BASE_URL}/valid-stock",
    )

    assert result.availability is Availability.UNKNOWN
    assert result.validation_status is ValidationStatus.PENDING_REVIEW


def test_invalid_explicit_availability_fails_extraction(
    adapter: FixtureHtmlAdapter,
) -> None:
    with pytest.raises(ExtractionFailedError):
        adapter.extract(f"{BASE_URL}/invalid-availability")


@pytest.mark.parametrize(
    "url",
    [
        "http://pricewatch-fixture.invalid/valid-stock",
        "https://untrusted.example/valid-stock",
        "https://user@pricewatch-fixture.invalid/valid-stock",
        "https://pricewatch-fixture.invalid:443/valid-stock",
        "https://pricewatch-fixture.invalid/../valid-stock",
        "https://pricewatch-fixture.invalid/valid-stock?redirect=https://example.com",
        "https://pricewatch-fixture.invalid/valid-stock#fragment",
    ],
)
def test_rejects_urls_outside_fixture_contract(
    adapter: FixtureHtmlAdapter, url: str
) -> None:
    assert not adapter.supports_url(url)
    with pytest.raises(UnsupportedURLError):
        adapter.extract(url)


def test_missing_local_fixture_is_source_unavailable(
    adapter: FixtureHtmlAdapter, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(fixture_html, "FIXTURE_DIRECTORY", tmp_path)

    with pytest.raises(SourceUnavailableError):
        adapter.extract(f"{BASE_URL}/valid-stock")


def test_observation_rejects_non_utc_timestamp() -> None:
    from datetime import datetime, timezone, timedelta

    with pytest.raises(ValueError, match="UTC"):
        ProductObservation(
            domain="pricewatch-fixture.invalid",
            source_url=f"{BASE_URL}/valid-stock",
            external_id=None,
            title="Producto",
            amount_minor=100,
            currency="ARS",
            availability=Availability.IN_STOCK,
            observed_at=datetime(2026, 10, 13, tzinfo=timezone(timedelta(hours=-3))),
            extraction_method="fixture_html",
            validation_status=ValidationStatus.VERIFIED,
        )


def test_observation_requires_positive_integer_minor_amount() -> None:
    from datetime import datetime

    with pytest.raises(ValueError, match="positivo"):
        ProductObservation(
            domain="pricewatch-fixture.invalid",
            source_url=f"{BASE_URL}/valid-stock",
            external_id=None,
            title="Producto",
            amount_minor=0,
            currency="ARS",
            availability=Availability.IN_STOCK,
            observed_at=datetime.now(UTC),
            extraction_method="fixture_html",
            validation_status=ValidationStatus.VERIFIED,
        )


def test_observation_rejects_non_integer_minor_amount() -> None:
    from datetime import datetime

    with pytest.raises(ValueError, match="entero positivo"):
        ProductObservation(
            domain="pricewatch-fixture.invalid",
            source_url=f"{BASE_URL}/valid-stock",
            external_id=None,
            title="Producto",
            amount_minor=10.5,
            currency="ARS",
            availability=Availability.IN_STOCK,
            observed_at=datetime.now(UTC),
            extraction_method="fixture_html",
            validation_status=ValidationStatus.VERIFIED,
        )


def test_observation_rejects_unverified_data_marked_as_verified() -> None:
    from datetime import datetime

    with pytest.raises(ValueError, match="requiere precio"):
        ProductObservation(
            domain="pricewatch-fixture.invalid",
            source_url=f"{BASE_URL}/valid-stock",
            external_id=None,
            title="Producto",
            amount_minor=None,
            currency="ARS",
            availability=Availability.IN_STOCK,
            observed_at=datetime.now(UTC),
            extraction_method="fixture_html",
            validation_status=ValidationStatus.VERIFIED,
        )


def test_observation_rejects_malformed_currency() -> None:
    from datetime import datetime

    with pytest.raises(ValueError, match="currency"):
        ProductObservation(
            domain="pricewatch-fixture.invalid",
            source_url=f"{BASE_URL}/valid-stock",
            external_id=None,
            title="Producto",
            amount_minor=100,
            currency="ars",
            availability=Availability.IN_STOCK,
            observed_at=datetime.now(UTC),
            extraction_method="fixture_html",
            validation_status=ValidationStatus.VERIFIED,
        )


def test_observation_rejects_untyped_availability_value() -> None:
    from datetime import datetime

    with pytest.raises(ValueError, match="availability"):
        ProductObservation(
            domain="pricewatch-fixture.invalid",
            source_url=f"{BASE_URL}/valid-stock",
            external_id=None,
            title="Producto",
            amount_minor=100,
            currency="ARS",
            availability="available",
            observed_at=datetime.now(UTC),
            extraction_method="fixture_html",
            validation_status=ValidationStatus.VERIFIED,
        )
