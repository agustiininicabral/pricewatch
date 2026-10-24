from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")


class Availability(StrEnum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"


class ValidationStatus(StrEnum):
    VERIFIED = "verified"
    PENDING_REVIEW = "pending_review"


@dataclass(frozen=True, slots=True)
class ProductObservation:
    domain: str
    source_url: str
    external_id: str | None
    title: str
    amount_minor: int | None
    currency: str | None
    availability: Availability
    observed_at: datetime
    extraction_method: str
    validation_status: ValidationStatus

    def __post_init__(self) -> None:
        if not isinstance(self.availability, Availability):
            raise ValueError("availability debe ser un valor Availability")
        if not isinstance(self.validation_status, ValidationStatus):
            raise ValueError("validation_status debe ser un valor ValidationStatus")
        if self.amount_minor is not None and (
            type(self.amount_minor) is not int or self.amount_minor <= 0
        ):
            raise ValueError("amount_minor debe ser un entero positivo o None")
        if self.currency is not None and not CURRENCY_PATTERN.fullmatch(self.currency):
            raise ValueError(
                "currency debe ser un código de moneda de tres letras mayúsculas o None"
            )
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() != UTC.utcoffset(
            self.observed_at
        ):
            raise ValueError("observed_at debe estar expresado en UTC")
        if self.validation_status is ValidationStatus.VERIFIED and (
            self.amount_minor is None
            or self.currency is None
            or self.availability is Availability.UNKNOWN
        ):
            raise ValueError(
                "Una observación verificada requiere precio, moneda y disponibilidad."
            )


class StoreAdapter(Protocol):
    @property
    def domain(self) -> str:
        """Dominio exacto admitido por el adaptador."""

    def supports_url(self, source_url: str) -> bool:
        """Indica si la URL tiene un dominio y formato admitidos."""

    def extract(self, source_url: str) -> ProductObservation:
        """Devuelve una observación normalizada o lanza un error tipado."""
