import hashlib
import hmac
import time
from urllib.parse import urlencode


def signed_init_data(bot_token: str = "manager-token", **extra: str) -> str:
    payload = {"auth_date": str(int(time.time())), "query_id": "test-query", **extra}
    data_check_string = "\n".join(f"{key}={payload[key]}" for key in sorted(payload))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**payload, "hash": digest})


class FakeSender:
    def __init__(self):
        self.messages = []
        self.photos = []
        self.media_groups = []
        self.actions = []

    async def send_message(self, token, chat_id, text, parse_mode="HTML", reply_markup=None):
        self.messages.append(
            {
                "token": token,
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            }
        )
        return {"ok": True, "result": {"message_id": len(self.messages)}}

    async def send_photo(self, token, chat_id, photo_path, caption=""):
        self.photos.append((token, chat_id, photo_path, caption))
        return {"ok": True}

    async def send_media_group(self, token, chat_id, photo_paths, caption=""):
        self.media_groups.append((token, chat_id, photo_paths, caption))
        return {"ok": True}

    async def send_chat_action(self, token, chat_id, action="typing"):
        self.actions.append((token, chat_id, action))
        return {"ok": True}


class FakeRedis:
    def __init__(self, locked=False):
        self.jobs = []
        self.locked = locked
        self.released = []

    async def enqueue_job(self, queue_name, job):
        self.jobs.append((queue_name, job))

    async def acquire_user_lock(self, chat_id, ttl=180):
        return not self.locked

    async def release_user_lock(self, chat_id):
        self.released.append(chat_id)
