ALTER TABLE processed_updates
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'telegram';

ALTER TABLE processed_updates
    ADD COLUMN IF NOT EXISTS external_update_id TEXT;

UPDATE processed_updates
SET external_update_id = telegram_update_id::text
WHERE external_update_id IS NULL
  AND channel = 'telegram';

CREATE UNIQUE INDEX IF NOT EXISTS idx_processed_updates_channel_external
    ON processed_updates (channel, external_update_id)
    WHERE external_update_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_processed_updates_channel_status
    ON processed_updates (channel, status);

ALTER TABLE inbound_events
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'telegram';

ALTER TABLE inbound_events
    ADD COLUMN IF NOT EXISTS external_message_id TEXT;

ALTER TABLE inbound_events
    ADD COLUMN IF NOT EXISTS external_chat_id TEXT;

ALTER TABLE inbound_events
    ADD COLUMN IF NOT EXISTS phone_e164 TEXT;

ALTER TABLE inbound_events
    ADD COLUMN IF NOT EXISTS media_path TEXT;

ALTER TABLE inbound_events
    ADD COLUMN IF NOT EXISTS media_mime TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_inbound_events_channel_external
    ON inbound_events (channel, external_message_id)
    WHERE external_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_inbound_events_channel_chat_created
    ON inbound_events (channel, chat_id, created_at DESC);

ALTER TABLE outbound_events
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'telegram';

ALTER TABLE outbound_events
    ADD COLUMN IF NOT EXISTS external_chat_id TEXT;

ALTER TABLE outbound_events
    ADD COLUMN IF NOT EXISTS external_message_id TEXT;

CREATE INDEX IF NOT EXISTS idx_outbound_events_channel_pending
    ON outbound_events (channel, status, attempts, created_at);
