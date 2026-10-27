from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.collectors.contracts import Availability, ValidationStatus
from app.pricing.comparator import ShippingStatus

CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
DOMAIN_PATTERN = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)
MAX_SQLITE_INTEGER = 2**63 - 1


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductCreate(ApiModel):
    name: str = Field(min_length=1, max_length=240)
    canonical_key: str = Field(min_length=1, max_length=160)
    brand: str | None = Field(default=None, max_length=120)
    description: str | None = None

    @field_validator("name", "canonical_key", "brand", mode="before")
    @classmethod
    def strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class ProductUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    canonical_key: str | None = Field(default=None, min_length=1, max_length=160)
    brand: str | None = Field(default=None, max_length=120)
    description: str | None = None
    is_active: bool | None = None

    @field_validator("name", "canonical_key", "brand", mode="before")
    @classmethod
    def strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def required_fields_cannot_be_null(self) -> ProductUpdate:
        for field in ("name", "canonical_key", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} no puede ser null.")
        return self


class ProductResponse(ApiModel):
    id: int
    name: str
    canonical_key: str
    brand: str | None
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ListingCreate(ApiModel):
    store_name: str = Field(min_length=1, max_length=120)
    source_url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=500)
    variant_key: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("store_name", "source_url", "title", "variant_key", mode="before")
    @classmethod
    def strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as error:
            raise ValueError("source_url debe ser una URL HTTP(S) válida.") from error
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 80, 443)
        ):
            raise ValueError("source_url debe ser una URL HTTP(S) válida sin credenciales.")
        return value


class ListingResponse(ApiModel):
    id: int
    product_id: int
    store_name: str
    store_domain: str
    integration_status: str
    store_enabled: bool
    url: str
    title: str | None
    variant_key: str | None
    is_enabled: bool
    validation_status: str
    extraction_method: str | None
    last_checked_at: datetime | None
    created_at: datetime


class ObservationCreate(ApiModel):
    store_name: str = Field(min_length=1, max_length=120)
    store_slug: str = Field(min_length=1, max_length=80)
    store_domain: str = Field(min_length=1, max_length=253)
    source_url: str = Field(min_length=1, max_length=2048)
    external_id: str | None = Field(default=None, max_length=160)
    title: str = Field(min_length=1, max_length=500)
    amount_minor: int = Field(gt=0, le=MAX_SQLITE_INTEGER, strict=True)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    availability: Availability
    observed_at: datetime | None = None
    extraction_method: str = Field(min_length=1, max_length=40)
    validation_status: ValidationStatus
    variant_key: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator(
        "store_name", "store_slug", "store_domain", "title", "extraction_method",
        "external_id", "variant_key", mode="before"
    )
    @classmethod
    def strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("store_slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        if not SLUG_PATTERN.fullmatch(value):
            raise ValueError("store_slug solo admite letras minúsculas, números y guiones.")
        return value

    @field_validator("store_domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        domain = value.rstrip(".").lower()
        if not domain or any(char in domain for char in "/:@?#"):
            raise ValueError("store_domain debe ser un hostname sin esquema ni ruta.")
        if not DOMAIN_PATTERN.fullmatch(domain):
            raise ValueError("store_domain debe ser un hostname válido.")
        return domain

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 80, 443)
        ):
            raise ValueError("source_url debe ser una URL HTTP(S) válida sin credenciales.")
        return value

    @field_validator("observed_at")
    @classmethod
    def normalize_observed_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at debe incluir zona horaria.")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_host_matches_store(self) -> ObservationCreate:
        host = urlsplit(self.source_url).hostname
        if host is None or not (host == self.store_domain or host.endswith(f".{self.store_domain}")):
            raise ValueError("El hostname de source_url debe pertenecer a store_domain.")
        return self


class ObservationResponse(ApiModel):
    id: int
    listing_id: int
    store_name: str
    store_domain: str
    source_url: str
    external_id: str | None
    title: str
    amount_minor: int
    currency: str
    availability: Availability
    observed_at: datetime
    extraction_method: str
    validation_status: ValidationStatus


class ShippingQuoteCreate(ApiModel):
    status: str = Field(pattern=r"^(known|unknown)$")
    amount_minor: int | None = Field(
        default=None, ge=0, le=MAX_SQLITE_INTEGER, strict=True
    )
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    source: str = Field(min_length=1, max_length=120)
    quoted_at: datetime | None = None

    @field_validator("quoted_at")
    @classmethod
    def normalize_quoted_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("quoted_at debe incluir zona horaria.")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_shipping_fields(self) -> ShippingQuoteCreate:
        if self.status == "unknown":
            if self.amount_minor is not None or self.currency is not None:
                raise ValueError("El envío desconocido no admite importe ni moneda.")
        elif self.amount_minor is None or self.currency is None:
            raise ValueError("El envío conocido requiere importe y moneda explícitos.")
        return self


class ShippingQuoteResponse(ApiModel):
    id: int
    listing_id: int
    status: str
    amount_minor: int | None
    currency: str | None
    source: str
    quoted_at: datetime


class OfferResponse(ApiModel):
    source_url: str
    title: str
    currency: str
    price_minor: int
    shipping_status: ShippingStatus
    shipping_minor: int | None
    total_minor: int
    difference_from_cheapest_minor: int | None


class ComparisonGroupResponse(ApiModel):
    canonical_key: str
    variant_key: str | None
    currency: str
    offers: list[OfferResponse]
    cheapest_offer: OfferResponse | None
    winner_reason: str | None
    blocking_reasons: list[str]


class ExcludedOfferResponse(ApiModel):
    source_url: str
    reason: str


class ComparisonResponse(ApiModel):
    product_id: int
    groups: list[ComparisonGroupResponse]
    excluded: list[ExcludedOfferResponse]
    summary: str



class AlertRuleCreate(ApiModel):
    target_amount_minor: int | None = Field(default=None, gt=0, strict=True)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    minimum_reduction_basis_points: int | None = Field(default=None, ge=1, le=10000, strict=True)
    variant_key: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def require_a_supported_trigger(self) -> AlertRuleCreate:
        if self.target_amount_minor is None and self.minimum_reduction_basis_points is None:
            raise ValueError("Configura un precio objetivo o una reducción mínima.")
        if self.currency is None:
            raise ValueError("La moneda es obligatoria para evaluar alertas de precio.")
        return self


class AlertRuleResponse(ApiModel):
    id: int
    product_id: int
    variant_key: str | None
    target_amount_minor: int | None
    currency: str | None
    minimum_reduction_basis_points: int | None
    notification_interval_hours: int
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class AlertEventResponse(ApiModel):
    id: int
    rule_id: int
    event_type: str
    state: str
    triggered_at: datetime
    payload: dict[str, Any]


class HealthResponse(ApiModel):
    status: str
    database: str


class ExecutionResponse(ApiModel):
    id: int
    product_id: int | None
    listing_id: int | None
    trigger: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    listings_checked: int
    listings_succeeded: int
    listings_failed: int
    errors: list[str]
