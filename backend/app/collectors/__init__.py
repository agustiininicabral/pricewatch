"""Store data collection adapters."""

from app.collectors.contracts import (
    Availability,
    ProductObservation,
    StoreAdapter,
    ValidationStatus,
)
from app.collectors.errors import (
    ExtractionFailedError,
    InvalidPriceError,
    SourceUnavailableError,
    StoreAdapterError,
    UnsupportedURLError,
)
from app.collectors.fixture_html import FixtureHtmlAdapter

__all__ = [
    "Availability",
    "ExtractionFailedError",
    "FixtureHtmlAdapter",
    "InvalidPriceError",
    "ProductObservation",
    "SourceUnavailableError",
    "StoreAdapter",
    "StoreAdapterError",
    "UnsupportedURLError",
    "ValidationStatus",
]
