import hashlib
import hmac
import time
from urllib.parse import urlencode

import pytest

from src.api.auth import validate_init_data


def signed_init_data(bot_token: str, payload: dict[str, str]) -> str:
    data_check_string = "\n".join(f"{key}={payload[key]}" for key in sorted(payload))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**payload, "hash": digest})


def test_validate_init_data_success():
    init_data = signed_init_data(
        "manager-token",
        {"auth_date": str(int(time.time())), "query_id": "abc", "user": '{"id":1}'},
    )

    parsed = validate_init_data(init_data, "manager-token")

    assert parsed["query_id"] == "abc"
    assert parsed["user_json"]["id"] == 1


def test_validate_init_data_rejects_bad_hash():
    with pytest.raises(ValueError):
        validate_init_data("auth_date=1&hash=bad", "manager-token")
