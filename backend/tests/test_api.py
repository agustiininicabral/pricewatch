from collections.abc import Iterator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import Base
from app.database.session import make_engine
from app.main import create_app
from app.database.session import get_session
from app.scheduler.service import UpdateCoordinator, UpdateSettings


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    engine = make_engine(f"sqlite:///{tmp_path / 'api-test.db'}")
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    coordinator = UpdateCoordinator(
        test_session,
        adapters={},
        settings=UpdateSettings(
            interval_seconds=86_400,
            minimum_request_interval_seconds=10,
        ),
    )
    application = create_app(update_coordinator=coordinator)

    def override_session() -> Iterator[Session]:
        with test_session() as session:
            yield session

    application.dependency_overrides[get_session] = override_session
    with TestClient(application) as test_client:
        yield test_client
    engine.dispose()


def create_product(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "Cámara de prueba",
        "canonical_key": "camara-prueba",
        "brand": "Marca",
        "description": "Descripción",
    }
    payload.update(overrides)
    response = client.post("/api/products", json=payload)
    assert response.status_code == 201
    return response.json()


def observation_payload(
    *,
    store_slug: str = "tienda-a",
    store_domain: str = "tienda-a.example.test",
    source_url: str = "https://tienda-a.example.test/camara",
    amount_minor: int = 20_000,
    currency: str = "ARS",
    validation_status: str = "verified",
    **extra,
) -> dict:
    payload = {
        "store_name": "Tienda A",
        "store_slug": store_slug,
        "store_domain": store_domain,
        "source_url": source_url,
        "external_id": "sku-1",
        "title": "Cámara de prueba",
        "amount_minor": amount_minor,
        "currency": currency,
        "availability": "in_stock",
        "observed_at": "2026-10-13T15:00:00-03:00",
        "extraction_method": "manual_test",
        "validation_status": validation_status,
    }
    payload.update(extra)
    return payload


def register_observation(
    client: TestClient, product_id: int, **overrides
) -> dict:
    response = client.post(
        f"/api/products/{product_id}/observations",
        json=observation_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health_endpoint_checks_database(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_frontend_is_served_from_the_local_api(client: TestClient) -> None:
    page = client.get("/")
    script = client.get("/assets/app.js")
    stylesheet = client.get("/assets/styles.css")

    assert page.status_code == script.status_code == stylesheet.status_code == 200
    assert 'lang="es"' in page.text
    assert 'src="/assets/app.js"' in page.text
    assert "function loadDashboard" in script.text
    assert ".summary-grid" in stylesheet.text


def test_product_crud_preserves_product_and_history(client: TestClient) -> None:
    product = create_product(client)
    product_id = product["id"]

    assert client.get("/api/products").json()[0]["id"] == product_id
    assert client.get(f"/api/products/{product_id}").status_code == 200
    updated = client.patch(
        f"/api/products/{product_id}",
        json={"brand": "Otra marca", "is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["brand"] == "Otra marca"
    assert updated.json()["is_active"] is False
    assert client.get("/api/products").json() == []
    assert client.get("/api/products?include_inactive=true").json()[0]["id"] == product_id

    activated = client.patch(f"/api/products/{product_id}", json={"is_active": True})
    assert activated.json()["is_active"] is True
    register_observation(client, product_id)
    deleted = client.delete(f"/api/products/{product_id}")
    assert deleted.status_code == 200
    assert deleted.json()["is_active"] is False
    assert len(client.get(f"/api/products/{product_id}/history").json()) == 1


def test_listing_url_can_be_registered_without_inventing_a_price(
    client: TestClient,
) -> None:
    product = create_product(client)
    response = client.post(
        f"/api/products/{product['id']}/listings",
        json={
            "store_name": "Tienda de prueba",
            "source_url": "https://shop.example.test/item-1",
            "title": "Cámara publicada",
        },
    )

    assert response.status_code == 201, response.text
    listing = response.json()
    assert listing["store_name"] == "Tienda de prueba"
    assert listing["store_domain"] == "shop.example.test"
    assert listing["integration_status"] == "pending"
    assert listing["store_enabled"] is False
    assert listing["validation_status"] == "pending"
    assert listing["last_checked_at"] is None
    assert client.get(f"/api/products/{product['id']}/history").json() == []
    assert client.get(f"/api/products/{product['id']}/comparison").json()["groups"] == []

    listings = client.get(f"/api/products/{product['id']}/listings")
    assert listings.status_code == 200
    assert listings.json() == [listing]


@pytest.mark.parametrize(
    "source_url",
    [
        "file:///local/file.html",
        "http://localhost/product",
        "http://127.0.0.1/product",
        "http://192.168.1.4/product",
        "https://user@shop.example.test/product",
        "https://shop.example.test:444/product",
        "https://bad_host.example/product",
    ],
)
def test_listing_registration_rejects_unsafe_or_invalid_urls(
    client: TestClient, source_url: str
) -> None:
    product = create_product(client)
    response = client.post(
        f"/api/products/{product['id']}/listings",
        json={"store_name": "Tienda", "source_url": source_url},
    )
    assert response.status_code == 422
    assert client.get(f"/api/products/{product['id']}/listings").json() == []


def test_listing_registration_rejects_duplicates_and_unknown_products(
    client: TestClient,
) -> None:
    product = create_product(client)
    payload = {
        "store_name": "Tienda",
        "source_url": "https://shop.example.test/product",
    }
    assert client.post(f"/api/products/{product['id']}/listings", json=payload).status_code == 201
    assert client.post(f"/api/products/{product['id']}/listings", json=payload).status_code == 409
    assert client.post("/api/products/999/listings", json=payload).status_code == 404


def test_listing_registration_rejects_unknown_product_variant(
    client: TestClient,
) -> None:
    product = create_product(client)
    response = client.post(
        f"/api/products/{product['id']}/listings",
        json={
            "store_name": "Tienda",
            "source_url": "https://shop.example.test/product",
            "variant_key": "no-existe",
        },
    )
    assert response.status_code == 422


def test_product_create_validates_input_and_unique_key(client: TestClient) -> None:
    assert client.post("/api/products", json={"name": " ", "canonical_key": " "}).status_code == 422
    create_product(client)
    duplicate = client.post(
        "/api/products",
        json={"name": "Duplicada", "canonical_key": "camara-prueba"},
    )
    assert duplicate.status_code == 409


def test_product_patch_rejects_null_for_non_nullable_fields(
    client: TestClient,
) -> None:
    product = create_product(client)
    for patch in ({"name": None}, {"canonical_key": None}, {"is_active": None}):
        response = client.patch(f"/api/products/{product['id']}", json=patch)
        assert response.status_code == 422


def test_missing_product_returns_clear_404(client: TestClient) -> None:
    assert client.get("/api/products/999").status_code == 404
    assert client.get("/api/products/999/history").status_code == 404
    assert client.get("/api/products/999/comparison").status_code == 404


def test_observation_is_persisted_with_utc_and_validation_state(
    client: TestClient,
) -> None:
    product = create_product(client)
    pending = register_observation(
        client,
        product["id"],
        validation_status="pending_review",
    )
    assert pending["validation_status"] == "pending_review"
    assert pending["observed_at"] == "2026-10-13T18:00:00Z"

    history = client.get(f"/api/products/{product['id']}/history")
    assert history.status_code == 200
    assert history.json()[0]["validation_status"] == "pending_review"
    assert history.json()[0]["amount_minor"] == 20_000
    assert history.json()[0]["currency"] == "ARS"

    verified = register_observation(
        client,
        product["id"],
        amount_minor=18_000,
    )
    assert verified["validation_status"] == "verified"
    assert [
        item["validation_status"]
        for item in client.get(f"/api/products/{product['id']}/history").json()
    ] == ["pending_review", "verified"]


@pytest.mark.parametrize(
    "changes",
    [
        {"amount_minor": 0},
        {"amount_minor": -100},
        {"amount_minor": 1.5},
        {"currency": "ars"},
        {"availability": "unknown-stock"},
        {"observed_at": "2026-10-13T15:00:00"},
        {"source_url": "file:///etc/passwd"},
        {"source_url": "https://other.example/camera"},
        {"store_domain": "localhost", "source_url": "http://localhost/camera"},
        {"source_url": "https://user:password@tienda-a.example.test/camara"},
    ],
)
def test_observation_rejects_invalid_input(
    client: TestClient, changes: dict
) -> None:
    product = create_product(client)
    response = client.post(
        f"/api/products/{product['id']}/observations",
        json=observation_payload(**changes),
    )
    assert response.status_code == 422
    assert client.get(f"/api/products/{product['id']}/history").json() == []


def test_observation_conflict_and_unknown_variant_are_rejected(
    client: TestClient,
) -> None:
    product_a = create_product(client)
    product_b = create_product(
        client,
        name="Otra cámara",
        canonical_key="otra-camara",
    )
    register_observation(client, product_a["id"])

    conflict = client.post(
        f"/api/products/{product_b['id']}/observations",
        json=observation_payload(),
    )
    assert conflict.status_code == 409

    wrong_store_domain = client.post(
        f"/api/products/{product_a['id']}/observations",
        json=observation_payload(
            store_slug="tienda-a",
            store_domain="other.example.test",
            source_url="https://other.example.test/camara",
        ),
    )
    assert wrong_store_domain.status_code == 409

    missing_variant = client.post(
        f"/api/products/{product_a['id']}/observations",
        json=observation_payload(variant_key="no-existe"),
    )
    assert missing_variant.status_code == 422


def test_observation_rejects_url_credentials(client: TestClient) -> None:
    product = create_product(client)
    payload = observation_payload()
    payload["source_url"] = (
        "https://" + "usuario" + "@" + "tienda-a.example.test/camara"
    )

    response = client.post(
        f"/api/products/{product['id']}/observations",
        json=payload,
    )
    assert response.status_code == 422


def test_pending_observation_never_enters_comparison_as_verified(
    client: TestClient,
) -> None:
    product = create_product(client)
    register_observation(
        client,
        product["id"],
        validation_status="pending_review",
    )

    response = client.get(f"/api/products/{product['id']}/comparison")
    assert response.status_code == 200
    result = response.json()
    assert result["groups"] == []
    assert len(result["excluded"]) == 1
    assert "revisión" in result["excluded"][0]["reason"]


def test_comparison_uses_existing_engine_and_known_shipping(
    client: TestClient,
) -> None:
    product = create_product(client)
    first = register_observation(client, product["id"])
    second = register_observation(
        client,
        product["id"],
        store_slug="tienda-b",
        store_domain="tienda-b.example.test",
        source_url="https://tienda-b.example.test/camara",
        amount_minor=19_000,
    )

    blocked = client.get(f"/api/products/{product['id']}/comparison").json()
    assert blocked["groups"][0]["cheapest_offer"] is None
    assert len(blocked["groups"][0]["blocking_reasons"]) == 2

    quote_a = client.post(
        f"/api/listings/{first['listing_id']}/shipping",
        json={
            "status": "known",
            "amount_minor": 0,
            "currency": "ARS",
            "source": "confirmado por el usuario",
        },
    )
    quote_b = client.post(
        f"/api/listings/{second['listing_id']}/shipping",
        json={
            "status": "known",
            "amount_minor": 500,
            "currency": "ARS",
            "source": "confirmado por el usuario",
        },
    )
    assert quote_a.status_code == quote_b.status_code == 201

    response = client.get(f"/api/products/{product['id']}/comparison")
    assert response.status_code == 200
    group = response.json()["groups"][0]
    assert [offer["total_minor"] for offer in group["offers"]] == [19_500, 20_000]
    assert group["cheapest_offer"]["source_url"] == second["source_url"]
    assert group["offers"][1]["difference_from_cheapest_minor"] == 500


def test_shipping_validation_requires_explicit_cost_and_currency(
    client: TestClient,
) -> None:
    product = create_product(client)
    observation = register_observation(client, product["id"])

    unknown_with_amount = client.post(
        f"/api/listings/{observation['listing_id']}/shipping",
        json={
            "status": "unknown",
            "amount_minor": 0,
            "source": "manual",
        },
    )
    assert unknown_with_amount.status_code == 422

    known_without_cost = client.post(
        f"/api/listings/{observation['listing_id']}/shipping",
        json={"status": "known", "source": "manual"},
    )
    assert known_without_cost.status_code == 422

    wrong_currency = client.post(
        f"/api/listings/{observation['listing_id']}/shipping",
        json={
            "status": "known",
            "amount_minor": 10,
            "currency": "USD",
            "source": "manual",
        },
    )
    assert wrong_currency.status_code == 422


def test_comparison_partitions_currency_and_variant(client: TestClient) -> None:
    product = create_product(client)
    register_observation(client, product["id"])
    register_observation(
        client,
        product["id"],
        store_slug="tienda-b",
        store_domain="tienda-b.example.test",
        source_url="https://tienda-b.example.test/camara",
        currency="USD",
    )
    response = client.get(f"/api/products/{product['id']}/comparison")
    assert {group["currency"] for group in response.json()["groups"]} == {"ARS", "USD"}


def test_history_filters_listing_and_records_absent_costs_as_not_assumed(
    client: TestClient,
) -> None:
    product = create_product(client)
    first = register_observation(client, product["id"])
    register_observation(
        client,
        product["id"],
        store_slug="tienda-b",
        store_domain="tienda-b.example.test",
        source_url="https://tienda-b.example.test/camara",
    )

    response = client.get(
        f"/api/products/{product['id']}/history",
        params={"listing_id": first["listing_id"]},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1
    compare = client.get(f"/api/products/{product['id']}/comparison").json()
    assert all(group["cheapest_offer"] is None for group in compare["groups"])


def test_inactive_product_rejects_new_observations(client: TestClient) -> None:
    product = create_product(client)
    client.delete(f"/api/products/{product['id']}")
    response = client.post(
        f"/api/products/{product['id']}/observations",
        json=observation_payload(),
    )
    assert response.status_code == 409


def test_manual_update_and_execution_status_are_persisted(
    client: TestClient,
) -> None:
    product = create_product(client)
    observation = register_observation(client, product["id"])

    response = client.post(
        f"/api/listings/{observation['listing_id']}/update"
    )
    assert response.status_code == 202
    run_id = response.json()["id"]
    coordinator = client.app.state.update_coordinator
    coordinator.wait_for_run(run_id, timeout=5)

    detail = client.get(f"/api/executions/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "failed"
    assert detail.json()["listings_failed"] == 1
    assert "AdapterNotReadyError" in detail.json()["errors"][0]
    assert client.get(
        f"/api/executions/latest?listing_id={observation['listing_id']}"
    ).json()["id"] == run_id
    history = client.get(f"/api/products/{product['id']}/history").json()
    assert len(history) == 1
    assert history[0]["amount_minor"] == 20_000


def test_manual_product_update_requires_enabled_publication(
    client: TestClient,
) -> None:
    product = create_product(client)
    response = client.post(f"/api/products/{product['id']}/update")
    assert response.status_code == 409


def test_execution_status_returns_404_for_unknown_run(client: TestClient) -> None:
    assert client.get("/api/executions/555").status_code == 404
    assert client.get("/api/executions/latest").status_code == 404
