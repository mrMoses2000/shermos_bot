-- One active draft per client while the bot collects render parameters.
-- Final orders are created only after the draft has all required fields and
-- the renderer succeeds.

CREATE TABLE IF NOT EXISTS order_drafts (
    request_id TEXT PRIMARY KEY,
    chat_id BIGINT NOT NULL REFERENCES clients(chat_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'collecting',
    collected_params JSONB NOT NULL DEFAULT '{}'::jsonb,
    rendered_order_id TEXT REFERENCES orders(request_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_order_drafts_status
        CHECK (status IN ('collecting', 'confirming', 'rendering', 'rendered', 'abandoned')),
    CONSTRAINT chk_order_drafts_collected_params_object
        CHECK (jsonb_typeof(collected_params) = 'object')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_order_drafts_one_active_per_chat
    ON order_drafts(chat_id)
    WHERE status IN ('collecting', 'confirming', 'rendering');

CREATE INDEX IF NOT EXISTS idx_order_drafts_chat_updated
    ON order_drafts(chat_id, updated_at DESC);
