import hashlib
import hmac
import time
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.deps import get_pool
from src.api import routes_orders


def signed_init_data() -> str:
    payload = {"auth_date": str(int(time.time())), "query_id": "orders-test"}
    data_check_string = "\n".join(f"{key}={payload[key]}" for key in sorted(payload))
    secret_key = hmac.new(b"WebAppData", b"manager-token", hashlib.sha256).digest()
    digest = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**payload, "hash": digest})


def test_orders_route_lists_orders(monkeypatch):
    async def fake_list_orders(_pool, status=None, search=None, limit=50, offset=0):
        assert limit == 50
        return [{"request_id": "abc", "chat_id": 1, "status": status or "new"}]

    monkeypatch.setattr(routes_orders.postgres, "list_orders", fake_list_orders)
    app = create_app()
    app.state.pg_pool = object()
    app.dependency_overrides[get_pool] = lambda: object()
    client = TestClient(app)

    response = client.get("/api/orders", headers={"X-Telegram-Init-Data": signed_init_data()})

    assert response.status_code == 200
    assert response.json()["items"][0]["request_id"] == "abc"
