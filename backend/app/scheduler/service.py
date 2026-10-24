from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.collectors.contracts import StoreAdapter, ValidationStatus
from app.collectors.errors import StoreAdapterError
from app.database.models import (
    ExecutionRun,
    PriceObservation,
    Product,
    Store,
    StoreListing,
    utc_now,
)


class UpdateCoordinatorError(Exception):
    """An update could not be queued or safely run."""


class DuplicateUpdateError(UpdateCoordinatorError):
    """At least one selected listing already has a queued or active update."""


class NoEligibleListingsError(UpdateCoordinatorError):
    """The requested scope has no enabled publications to update."""


class AdapterNotReadyError(StoreAdapterError):
    """The source has no registered and explicitly enabled adapter."""


@dataclass(frozen=True, slots=True)
class UpdateSettings:
    interval_seconds: int = 86_400
    minimum_request_interval_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.interval_seconds < 3_600:
            raise ValueError("El intervalo automático mínimo es de una hora.")
        if self.minimum_request_interval_seconds < 10:
            raise ValueError(
                "El intervalo mínimo entre consultas debe ser de al menos 10 segundos."
            )

    @classmethod
    def from_environment(cls) -> UpdateSettings:
        import os

        return cls(
            interval_seconds=int(
                os.getenv("PRICEWATCH_UPDATE_INTERVAL_SECONDS", "86400")
            ),
            minimum_request_interval_seconds=float(
                os.getenv("PRICEWATCH_MIN_REQUEST_INTERVAL_SECONDS", "60")
            ),
        )


AdapterRegistry = Mapping[str, StoreAdapter]
logger = logging.getLogger(__name__)


class UpdateService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        adapters: AdapterRegistry,
        minimum_request_interval_seconds: float = 60.0,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        import time

        self._session_factory = session_factory
        self._adapters = adapters
        self._minimum_interval = minimum_request_interval_seconds
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep
        self._rate_lock = threading.Lock()
        self._last_request_at: dict[str, float] = {}

    @property
    def adapter_domains(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def execute(
        self,
        run_id: int,
        listing_ids: Sequence[int],
    ) -> None:
        errors: list[str] = []
        succeeded = 0
        checked = 0
        for listing_id in listing_ids:
            checked += 1
            try:
                self._update_listing(listing_id)
                succeeded += 1
            except StoreAdapterError as error:
                errors.append(f"listing_id={listing_id}: {type(error).__name__}")
            except Exception as error:
                errors.append(
                    f"listing_id={listing_id}: error interno ({type(error).__name__})"
                )
        with self._session_factory() as session:
            run = session.get(ExecutionRun, run_id)
            if run is None:
                raise UpdateCoordinatorError("La ejecución desapareció de la base.")
            run.listings_checked = checked
            run.listings_succeeded = succeeded
            run.listings_failed = checked - succeeded
            run.completed_at = utc_now()
            run.error_summary = "\n".join(errors) if errors else None
            if not errors:
                run.status = "succeeded"
            elif succeeded:
                run.status = "partial"
            else:
                run.status = "failed"
            session.commit()

    def _update_listing(self, listing_id: int) -> None:
        with self._session_factory() as session:
            listing = session.scalar(
                select(StoreListing)
                .options(
                    joinedload(StoreListing.store),
                    joinedload(StoreListing.product),
                )
                .where(StoreListing.id == listing_id)
            )
            if listing is None:
                raise AdapterNotReadyError("La publicación no existe.")
            adapter = self._adapters.get(listing.store.base_domain)
            if (
                adapter is None
                or adapter.domain != listing.store.base_domain
                or not listing.store.is_enabled
                or listing.store.integration_status != "active"
            ):
                listing.last_checked_at = utc_now()
                session.commit()
                raise AdapterNotReadyError("La integración de la tienda no está habilitada.")
            if not listing.is_enabled or not listing.product.is_active:
                listing.last_checked_at = utc_now()
                session.commit()
                raise AdapterNotReadyError("La publicación o producto está desactivado.")
            source_url = listing.url
            domain = listing.store.base_domain

        try:
            supports_url = adapter.supports_url(source_url)
        except Exception as error:
            self._record_attempt_time(listing_id)
            raise StoreAdapterError("El adaptador falló al validar la URL.") from error
        if not supports_url:
            self._record_attempt_time(listing_id)
            raise AdapterNotReadyError("El adaptador no admite esta URL.")

        self._wait_for_store_interval(domain)
        try:
            result = adapter.extract(source_url)
        except StoreAdapterError:
            self._record_attempt_time(listing_id)
            raise
        except Exception as error:
            self._record_attempt_time(listing_id)
            raise StoreAdapterError("El adaptador produjo un error no tipado.") from error

        self._record_attempt_time(listing_id)
        if result.domain != domain or result.source_url != source_url:
            raise StoreAdapterError("El adaptador devolvió una procedencia distinta.")
        if result.validation_status is not ValidationStatus.VERIFIED:
            raise StoreAdapterError("La observación requiere revisión y no se guardó.")
        if result.amount_minor is None or result.currency is None:
            raise StoreAdapterError("La observación no contiene un precio comparable.")

        with self._session_factory() as session:
            listing = session.scalar(
                select(StoreListing)
                .options(joinedload(StoreListing.product))
                .where(StoreListing.id == listing_id)
            )
            if listing is None:
                raise AdapterNotReadyError("La publicación desapareció durante la consulta.")
            listing.last_checked_at = utc_now()
            listing.title = result.title
            listing.external_id = result.external_id
            listing.validation_status = "valid"
            listing.extraction_method = result.extraction_method
            session.add(
                PriceObservation(
                    listing_id=listing.id,
                    amount_minor=result.amount_minor,
                    currency=result.currency,
                    availability=result.availability.value,
                    observed_at=result.observed_at.astimezone(UTC),
                    is_valid=True,
                    extraction_method=result.extraction_method,
                    source_reference=result.source_url,
                )
            )
            session.commit()

    def _record_attempt_time(self, listing_id: int) -> None:
        with self._session_factory() as session:
            listing = session.get(StoreListing, listing_id)
            if listing is not None:
                listing.last_checked_at = utc_now()
                session.commit()

    def _wait_for_store_interval(self, domain: str) -> None:
        with self._rate_lock:
            now = self._monotonic()
            previous = self._last_request_at.get(domain)
            if previous is not None:
                wait_seconds = self._minimum_interval - (now - previous)
                if wait_seconds > 0:
                    self._sleep(wait_seconds)
                    now = self._monotonic()
            self._last_request_at[domain] = now


class UpdateCoordinator:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        adapters: AdapterRegistry | None = None,
        settings: UpdateSettings | None = None,
    ) -> None:
        self.settings = settings or UpdateSettings.from_environment()
        self.service = UpdateService(
            session_factory,
            adapters or {},
            self.settings.minimum_request_interval_seconds,
        )
        self._session_factory = session_factory
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="pricewatch-update"
        )
        self._lock = threading.Lock()
        self._active_listing_ids: set[int] = set()
        self._futures: dict[int, Future[None]] = {}
        self._scheduler: PeriodicScheduler | None = None
        self._closed = False

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise UpdateCoordinatorError("El coordinador ya está detenido.")
            if self._scheduler is not None:
                return
            self._scheduler = PeriodicScheduler(
                self.settings.interval_seconds,
                self.enqueue_scheduled,
            )
            self._scheduler.start()

    def stop(self) -> None:
        scheduler = self._scheduler
        if scheduler is not None:
            scheduler.stop()
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=False)

    def enqueue_listing(self, listing_id: int) -> ExecutionRun:
        with self._session_factory() as session:
            listing = session.scalar(
                select(StoreListing)
                .options(joinedload(StoreListing.product))
                .where(StoreListing.id == listing_id)
            )
            if listing is None:
                raise NoEligibleListingsError("No existe la publicación.")
            if not listing.is_enabled or not listing.product.is_active:
                raise NoEligibleListingsError(
                    "La publicación o producto está desactivado."
                )
            return self._enqueue(
                session,
                [listing.id],
                trigger="manual",
                product_id=listing.product_id,
                listing_id=listing.id,
            )

    def enqueue_product(self, product_id: int) -> ExecutionRun:
        with self._session_factory() as session:
            product = session.get(Product, product_id)
            if product is None:
                raise NoEligibleListingsError("No existe el producto.")
            if not product.is_active:
                raise NoEligibleListingsError("El producto está desactivado.")
            listing_ids = list(
                session.scalars(
                    select(StoreListing.id)
                    .where(
                        StoreListing.product_id == product_id,
                        StoreListing.is_enabled.is_(True),
                    )
                    .order_by(StoreListing.id)
                )
            )
            if not listing_ids:
                raise NoEligibleListingsError(
                    "El producto no tiene publicaciones habilitadas."
                )
            return self._enqueue(
                session,
                listing_ids,
                trigger="manual",
                product_id=product_id,
                listing_id=None,
            )

    def enqueue_scheduled(self) -> ExecutionRun | None:
        with self._session_factory() as session:
            listing_ids = list(
                session.scalars(
                    select(StoreListing.id)
                    .join(StoreListing.store)
                    .join(StoreListing.product)
                    .where(
                        StoreListing.is_enabled.is_(True),
                        Product.is_active.is_(True),
                        Store.is_enabled.is_(True),
                        Store.integration_status == "active",
                        Store.base_domain.in_(self.service.adapter_domains),
                    )
                    .order_by(StoreListing.id)
                )
            )
            if not listing_ids:
                return None
            return self._enqueue(
                session,
                listing_ids,
                trigger="scheduled",
                product_id=None,
                listing_id=None,
            )

    def _enqueue(
        self,
        session: Session,
        listing_ids: list[int],
        *,
        trigger: str,
        product_id: int | None,
        listing_id: int | None,
    ) -> ExecutionRun:
        selected = set(listing_ids)
        with self._lock:
            if self._closed:
                raise UpdateCoordinatorError("El coordinador está detenido.")
            duplicates = selected.intersection(self._active_listing_ids)
            if duplicates:
                raise DuplicateUpdateError(
                    "Ya hay una actualización activa para una o más publicaciones."
                )
            self._active_listing_ids.update(selected)
            run = ExecutionRun(
                trigger=trigger,
                status="running",
                product_id=product_id,
                listing_id=listing_id,
                started_at=utc_now(),
                listings_checked=0,
                listings_succeeded=0,
                listings_failed=0,
            )
            session.add(run)
            try:
                session.commit()
            except Exception:
                session.rollback()
                self._active_listing_ids.difference_update(selected)
                raise
            session.refresh(run)
            run_id = run.id
            future = self._executor.submit(self._execute_reserved, run_id, listing_ids)
            self._futures[run_id] = future
            if len(self._futures) > 256:
                for saved_id, saved_future in tuple(self._futures.items()):
                    if len(self._futures) <= 256:
                        break
                    if saved_future.done():
                        del self._futures[saved_id]
            return run

    def _execute_reserved(self, run_id: int, listing_ids: Sequence[int]) -> None:
        try:
            self.service.execute(run_id, listing_ids)
        finally:
            with self._lock:
                self._active_listing_ids.difference_update(listing_ids)

    def wait_for_run(self, run_id: int, timeout: float | None = None) -> None:
        with self._lock:
            future = self._futures.get(run_id)
        if future is None:
            raise UpdateCoordinatorError("No existe una tarea en memoria para esa ejecución.")
        future.result(timeout=timeout)


class PeriodicScheduler:
    def __init__(self, interval_seconds: int, callback: Callable[[], object]) -> None:
        if interval_seconds < 3_600:
            raise ValueError("El intervalo automático mínimo es de una hora.")
        self.interval_seconds = interval_seconds
        self.callback = callback
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="pricewatch-periodic-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            try:
                self.callback()
            except Exception:
                logger.exception("Falló el ciclo del planificador de PriceWatch.")
                continue
