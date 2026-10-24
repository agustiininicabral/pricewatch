from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.models import (
    PriceObservation,
    Product,
    ProductVariant,
    AlertEvent,
    AlertRule,
    ShippingQuote,
    Store,
    StoreListing,
    utc_now,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def add_listing(session: Session) -> StoreListing:
    product = Product(name="Auriculares", canonical_key="auriculares-x")
    store = Store(name="Tienda de prueba", slug="prueba", base_domain="example.test")
    session.add_all([product, store])
    session.flush()
    listing = StoreListing(
        store_id=store.id,
        product_id=product.id,
        url="https://example.test/auriculares-x",
        validation_status="valid",
    )
    session.add(listing)
    session.flush()
    return listing


def test_persists_catalog_listing_and_integer_price(session: Session) -> None:
    listing = add_listing(session)
    observed_at = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
    session.add(
        PriceObservation(
            listing_id=listing.id,
            amount_minor=123456,
            currency="ARS",
            availability="in_stock",
            observed_at=observed_at,
            extraction_method="fixture_html",
        )
    )
    session.commit()

    observation = session.scalar(select(PriceObservation))
    assert observation is not None
    assert observation.amount_minor == 123456
    assert observation.currency == "ARS"
    assert observation.observed_at.replace(tzinfo=UTC) == observed_at


def test_rejects_nonpositive_prices(session: Session) -> None:
    listing = add_listing(session)
    session.add(
        PriceObservation(
            listing_id=listing.id,
            amount_minor=0,
            currency="ARS",
            availability="in_stock",
            extraction_method="fixture_html",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_variant_key_is_unique_per_product(session: Session) -> None:
    product = Product(name="Memoria", canonical_key="memoria-x")
    session.add(product)
    session.flush()
    session.add_all(
        [
            ProductVariant(
                product_id=product.id, variant_key="16gb-black", label="16 GB negra"
            ),
            ProductVariant(
                product_id=product.id, variant_key="16gb-black", label="Duplicada"
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_unknown_shipping_is_not_stored_as_free(session: Session) -> None:
    listing = add_listing(session)
    quote = ShippingQuote(
        listing_id=listing.id,
        status="unknown",
        amount_minor=None,
        currency=None,
        source="not_checked",
    )
    session.add(quote)
    session.commit()
    assert quote.status == "unknown"
    assert quote.amount_minor is None


def test_alert_events_reject_duplicate_deduplication_keys(session: Session) -> None:
    product = Product(name="Cámara", canonical_key="camara-x")
    session.add(product)
    session.flush()
    rule = AlertRule(
        product_id=product.id,
        target_amount_minor=120000,
        currency="ARS",
    )
    session.add(rule)
    session.flush()
    session.add_all(
        [
            AlertEvent(
                rule_id=rule.id,
                deduplication_key="rule-1:target-reached:120000",
                event_type="target_reached",
            ),
            AlertEvent(
                rule_id=rule.id,
                deduplication_key="rule-1:target-reached:120000",
                event_type="target_reached",
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_utc_clock_returns_aware_timestamp() -> None:
    assert utc_now().utcoffset().total_seconds() == 0
