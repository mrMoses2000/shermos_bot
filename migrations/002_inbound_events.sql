CREATE TABLE IF NOT EXISTS inbound_events (
    id BIGSERIAL PRIMARY KEY,
    telegram_update_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    raw_update JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_inbound_events_chat_created
    ON inbound_events(chat_id, created_at DESC);
