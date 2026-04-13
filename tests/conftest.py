import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "client-token")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "client-secret")
os.environ.setdefault("MANAGER_BOT_TOKEN", "manager-token")
os.environ.setdefault("MANAGER_WEBHOOK_SECRET", "manager-secret")
os.environ.setdefault("POSTGRES_PASSWORD", "change_me")
os.environ.setdefault("LOG_FORMAT", "text")
