CREATE TABLE IF NOT EXISTS outbound_events (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    bot_type TEXT NOT NULL DEFAULT 'client',
    reply_text TEXT NOT NULL DEFAULT '',
    reply_markup JSONB,
    inbound_event_id BIGINT REFERENCES inbound_events(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_outbound_events_pending
    ON outbound_events(status, attempts, created_at);
