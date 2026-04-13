CREATE TABLE IF NOT EXISTS orders (
    request_id TEXT PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    render_paths JSONB NOT NULL DEFAULT '{}'::jsonb,
    price JSONB NOT NULL DEFAULT '{}'::jsonb,
    manager_note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_orders_chat_created
    ON orders(chat_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_orders_status_created
    ON orders(status, created_at DESC);
