from __future__ import annotations

import ipaddress
import hashlib
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from app.collectors.contracts import (
    Availability,
    ProductObservation,
    ValidationStatus,
)
from app.database.models import (
    AlertEvent,
    AlertRule,
    ExecutionRun,
    PriceObservation,
    Product,
    ProductVariant,
    ShippingQuote,
    Store,
    StoreListing,
    utc_now,
)
from app.database.session import get_session
from app.pricing.comparator import (
    OfferCandidate,
    ProductIdentity,
    ShippingCost,
    ShippingStatus,
    compare_offers,
)
from app.scheduler.service import (
    DuplicateUpdateError,
    NoEligibleListingsError,
    UpdateCoordinator,
    UpdateCoordinatorError,
)
from app.api.schemas import (
    AlertEventResponse,
    AlertRuleCreate,
    AlertRuleResponse,
    ComparisonGroupResponse,
    ComparisonResponse,
    DOMAIN_PATTERN,
    ExcludedOfferResponse,
    ExecutionResponse,
    HealthResponse,
    ListingCreate,
    ListingResponse,
    ObservationCreate,
    ObservationResponse,
    OfferResponse,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    ShippingQuoteCreate,
    ShippingQuoteResponse,
)

router = APIRouter(prefix="/api")


def get_update_coordinator(request: Request) -> UpdateCoordinator:
    return request.app.state.update_coordinator


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _not_found_product(product_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No existe el producto {product_id}.")


def _ensure_public_store_domain(domain: str) -> None:
    if domain == "localhost" or domain.endswith(".localhost") or domain.endswith(".local"):
        raise HTTPException(status_code=422, detail="El dominio local no es válido.")
    try:
        address = ipaddress.ip_address(domain)
    except ValueError:
        return
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise HTTPException(status_code=422, detail="No se admiten dominios IP locales o reservados.")


def _response_product(product: Product) -> ProductResponse:
    return ProductResponse(
        id=product.id,
        name=product.name,
        canonical_key=product.canonical_key,
        brand=product.brand,
        description=product.description,
        is_active=product.is_active,
        created_at=_utc(product.created_at),
        updated_at=_utc(product.updated_at),
    )


def _response_observation(
    observation: PriceObservation, listing: StoreListing
) -> ObservationResponse:
    return ObservationResponse(
        id=observation.id,
        listing_id=listing.id,
        store_name=listing.store.name,
        store_domain=listing.store.base_domain,
        source_url=listing.url,
        external_id=listing.external_id,
        title=observation.listing.title or listing.title or "",
        amount_minor=observation.amount_minor,
        currency=observation.currency,
        availability=Availability(observation.availability),
        observed_at=_utc(observation.observed_at),
        extraction_method=observation.extraction_method,
        validation_status=(
            ValidationStatus.VERIFIED
            if observation.is_valid
            else ValidationStatus.PENDING_REVIEW
        ),
    )


def _response_execution(run: ExecutionRun) -> ExecutionResponse:
    return ExecutionResponse(
        id=run.id,
        product_id=run.product_id,
        listing_id=run.listing_id,
        trigger=run.trigger,
        status=run.status,
        started_at=_utc(run.started_at),
        completed_at=_utc(run.completed_at) if run.completed_at else None,
        listings_checked=run.listings_checked,
        listings_succeeded=run.listings_succeeded,
        listings_failed=run.listings_failed,
        errors=run.error_summary.splitlines() if run.error_summary else [],
    )


def _response_listing(listing: StoreListing) -> ListingResponse:
    return ListingResponse(
        id=listing.id,
        product_id=listing.product_id,
        store_name=listing.store.name,
        store_domain=listing.store.base_domain,
        integration_status=listing.store.integration_status,
        store_enabled=listing.store.is_enabled,
        url=listing.url,
        title=listing.title,
        variant_key=listing.variant.variant_key if listing.variant else None,
        is_enabled=listing.is_enabled,
        validation_status=listing.validation_status,
        extraction_method=listing.extraction_method,
        last_checked_at=(
            _utc(listing.last_checked_at) if listing.last_checked_at else None
        ),
        created_at=_utc(listing.created_at),
    )


def _commit_or_conflict(session: Session, conflict_detail: str) -> None:
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=conflict_detail) from error


@router.get("/health", response_model=HealthResponse, tags=["salud"])
def health(session: Session = Depends(get_session)) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503,
            detail="La base de datos no está disponible.",
        ) from error
    return HealthResponse(status="ok", database="ok")


@router.get("/products", response_model=list[ProductResponse], tags=["productos"])
def list_products(
    include_inactive: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> list[ProductResponse]:
    statement = select(Product).order_by(Product.id)
    if not include_inactive:
        statement = statement.where(Product.is_active.is_(True))
    return [_response_product(product) for product in session.scalars(statement)]


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["productos"],
)
def create_product(
    payload: ProductCreate, session: Session = Depends(get_session)
) -> ProductResponse:
    product = Product(**payload.model_dump())
    session.add(product)
    _commit_or_conflict(session, "Ya existe un producto con esa clave canónica.")
    session.refresh(product)
    return _response_product(product)


@router.get("/products/{product_id}", response_model=ProductResponse, tags=["productos"])
def get_product(
    product_id: int, session: Session = Depends(get_session)
) -> ProductResponse:
    product = session.get(Product, product_id)
    if product is None:
        raise _not_found_product(product_id)
    return _response_product(product)


@router.patch(
    "/products/{product_id}", response_model=ProductResponse, tags=["productos"]
)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    session: Session = Depends(get_session),
) -> ProductResponse:
    product = session.get(Product, product_id)
    if product is None:
        raise _not_found_product(product_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    _commit_or_conflict(session, "La clave canónica ya está asignada a otro producto.")
    session.refresh(product)
    return _response_product(product)


@router.delete(
    "/products/{product_id}",
    response_model=ProductResponse,
    tags=["productos"],
    summary="Desactivar producto sin borrar el historial",
)
def deactivate_product(
    product_id: int, session: Session = Depends(get_session)
) -> ProductResponse:
    product = session.get(Product, product_id)
    if product is None:
        raise _not_found_product(product_id)
    product.is_active = False
    session.commit()
    session.refresh(product)
    return _response_product(product)


@router.get(
    "/products/{product_id}/listings",
    response_model=list[ListingResponse],
    tags=["publicaciones"],
)
def get_product_listings(
    product_id: int, session: Session = Depends(get_session)
) -> list[ListingResponse]:
    if session.get(Product, product_id) is None:
        raise _not_found_product(product_id)
    listings = session.scalars(
        select(StoreListing)
        .options(
            joinedload(StoreListing.store),
            joinedload(StoreListing.variant),
        )
        .where(StoreListing.product_id == product_id)
        .order_by(StoreListing.id)
    ).unique().all()
    return [_response_listing(listing) for listing in listings]


@router.post(
    "/products/{product_id}/listings",
    response_model=ListingResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["publicaciones"],
    summary="Registrar una URL sin crear una observación de precio",
)
def create_product_listing(
    product_id: int,
    payload: ListingCreate,
    session: Session = Depends(get_session),
) -> ListingResponse:
    product = session.get(Product, product_id)
    if product is None:
        raise _not_found_product(product_id)
    if not product.is_active:
        raise HTTPException(status_code=409, detail="El producto está desactivado.")

    parsed_url = urlsplit(payload.source_url)
    domain = (parsed_url.hostname or "").rstrip(".").lower()
    _ensure_public_store_domain(domain)
    if not DOMAIN_PATTERN.fullmatch(domain):
        raise HTTPException(
            status_code=422,
            detail="La URL debe usar un dominio público con hostname válido.",
        )

    store = session.scalar(select(Store).where(Store.base_domain == domain))
    if store is None:
        slug = domain.replace(".", "-")
        if len(slug) > 80:
            suffix = hashlib.sha256(domain.encode("ascii")).hexdigest()[:12]
            slug = f"{slug[:67].rstrip('-')}-{suffix}"
        existing_slug = session.scalar(select(Store).where(Store.slug == slug))
        if existing_slug is not None:
            raise HTTPException(
                status_code=409,
                detail="El dominio no puede registrarse porque su identificador ya está en uso.",
            )
        store = Store(
            name=payload.store_name,
            slug=slug,
            base_domain=domain,
            integration_status="pending",
            is_enabled=False,
        )
        session.add(store)
        session.flush()

    variant_id = None
    if payload.variant_key is not None:
        variant = session.scalar(
            select(ProductVariant).where(
                ProductVariant.product_id == product_id,
                ProductVariant.variant_key == payload.variant_key,
            )
        )
        if variant is None:
            raise HTTPException(
                status_code=422,
                detail="variant_key no corresponde a una variante del producto.",
            )
        variant_id = variant.id

    existing_listing = session.scalar(
        select(StoreListing).where(StoreListing.url == payload.source_url)
    )
    if existing_listing is not None:
        raise HTTPException(
            status_code=409,
            detail="La URL ya está registrada como publicación.",
        )

    listing = StoreListing(
        store_id=store.id,
        product_id=product.id,
        variant_id=variant_id,
        url=payload.source_url,
        title=payload.title,
        is_enabled=True,
        validation_status="pending",
    )
    session.add(listing)
    _commit_or_conflict(session, "La publicación o tienda ya está registrada.")
    session.refresh(listing)
    session.refresh(store)
    listing.store = store
    if variant_id is not None:
        listing.variant = session.get(ProductVariant, variant_id)
    return _response_listing(listing)


@router.post(
    "/products/{product_id}/observations",
    response_model=ObservationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["observaciones"],
)
def create_observation(
    product_id: int,
    payload: ObservationCreate,
    session: Session = Depends(get_session),
) -> ObservationResponse:
    product = session.get(Product, product_id)
    if product is None:
        raise _not_found_product(product_id)
    if not product.is_active:
        raise HTTPException(status_code=409, detail="El producto está desactivado.")

    _ensure_public_store_domain(payload.store_domain)
    parsed_url = urlsplit(payload.source_url)
    try:
        host_address = ipaddress.ip_address(parsed_url.hostname or "")
    except ValueError:
        host_address = None
    if host_address is not None and (
        host_address.is_private
        or host_address.is_loopback
        or host_address.is_link_local
        or host_address.is_multicast
        or host_address.is_reserved
        or host_address.is_unspecified
    ):
        raise HTTPException(status_code=422, detail="No se admiten URLs con destino IP local.")

    store = session.scalar(
        select(Store).where(
            (Store.slug == payload.store_slug)
            | (Store.base_domain == payload.store_domain)
        )
    )
    if store is None:
        store = Store(
            name=payload.store_name,
            slug=payload.store_slug,
            base_domain=payload.store_domain,
            integration_status="pending",
            is_enabled=False,
        )
        session.add(store)
        session.flush()
    elif (
        store.slug != payload.store_slug
        or store.base_domain != payload.store_domain
    ):
        raise HTTPException(
            status_code=409,
            detail="El slug o dominio ya está asociado a otra tienda.",
        )

    variant_id = None
    if payload.variant_key is not None:
        variant = session.scalar(
            select(ProductVariant).where(
                ProductVariant.product_id == product_id,
                ProductVariant.variant_key == payload.variant_key,
            )
        )
        if variant is None:
            raise HTTPException(
                status_code=422,
                detail="variant_key no corresponde a una variante del producto.",
            )
        variant_id = variant.id

    listing = session.scalar(
        select(StoreListing)
        .options(joinedload(StoreListing.store))
        .where(StoreListing.url == payload.source_url)
    )
    listing_status = (
        "valid"
        if payload.validation_status is ValidationStatus.VERIFIED
        else "pending"
    )
    if listing is None:
        listing = StoreListing(
            store_id=store.id,
            product_id=product.id,
            variant_id=variant_id,
            external_id=payload.external_id,
            url=payload.source_url,
            title=payload.title,
            is_enabled=True,
            validation_status=listing_status,
            extraction_method=payload.extraction_method,
            last_checked_at=payload.observed_at or utc_now(),
        )
        session.add(listing)
        session.flush()
    elif (
        listing.store_id != store.id
        or listing.product_id != product.id
        or listing.variant_id != variant_id
    ):
        raise HTTPException(
            status_code=409,
            detail="La publicación ya está asociada a otro producto o variante.",
        )
    else:
        listing.title = payload.title
        listing.external_id = payload.external_id
        listing.validation_status = listing_status
        listing.extraction_method = payload.extraction_method
        listing.last_checked_at = payload.observed_at or utc_now()

    observation = PriceObservation(
        listing_id=listing.id,
        amount_minor=payload.amount_minor,
        currency=payload.currency,
        availability=payload.availability.value,
        observed_at=payload.observed_at or utc_now(),
        is_valid=payload.validation_status is ValidationStatus.VERIFIED,
        extraction_method=payload.extraction_method,
        source_reference=payload.source_url,
    )
    session.add(observation)
    _commit_or_conflict(session, "No se pudo registrar la observación por conflicto de datos.")
    session.refresh(observation)
    session.refresh(listing)
    return _response_observation(observation, listing)


@router.get(
    "/products/{product_id}/history",
    response_model=list[ObservationResponse],
    tags=["observaciones"],
)
def get_price_history(
    product_id: int,
    listing_id: int | None = Query(default=None, gt=0),
    session: Session = Depends(get_session),
) -> list[ObservationResponse]:
    if session.get(Product, product_id) is None:
        raise _not_found_product(product_id)
    statement = (
        select(PriceObservation)
        .join(PriceObservation.listing)
        .options(
            joinedload(PriceObservation.listing).joinedload(StoreListing.store)
        )
        .where(StoreListing.product_id == product_id)
        .order_by(PriceObservation.observed_at, PriceObservation.id)
    )
    if listing_id is not None:
        statement = statement.where(StoreListing.id == listing_id)
    observations = session.scalars(statement).unique().all()
    return [
        _response_observation(item, item.listing)
        for item in observations
    ]


@router.post(
    "/listings/{listing_id}/shipping",
    response_model=ShippingQuoteResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["envíos"],
)
def create_shipping_quote(
    listing_id: int,
    payload: ShippingQuoteCreate,
    session: Session = Depends(get_session),
) -> ShippingQuoteResponse:
    listing = session.get(StoreListing, listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="No existe la publicación.")
    if payload.status == "known":
        latest = session.scalar(
            select(PriceObservation)
            .where(PriceObservation.listing_id == listing_id)
            .order_by(PriceObservation.observed_at.desc(), PriceObservation.id.desc())
            .limit(1)
        )
        if latest is None or payload.currency != latest.currency:
            raise HTTPException(
                status_code=422,
                detail="La moneda del envío conocido debe coincidir con el último precio.",
            )
    quote = ShippingQuote(
        listing_id=listing_id,
        status=payload.status,
        amount_minor=payload.amount_minor,
        currency=payload.currency,
        source=payload.source,
        quoted_at=payload.quoted_at or utc_now(),
    )
    session.add(quote)
    session.commit()
    session.refresh(quote)
    return ShippingQuoteResponse(
        id=quote.id,
        listing_id=quote.listing_id,
        status=quote.status,
        amount_minor=quote.amount_minor,
        currency=quote.currency,
        source=quote.source,
        quoted_at=_utc(quote.quoted_at),
    )



def _response_alert_rule(rule: AlertRule) -> AlertRuleResponse:
    return AlertRuleResponse(
        id=rule.id,
        product_id=rule.product_id,
        variant_key=rule.variant.variant_key if rule.variant else None,
        target_amount_minor=rule.target_amount_minor,
        currency=rule.currency,
        minimum_reduction_basis_points=rule.minimum_reduction_basis_points,
        notification_interval_hours=rule.notification_interval_hours,
        is_enabled=rule.is_enabled,
        created_at=_utc(rule.created_at),
        updated_at=_utc(rule.updated_at),
    )


def _response_alert_event(event: AlertEvent) -> AlertEventResponse:
    return AlertEventResponse(
        id=event.id,
        rule_id=event.rule_id,
        event_type=event.event_type,
        state=event.state,
        triggered_at=_utc(event.triggered_at),
        payload=event.payload,
    )


@router.post(
    "/products/{product_id}/alerts",
    response_model=AlertRuleResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["alertas"],
)
def create_alert_rule(
    product_id: int,
    payload: AlertRuleCreate,
    session: Session = Depends(get_session),
) -> AlertRuleResponse:
    if session.get(Product, product_id) is None:
        raise _not_found_product(product_id)
    variant_id: int | None = None
    if payload.variant_key is not None:
        variant = session.scalar(
            select(ProductVariant).where(
                ProductVariant.product_id == product_id,
                ProductVariant.variant_key == payload.variant_key,
            )
        )
        if variant is None:
            raise HTTPException(status_code=404, detail="No existe esa variante del producto.")
        variant_id = variant.id
    rule = AlertRule(
        product_id=product_id,
        variant_id=variant_id,
        target_amount_minor=payload.target_amount_minor,
        currency=payload.currency,
        minimum_reduction_basis_points=payload.minimum_reduction_basis_points,
        notification_interval_hours=24,
        is_enabled=True,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return _response_alert_rule(rule)


@router.get(
    "/products/{product_id}/alerts",
    response_model=list[AlertRuleResponse],
    tags=["alertas"],
)
def list_alert_rules(
    product_id: int,
    session: Session = Depends(get_session),
) -> list[AlertRuleResponse]:
    if session.get(Product, product_id) is None:
        raise _not_found_product(product_id)
    rules = session.scalars(
        select(AlertRule)
        .options(joinedload(AlertRule.variant))
        .where(AlertRule.product_id == product_id)
        .order_by(AlertRule.id)
    ).unique().all()
    return [_response_alert_rule(rule) for rule in rules]


@router.get(
    "/alerts/{rule_id}/events",
    response_model=list[AlertEventResponse],
    tags=["alertas"],
)
def list_alert_events(
    rule_id: int,
    session: Session = Depends(get_session),
) -> list[AlertEventResponse]:
    if session.get(AlertRule, rule_id) is None:
        raise HTTPException(status_code=404, detail="No existe la regla de alerta.")
    events = session.scalars(
        select(AlertEvent)
        .where(AlertEvent.rule_id == rule_id)
        .order_by(AlertEvent.triggered_at.desc(), AlertEvent.id.desc())
    ).all()
    return [_response_alert_event(event) for event in events]


@router.post(
    "/alerts/{rule_id}/evaluate",
    response_model=list[AlertEventResponse],
    tags=["alertas"],
)
def evaluate_alert_rule(
    rule_id: int,
    session: Session = Depends(get_session),
) -> list[AlertEventResponse]:
    from app.alerts.service import evaluate_rule

    rule = session.scalar(
        select(AlertRule)
        .options(joinedload(AlertRule.variant))
        .where(AlertRule.id == rule_id)
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="No existe la regla de alerta.")
    if not rule.is_enabled:
        raise HTTPException(status_code=409, detail="La regla de alerta está deshabilitada.")
    events = evaluate_rule(session, rule)
    session.commit()
    for event in events:
        session.refresh(event)
    return [_response_alert_event(event) for event in events)


@router.get(
    "/products/{product_id}/comparison",
    response_model=ComparisonResponse,
    tags=["comparación"],
)
def compare_product(
    product_id: int,
    variant_key: str | None = Query(default=None, min_length=1, max_length=160),
    session: Session = Depends(get_session),
) -> ComparisonResponse:
    product = session.get(Product, product_id)
    if product is None:
        raise _not_found_product(product_id)
    variant_id: int | None = None
    if variant_key is not None:
        variant = session.scalar(
            select(ProductVariant).where(
                ProductVariant.product_id == product_id,
                ProductVariant.variant_key == variant_key,
            )
        )
        if variant is None:
            raise HTTPException(status_code=404, detail="No existe esa variante del producto.")
        variant_id = variant.id

    listings = session.scalars(
        select(StoreListing)
        .options(joinedload(StoreListing.store), joinedload(StoreListing.variant))
        .where(StoreListing.product_id == product_id)
        .order_by(StoreListing.id)
    ).unique().all()
    if variant_key is not None:
        listings = [listing for listing in listings if listing.variant_id == variant_id]

    candidates: list[OfferCandidate] = []
    for listing in listings:
        observation = session.scalar(
            select(PriceObservation)
            .where(PriceObservation.listing_id == listing.id)
            .order_by(PriceObservation.observed_at.desc(), PriceObservation.id.desc())
            .limit(1)
        )
        if observation is None:
            continue
        shipping_quote = session.scalar(
            select(ShippingQuote)
            .where(ShippingQuote.listing_id == listing.id)
            .order_by(ShippingQuote.quoted_at.desc(), ShippingQuote.id.desc())
            .limit(1)
        )
        validation_status = (
            ValidationStatus.VERIFIED
            if observation.is_valid
            else ValidationStatus.PENDING_REVIEW
        )
        product_observation = ProductObservation(
            domain=listing.store.base_domain,
            source_url=listing.url,
            external_id=listing.external_id,
            title=observation.listing.title or listing.title or "",
            amount_minor=observation.amount_minor,
            currency=observation.currency,
            availability=Availability(observation.availability),
            observed_at=_utc(observation.observed_at),
            extraction_method=observation.extraction_method,
            validation_status=validation_status,
        )
        if shipping_quote is None or shipping_quote.status == "unknown":
            shipping = ShippingCost(ShippingStatus.UNKNOWN)
        elif shipping_quote.amount_minor == 0:
            shipping = ShippingCost(ShippingStatus.FREE, amount_minor=0)
        else:
            shipping = ShippingCost(
                ShippingStatus.PAID,
                amount_minor=shipping_quote.amount_minor,
                currency=shipping_quote.currency,
            )
        identity = ProductIdentity(
            canonical_key=product.canonical_key,
            variant_key=listing.variant.variant_key if listing.variant else None,
            verified=True,
        )
        candidates.append(
            OfferCandidate(identity=identity, observation=product_observation, shipping=shipping)
        )

    result = compare_offers(candidates)
    return ComparisonResponse(
        product_id=product.id,
        groups=[
            ComparisonGroupResponse(
                canonical_key=group.canonical_key,
                variant_key=group.variant_key,
                currency=group.currency,
                offers=[
                    OfferResponse(
                        source_url=offer.source_url,
                        title=offer.title,
                        currency=offer.currency,
                        price_minor=offer.price_minor,
                        shipping_status=offer.shipping_status,
                        shipping_minor=offer.shipping_minor,
                        total_minor=offer.total_minor,
                        difference_from_cheapest_minor=offer.difference_from_cheapest_minor,
                    )
                    for offer in group.offers
                ],
                cheapest_offer=(
                    OfferResponse(
                        source_url=group.cheapest_offer.source_url,
                        title=group.cheapest_offer.title,
                        currency=group.cheapest_offer.currency,
                        price_minor=group.cheapest_offer.price_minor,
                        shipping_status=group.cheapest_offer.shipping_status,
                        shipping_minor=group.cheapest_offer.shipping_minor,
                        total_minor=group.cheapest_offer.total_minor,
                        difference_from_cheapest_minor=group.cheapest_offer.difference_from_cheapest_minor,
                    )
                    if group.cheapest_offer
                    else None
                ),
                winner_reason=group.winner_reason,
                blocking_reasons=list(group.blocking_reasons),
            )
            for group in result.groups
        ],
        excluded=[
            ExcludedOfferResponse(source_url=item.source_url, reason=item.reason)
            for item in result.excluded
        ],
        summary=result.summary,
    )


@router.post(
    "/products/{product_id}/update",
    response_model=ExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["actualizaciones"],
)
def update_product_now(
    product_id: int,
    session: Session = Depends(get_session),
    coordinator: UpdateCoordinator = Depends(get_update_coordinator),
) -> ExecutionResponse:
    if session.get(Product, product_id) is None:
        raise _not_found_product(product_id)
    try:
        run = coordinator.enqueue_product(product_id)
    except NoEligibleListingsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except DuplicateUpdateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except UpdateCoordinatorError as error:
        raise HTTPException(status_code=503, detail="El servicio de actualización no está disponible.") from error
    return _response_execution(run)


@router.post(
    "/listings/{listing_id}/update",
    response_model=ExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["actualizaciones"],
)
def update_listing_now(
    listing_id: int,
    session: Session = Depends(get_session),
    coordinator: UpdateCoordinator = Depends(get_update_coordinator),
) -> ExecutionResponse:
    if session.get(StoreListing, listing_id) is None:
        raise HTTPException(status_code=404, detail="No existe la publicación.")
    try:
        run = coordinator.enqueue_listing(listing_id)
    except NoEligibleListingsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except DuplicateUpdateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except UpdateCoordinatorError as error:
        raise HTTPException(status_code=503, detail="El servicio de actualización no está disponible.") from error
    return _response_execution(run)


@router.get(
    "/executions/latest",
    response_model=ExecutionResponse,
    tags=["actualizaciones"],
)
def latest_execution(
    product_id: int | None = Query(default=None, gt=0),
    listing_id: int | None = Query(default=None, gt=0),
    session: Session = Depends(get_session),
) -> ExecutionResponse:
    if product_id is not None and session.get(Product, product_id) is None:
        raise _not_found_product(product_id)
    if listing_id is not None and session.get(StoreListing, listing_id) is None:
        raise HTTPException(status_code=404, detail="No existe la publicación.")
    statement = select(ExecutionRun)
    if product_id is not None:
        statement = statement.where(ExecutionRun.product_id == product_id)
    if listing_id is not None:
        statement = statement.where(ExecutionRun.listing_id == listing_id)
    run = session.scalar(statement.order_by(ExecutionRun.started_at.desc(), ExecutionRun.id.desc()).limit(1))
    if run is None:
        raise HTTPException(status_code=404, detail="Todavía no hay ejecuciones registradas.")
    return _response_execution(run)


@router.get(
    "/executions/{run_id}",
    response_model=ExecutionResponse,
    tags=["actualizaciones"],
)
def get_execution(
    run_id: int, session: Session = Depends(get_session)
) -> ExecutionResponse:
    run = session.get(ExecutionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No existe la ejecución.")
    return _response_execution(run)
