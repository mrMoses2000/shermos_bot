from fastapi.testclient import TestClient

from src.api import (
    routes_analytics,
    routes_clients,
    routes_measurements,
    routes_pricing,
)
from src.api.app import create_app
from src.api.deps import get_pool
from tests.helpers import signed_init_data


def _client():
    app = create_app()
    app.state.pg_pool = object()
    app.dependency_overrides[get_pool] = lambda: object()
    return TestClient(app)


def _headers():
    return {"X-Telegram-Init-Data": signed_init_data()}


def test_clients_routes(monkeypatch):
    async def fake_list_clients(_pool, search=None, limit=50, offset=0):
        return [{"chat_id": 1, "name": search or "Ann"}]

    async def fake_get_client(_pool, chat_id):
        return {"chat_id": chat_id, "orders": []}

    async def fake_update_client(_pool, chat_id, **fields):
        return {"chat_id": chat_id, **fields}

    monkeypatch.setattr(routes_clients.postgres, "list_clients", fake_list_clients)
    monkeypatch.setattr(routes_clients.postgres, "get_client_with_orders", fake_get_client)
    monkeypatch.setattr(routes_clients.postgres, "update_client", fake_update_client)
    client = _client()

    assert client.get("/api/clients?search=Ann", headers=_headers()).json()["items"][0]["name"] == "Ann"
    assert client.get("/api/clients/2", headers=_headers()).json()["chat_id"] == 2
    assert client.patch("/api/clients/2", headers=_headers(), json={"phone": "+1"}).json()["phone"] == "+1"


def test_client_not_found(monkeypatch):
    async def fake_get_client(_pool, chat_id):
        return None

    monkeypatch.setattr(routes_clients.postgres, "get_client_with_orders", fake_get_client)

    assert _client().get("/api/clients/404", headers=_headers()).status_code == 404


def test_measurement_routes(monkeypatch):
    async def fake_list_measurements(_pool, upcoming_only=True, limit=50):
        return [{"id": 1, "status": "scheduled"}]

    async def fake_confirm(_pool, measurement_id):
        return {"id": measurement_id, "status": "confirmed"}

    async def fake_for_client(_pool, chat_id):
        return [{"client_chat_id": chat_id}]

    async def fake_update_status(_pool, mid, status, **kwargs):
        return {"id": mid, "status": status}

    monkeypatch.setattr(routes_measurements.postgres, "list_measurements", fake_list_measurements)
    monkeypatch.setattr(routes_measurements, "update_measurement_status", fake_update_status)
    monkeypatch.setattr(routes_measurements.postgres, "get_measurements_for_client", fake_for_client)
    client = _client()

    assert client.get("/api/measurements", headers=_headers()).json()["items"][0]["id"] == 1
    assert client.post("/api/measurements/3/confirm", headers=_headers()).json()["status"] == "confirmed"
    assert client.get("/api/measurements/client/9", headers=_headers()).json()["items"][0]["client_chat_id"] == 9


def test_pricing_routes(monkeypatch):
    async def fake_get_prices(_pool):
        return [{"id": "base"}]

    async def fake_update_price(_pool, price_id, **fields):
        return {"id": price_id, **fields}

    async def fake_get_materials(_pool):
        return [{"id": "glass_1"}]

    async def fake_update_material(_pool, material_id, **fields):
        return {"id": material_id, **fields}

    monkeypatch.setattr(routes_pricing.postgres, "get_prices", fake_get_prices)
    monkeypatch.setattr(routes_pricing.postgres, "update_price", fake_update_price)
    monkeypatch.setattr(routes_pricing.postgres, "get_materials", fake_get_materials)
    monkeypatch.setattr(routes_pricing.postgres, "update_material", fake_update_material)
    client = _client()

    assert client.get("/api/pricing/prices", headers=_headers()).json()["items"][0]["id"] == "base"
    assert client.patch("/api/pricing/prices/base", headers=_headers(), json={"amount": 200}).json()["amount"] == 200
    assert client.get("/api/pricing/materials", headers=_headers()).json()["items"][0]["id"] == "glass_1"
    assert (
        client.patch("/api/pricing/materials/glass_1", headers=_headers(), json={"name": "Glass"}).json()["name"]
        == "Glass"
    )


def test_analytics_and_settings_routes(monkeypatch):
    async def fake_stats(_pool, days=30):
        return {"total_orders": 1, "total_revenue": 2, "orders_today": 1, "pending_measurements": 0}

    monkeypatch.setattr(routes_analytics.postgres, "get_dashboard_stats", fake_stats)
    client = _client()

    assert client.get("/api/analytics/dashboard?days=7", headers=_headers()).json()["total_orders"] == 1
    settings = client.get("/api/settings", headers=_headers()).json()
    assert "webhook_url_client" in settings


def test_api_requires_auth_header():
    assert _client().get("/api/orders").status_code == 401
