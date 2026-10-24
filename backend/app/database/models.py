from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Store(Base):
    __tablename__ = "stores"
    __table_args__ = (
        CheckConstraint(
            "integration_status IN ('pending', 'tested', 'active', 'disabled')",
            name="integration_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    base_domain: Mapped[str] = mapped_column(String(253), nullable=False, unique=True)
    integration_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    listings: Mapped[list[StoreListing]] = relationship(back_populates="store")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    canonical_key: Mapped[str] = mapped_column(
        String(160), nullable=False, unique=True
    )
    brand: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    variants: Mapped[list[ProductVariant]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    listings: Mapped[list[StoreListing]] = relationship(back_populates="product")
    alert_rules: Mapped[list[AlertRule]] = relationship(back_populates="product")


class ProductVariant(Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("product_id", "variant_key", name="uq_variant_product_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    variant_key: Mapped[str] = mapped_column(String(160), nullable=False)
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    product: Mapped[Product] = relationship(back_populates="variants")
    listings: Mapped[list[StoreListing]] = relationship(back_populates="variant")


class StoreListing(Base):
    __tablename__ = "store_listings"
    __table_args__ = (
        UniqueConstraint("store_id", "external_id", name="uq_listing_store_external"),
        CheckConstraint(
            "validation_status IN ('pending', 'valid', 'invalid')",
            name="validation_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="SET NULL")
    )
    external_id: Mapped[str | None] = mapped_column(String(160))
    url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(String(500))
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    validation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    extraction_method: Mapped[str | None] = mapped_column(String(40))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    store: Mapped[Store] = relationship(back_populates="listings")
    product: Mapped[Product] = relationship(back_populates="listings")
    variant: Mapped[ProductVariant | None] = relationship(back_populates="listings")
    price_observations: Mapped[list[PriceObservation]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )
    shipping_quotes: Mapped[list[ShippingQuote]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="positive_amount"),
        CheckConstraint("length(currency) = 3", name="currency_length"),
        CheckConstraint(
            "availability IN ('in_stock', 'out_of_stock', 'unknown')",
            name="availability",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("store_listings.id", ondelete="CASCADE"), nullable=False
    )
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    availability: Mapped[str] = mapped_column(String(20), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    extraction_method: Mapped[str] = mapped_column(String(40), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(2048))

    listing: Mapped[StoreListing] = relationship(back_populates="price_observations")


class ShippingQuote(Base):
    __tablename__ = "shipping_quotes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('known', 'unknown')",
            name="shipping_status",
        ),
        CheckConstraint(
            "(status = 'known' AND amount_minor IS NOT NULL AND amount_minor >= 0 "
            "AND currency IS NOT NULL) OR "
            "(status = 'unknown' AND amount_minor IS NULL)",
            name="shipping_amount_consistency",
        ),
        CheckConstraint(
            "currency IS NULL OR length(currency) = 3",
            name="currency_length",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("store_listings.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_minor: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(3))
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    quoted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    listing: Mapped[StoreListing] = relationship(back_populates="shipping_quotes")


class AlertRule(Base):
    __tablename__ = "alert_rules"
    __table_args__ = (
        CheckConstraint("target_amount_minor IS NULL OR target_amount_minor > 0", name="target_amount"),
        CheckConstraint(
            "(target_amount_minor IS NULL AND currency IS NULL) OR "
            "(target_amount_minor IS NOT NULL AND currency IS NOT NULL)",
            name="target_currency_consistency",
        ),
        CheckConstraint(
            "currency IS NULL OR length(currency) = 3",
            name="currency_length",
        ),
        CheckConstraint(
            "minimum_reduction_basis_points IS NULL OR "
            "minimum_reduction_basis_points BETWEEN 0 AND 10000",
            name="reduction_range",
        ),
        CheckConstraint("notification_interval_hours >= 0", name="notification_interval"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    target_amount_minor: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(3))
    minimum_reduction_basis_points: Mapped[int | None] = mapped_column(Integer)
    detect_new_cheapest: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    notification_interval_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=24
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    product: Mapped[Product] = relationship(back_populates="alert_rules")
    events: Mapped[list[AlertEvent]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        UniqueConstraint("deduplication_key", name="uq_alert_deduplication_key"),
        CheckConstraint(
            "state IN ('pending', 'notified', 'dismissed')",
            name="alert_state",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False
    )
    deduplication_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    rule: Mapped[AlertRule] = relationship(back_populates="events")


class ExecutionRun(Base):
    __tablename__ = "execution_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed')",
            name="execution_status",
        ),
        CheckConstraint(
            "trigger IN ('manual', 'scheduled')",
            name="execution_trigger",
        ),
        CheckConstraint("listings_checked >= 0", name="listings_checked_nonnegative"),
        CheckConstraint("listings_succeeded >= 0", name="listings_succeeded_nonnegative"),
        CheckConstraint("listings_failed >= 0", name="listings_failed_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL")
    )
    listing_id: Mapped[int | None] = mapped_column(
        ForeignKey("store_listings.id", ondelete="SET NULL")
    )
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    listings_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    listings_succeeded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    listings_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
