from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.auth import create_access_token
from src.api.deps import get_pool
from src.api import routes_orders


def _auth_headers() -> dict:
    token = create_access_token({"sub": "test-manager", "type": "access"})
    return {"Authorization": f"Bearer {token}"}


def test_orders_route_lists_orders(monkeypatch):
    async def fake_list_orders(_pool, status=None, search=None, limit=50, offset=0):
        assert limit == 50
        return [{"request_id": "abc", "chat_id": 1, "status": status or "new"}]

    monkeypatch.setattr(routes_orders.postgres, "list_orders", fake_list_orders)
    app = create_app()
    app.state.pg_pool = object()
    app.dependency_overrides[get_pool] = lambda: object()
    client = TestClient(app)

    response = client.get("/api/orders", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["items"][0]["request_id"] == "abc"
