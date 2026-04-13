CREATE TABLE IF NOT EXISTS processed_updates (
    telegram_update_id BIGINT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'received',
    error_message TEXT,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_processed_updates_status
    ON processed_updates(status);
