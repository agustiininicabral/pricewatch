from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from app.collectors.contracts import (
    Availability,
    CURRENCY_PATTERN,
    ProductObservation,
    ValidationStatus,
)
from app.collectors.errors import (
    ExtractionFailedError,
    InvalidPriceError,
    SourceUnavailableError,
    UnsupportedURLError,
)

FIXTURE_DOMAIN = "pricewatch-fixture.invalid"
FIXTURE_DIRECTORY = Path(__file__).with_name("fixtures")
FIXTURE_FILES = {
    "valid-stock": "valid-stock.html",
    "missing-price": "missing-price.html",
    "inconsistent": "inconsistent.html",
    "negative-price": "negative-price.html",
    "unverified-currency": "unverified-currency.html",
    "invalid-availability": "invalid-availability.html",
}
PRICE_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?\Z")
MAX_AMOUNT_MINOR = 2**63 - 1


class FixtureHtmlAdapter:
    """Lee HTML de pruebas local; nunca realiza solicitudes de red."""

    @property
    def domain(self) -> str:
        return FIXTURE_DOMAIN

    def supports_url(self, source_url: str) -> bool:
        try:
            parsed = urlsplit(source_url)
            return (
                parsed.scheme == "https"
                and parsed.hostname == self.domain
                and parsed.port is None
                and parsed.username is None
                and parsed.password is None
                and parsed.query == ""
                and parsed.fragment == ""
                and parsed.path.removeprefix("/") in FIXTURE_FILES
                and parsed.path.count("/") == 1
            )
        except ValueError:
            return False

    def extract(self, source_url: str) -> ProductObservation:
        if not self.supports_url(source_url):
            raise UnsupportedURLError("La URL no corresponde a un fixture admitido.")

        path = urlsplit(source_url).path.removeprefix("/")
        fixture_path = FIXTURE_DIRECTORY / FIXTURE_FILES[path]
        try:
            html = fixture_path.read_text(encoding="utf-8")
        except OSError as error:
            raise SourceUnavailableError(
                f"No se pudo leer el fixture local '{fixture_path.name}'."
            ) from error

        return self._parse_html(html, source_url)

    @staticmethod
    def _parse_html(html: str, source_url: str) -> ProductObservation:
        soup = BeautifulSoup(html, "html.parser")
        product = soup.select_one("[data-product]")
        if product is None:
            raise ExtractionFailedError("El HTML no contiene un producto identificable.")

        title = product.get("data-title", "").strip()
        if not title:
            raise ExtractionFailedError("El producto no contiene un título.")

        raw_price = product.get("data-price")
        amount_minor = (
            None if raw_price is None else FixtureHtmlAdapter._parse_price(raw_price)
        )

        raw_currency = product.get("data-currency")
        currency = None if raw_currency is None else raw_currency.strip()
        if currency is not None and not CURRENCY_PATTERN.fullmatch(currency):
            raise ExtractionFailedError("La moneda indicada no es un código válido.")

        raw_availability = product.get("data-availability")
        if raw_availability is None:
            availability = Availability.UNKNOWN
        else:
            try:
                availability = Availability(raw_availability.strip())
            except ValueError as error:
                raise ExtractionFailedError(
                    "El valor explícito de disponibilidad no es válido."
                ) from error

        validation_status = (
            ValidationStatus.VERIFIED
            if amount_minor is not None
            and currency is not None
            and availability is not Availability.UNKNOWN
            else ValidationStatus.PENDING_REVIEW
        )
        return ProductObservation(
            domain=FIXTURE_DOMAIN,
            source_url=source_url,
            external_id=product.get("data-external-id") or None,
            title=title,
            amount_minor=amount_minor,
            currency=currency,
            availability=availability,
            observed_at=datetime.now(UTC),
            extraction_method="fixture_html",
            validation_status=validation_status,
        )

    @staticmethod
    def _parse_price(raw_price: str) -> int:
        normalized = raw_price.strip()
        if not PRICE_PATTERN.fullmatch(normalized):
            raise InvalidPriceError("El precio no tiene un formato decimal admitido.")
        if len(normalized) > 20:
            raise InvalidPriceError("El precio supera el máximo representable.")
        try:
            amount = Decimal(normalized)
            amount_minor = int(amount * 100)
        except (InvalidOperation, ValueError, OverflowError) as error:
            raise InvalidPriceError(
                "No se pudo convertir el precio a unidades menores."
            ) from error
        if amount <= 0 or amount_minor <= 0:
            raise InvalidPriceError("El precio debe ser mayor que cero.")
        if amount_minor > MAX_AMOUNT_MINOR:
            raise InvalidPriceError("El precio supera el máximo representable.")
        return amount_minor
