ALTER TABLE outbound_events ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT;
ALTER TABLE outbound_events ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_outbound_idempotency
    ON outbound_events (idempotency_key)
    WHERE idempotency_key IS NOT NULL;
