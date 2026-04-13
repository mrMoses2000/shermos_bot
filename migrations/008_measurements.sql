CREATE TABLE IF NOT EXISTS measurements (
    id BIGSERIAL PRIMARY KEY,
    client_chat_id BIGINT NOT NULL REFERENCES clients(chat_id) ON DELETE CASCADE,
    scheduled_time TIMESTAMPTZ NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    calendar_event_id TEXT,
    status TEXT NOT NULL DEFAULT 'scheduled',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_measurements_scheduled
    ON measurements(scheduled_time);
