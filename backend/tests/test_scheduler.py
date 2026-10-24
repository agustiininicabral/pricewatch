from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.collectors.contracts import (
    Availability,
    ProductObservation,
    ValidationStatus,
)
from app.collectors.errors import (
    ExtractionFailedError,
    InvalidPriceError,
    SourceUnavailableError,
)
from app.database.base import Base
from app.database.models import (
    ExecutionRun,
    PriceObservation,
    Product,
    Store,
    StoreListing,
)
from app.database.session import make_engine
from app.scheduler.service import (
    DuplicateUpdateError,
    PeriodicScheduler,
    UpdateCoordinator,
    UpdateService,
    UpdateSettings,
)

DOMAIN = "authorized-fixture.example.test"
URL = f"https://{DOMAIN}/item/1"


class FakeAdapter:
    domain = DOMAIN

    def __init__(
        self,
        behavior: ProductObservation | Exception | Callable[[], ProductObservation],
    ) -> None:
        self.behavior = behavior
        self.calls = 0

    def supports_url(self, source_url: str) -> bool:
        return source_url.startswith(f"https://{self.domain}/")

    def extract(self, source_url: str) -> ProductObservation:
        self.calls += 1
        if not self.supports_url(source_url):
            raise ValueError("unsupported test source")
        if isinstance(self.behavior, Exception):
            raise self.behavior
        if callable(self.behavior):
            return self.behavior()
        return self.behavior


def make_observation(
    *,
    amount_minor: int = 15_000,
    validation: ValidationStatus = ValidationStatus.VERIFIED,
) -> ProductObservation:
    return ProductObservation(
        domain=DOMAIN,
        source_url=URL,
        external_id="sku-1",
        title="Producto de prueba",
        amount_minor=amount_minor,
        currency="ARS",
        availability=Availability.IN_STOCK,
        observed_at=datetime.now(UTC),
        extraction_method="fake-authorized-source",
        validation_status=validation,
    )


@pytest.fixture
def database(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'scheduler-test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        product = Product(name="Producto", canonical_key="producto")
        store = Store(
            name="Tienda prueba",
            slug="tienda-prueba",
            base_domain=DOMAIN,
            integration_status="active",
            is_enabled=True,
        )
        session.add_all([product, store])
        session.flush()
        listing = StoreListing(
            store_id=store.id,
            product_id=product.id,
            external_id="sku-1",
            url=URL,
            title="Producto previo",
            is_enabled=True,
            validation_status="valid",
            extraction_method="seed",
        )
        session.add(listing)
        session.flush()
        previous = PriceObservation(
            listing_id=listing.id,
            amount_minor=20_000,
            currency="ARS",
            availability="in_stock",
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            is_valid=True,
            extraction_method="seed",
            source_reference=URL,
        )
        session.add(previous)
        session.commit()
        ids = (product.id, store.id, listing.id, previous.id)
    yield factory, ids
    engine.dispose()


def create_run(factory: sessionmaker[Session], listing_id: int) -> int:
    with factory() as session:
        listing = session.get(StoreListing, listing_id)
        assert listing is not None
        run = ExecutionRun(
            trigger="manual",
            status="running",
            product_id=listing.product_id,
            listing_id=listing_id,
        )
        session.add(run)
        session.commit()
        return run.id


def test_successful_update_persists_new_observation_and_run(database) -> None:
    factory, (_, _, listing_id, _) = database
    adapter = FakeAdapter(make_observation(amount_minor=15_000))
    run_id = create_run(factory, listing_id)

    UpdateService(factory, {DOMAIN: adapter}, minimum_request_interval_seconds=0).execute(
        run_id, [listing_id]
    )

    with factory() as session:
        run = session.get(ExecutionRun, run_id)
        observations = list(
            session.scalars(
                select(PriceObservation)
                .where(PriceObservation.listing_id == listing_id)
                .order_by(PriceObservation.observed_at, PriceObservation.id)
            )
        )
        listing = session.get(StoreListing, listing_id)
        assert run is not None
        assert run.status == "succeeded"
        assert run.listings_checked == 1
        assert run.listings_succeeded == 1
        assert run.listings_failed == 0
        assert run.completed_at is not None
        assert run.error_summary is None
        assert [item.amount_minor for item in observations] == [20_000, 15_000]
        assert observations[-1].is_valid is True
        assert observations[-1].extraction_method == "fake-authorized-source"
        assert observations[-1].source_reference == URL
        assert listing is not None and listing.last_checked_at is not None


@pytest.mark.parametrize(
    ("error", "expected_type"),
    [
        (SourceUnavailableError("simulated timeout"), "SourceUnavailableError"),
        (InvalidPriceError("simulated malformed price"), "InvalidPriceError"),
        (ExtractionFailedError("simulated blocked or changed HTML"), "ExtractionFailedError"),
    ],
)
def test_failed_updates_preserve_last_valid_price_and_record_error(
    database, error: Exception, expected_type: str
) -> None:
    factory, (_, _, listing_id, previous_id) = database
    adapter = FakeAdapter(error)
    run_id = create_run(factory, listing_id)

    UpdateService(factory, {DOMAIN: adapter}, minimum_request_interval_seconds=0).execute(
        run_id, [listing_id]
    )

    with factory() as session:
        run = session.get(ExecutionRun, run_id)
        observations = list(
            session.scalars(
                select(PriceObservation).where(
                    PriceObservation.listing_id == listing_id
                )
            )
        )
        previous = session.get(PriceObservation, previous_id)
        listing = session.get(StoreListing, listing_id)
        assert run is not None and run.status == "failed"
        assert run.listings_failed == 1
        assert expected_type in (run.error_summary or "")
        assert str(error) not in (run.error_summary or "")
        assert len(observations) == 1
        assert previous is not None and previous.amount_minor == 20_000
        assert listing is not None and listing.last_checked_at is not None


def test_pending_result_is_not_saved_as_verified(database) -> None:
    factory, (_, _, listing_id, _) = database
    adapter = FakeAdapter(
        make_observation(
            amount_minor=15_000,
            validation=ValidationStatus.PENDING_REVIEW,
        )
    )
    run_id = create_run(factory, listing_id)

    UpdateService(factory, {DOMAIN: adapter}, minimum_request_interval_seconds=0).execute(
        run_id, [listing_id]
    )

    with factory() as session:
        run = session.get(ExecutionRun, run_id)
        prices = list(session.scalars(select(PriceObservation)))
        assert run is not None and run.status == "failed"
        assert run.error_summary is not None
        assert len(prices) == 1
        assert prices[0].is_valid is True
        assert prices[0].amount_minor == 20_000


def test_update_continues_after_one_publication_fails(database) -> None:
    factory, (product_id, _, first_listing_id, _) = database
    with factory() as session:
        other_store = Store(
            name="Otra tienda",
            slug="otra-tienda",
            base_domain="other-authorized.example.test",
            integration_status="active",
            is_enabled=True,
        )
        session.add(other_store)
        session.flush()
        second_listing = StoreListing(
            store_id=other_store.id,
            product_id=product_id,
            url="https://other-authorized.example.test/item/2",
            title="Segundo producto",
            is_enabled=True,
            validation_status="valid",
            extraction_method="seed",
        )
        session.add(second_listing)
        session.flush()
        run = ExecutionRun(
            trigger="manual",
            status="running",
            product_id=product_id,
        )
        session.add(run)
        session.commit()
        second_listing_id = second_listing.id
        run_id = run.id

    failing_adapter = FakeAdapter(SourceUnavailableError("simulated unavailable"))

    class OtherAdapter(FakeAdapter):
        domain = "other-authorized.example.test"

        def supports_url(self, source_url: str) -> bool:
            return source_url.startswith(f"https://{self.domain}/")

        def extract(self, source_url: str) -> ProductObservation:
            self.calls += 1
            return ProductObservation(
                domain=self.domain,
                source_url=source_url,
                external_id=None,
                title="Segundo producto",
                amount_minor=12_000,
                currency="ARS",
                availability=Availability.IN_STOCK,
                observed_at=datetime.now(UTC),
                extraction_method="other-adapter",
                validation_status=ValidationStatus.VERIFIED,
            )

    service = UpdateService(
        factory,
        {
            DOMAIN: failing_adapter,
            "other-authorized.example.test": OtherAdapter(make_observation()),
        },
        minimum_request_interval_seconds=0,
    )
    service.execute(run_id, [first_listing_id, second_listing_id])

    with factory() as session:
        stored_run = session.get(ExecutionRun, run_id)
        assert stored_run is not None
        assert stored_run.status == "partial"
        assert stored_run.listings_checked == 2
        assert stored_run.listings_succeeded == 1
        assert stored_run.listings_failed == 1
        assert "SourceUnavailableError" in (stored_run.error_summary or "")
        assert session.scalar(
            select(func.count()).select_from(PriceObservation)
        ) == 2


def test_missing_adapter_is_recorded_without_overwriting_history(database) -> None:
    factory, (_, _, listing_id, _) = database
    run_id = create_run(factory, listing_id)

    UpdateService(factory, {}, minimum_request_interval_seconds=0).execute(
        run_id, [listing_id]
    )

    with factory() as session:
        run = session.get(ExecutionRun, run_id)
        count = session.scalar(select(func.count()).select_from(PriceObservation))
        assert run is not None and run.status == "failed"
        assert "AdapterNotReadyError" in (run.error_summary or "")
        assert count == 1


def test_coordinator_rejects_simultaneous_duplicate_listing_updates(database) -> None:
    factory, (_, _, listing_id, _) = database
    adapter_started = threading.Event()
    release_adapter = threading.Event()

    def blocking_observation() -> ProductObservation:
        adapter_started.set()
        if not release_adapter.wait(timeout=5):
            raise TimeoutError("test adapter timed out")
        return make_observation()

    coordinator = UpdateCoordinator(
        factory,
        {DOMAIN: FakeAdapter(blocking_observation)},
        UpdateSettings(86_400, 10),
    )
    try:
        run = coordinator.enqueue_listing(listing_id)
        assert adapter_started.wait(timeout=5)
        with pytest.raises(DuplicateUpdateError):
            coordinator.enqueue_listing(listing_id)
        release_adapter.set()
        coordinator.wait_for_run(run.id, timeout=5)
    finally:
        release_adapter.set()
        coordinator.stop()

    with factory() as session:
        runs = list(session.scalars(select(ExecutionRun)))
        assert len(runs) == 1
        assert runs[0].status == "succeeded"


def test_product_update_and_scheduled_update_use_enabled_listings(database) -> None:
    factory, (product_id, _, listing_id, _) = database
    adapter = FakeAdapter(make_observation())
    coordinator = UpdateCoordinator(
        factory,
        {DOMAIN: adapter},
        UpdateSettings(86_400, 10),
    )
    coordinator.service._minimum_interval = 0
    try:
        run = coordinator.enqueue_product(product_id)
        coordinator.wait_for_run(run.id, timeout=5)
        scheduled = coordinator.enqueue_scheduled()
        assert scheduled is not None
        coordinator.wait_for_run(scheduled.id, timeout=5)
    finally:
        coordinator.stop()

    with factory() as session:
        runs = list(
            session.scalars(
                select(ExecutionRun).order_by(ExecutionRun.id)
            )
        )
        assert runs[0].product_id == product_id
        assert runs[0].listing_id is None
        assert runs[0].trigger == "manual"
        assert runs[1].trigger == "scheduled"
        assert runs[1].listings_succeeded == 1
    assert adapter.calls == 2
    assert listing_id > 0


def test_scheduler_interval_is_daily_by_default_and_not_aggressive(monkeypatch) -> None:
    monkeypatch.delenv("PRICEWATCH_UPDATE_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("PRICEWATCH_MIN_REQUEST_INTERVAL_SECONDS", raising=False)
    assert UpdateSettings.from_environment().interval_seconds == 86_400
    monkeypatch.setenv("PRICEWATCH_UPDATE_INTERVAL_SECONDS", "3599")
    with pytest.raises(ValueError, match="una hora"):
        UpdateSettings.from_environment()
    monkeypatch.setenv("PRICEWATCH_UPDATE_INTERVAL_SECONDS", "3600")
    monkeypatch.setenv("PRICEWATCH_MIN_REQUEST_INTERVAL_SECONDS", "9")
    with pytest.raises(ValueError, match="10 segundos"):
        UpdateSettings.from_environment()
    with pytest.raises(ValueError, match="una hora"):
        PeriodicScheduler(3599, lambda: None)


def test_rate_limiter_waits_between_queries_to_same_domain(database) -> None:
    factory, _ = database
    now = [10.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    service = UpdateService(
        session_factory=factory,
        adapters={},
        minimum_request_interval_seconds=30,
        monotonic=lambda: now[0],
        sleep=sleep,
    )
    service._wait_for_store_interval(DOMAIN)
    now[0] += 5
    service._wait_for_store_interval(DOMAIN)

    assert waits == [25]


def test_scheduler_can_stop_without_waiting_for_interval() -> None:
    calls: list[bool] = []
    scheduler = PeriodicScheduler(86_400, lambda: calls.append(True))

    scheduler.start()
    assert scheduler.is_running
    scheduler.stop()

    assert not scheduler.is_running
    assert calls == []
