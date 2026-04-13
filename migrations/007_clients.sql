CREATE TABLE IF NOT EXISTS clients (
    chat_id BIGINT PRIMARY KEY,
    first_name TEXT NOT NULL DEFAULT '',
    username TEXT NOT NULL DEFAULT '',
    name TEXT,
    phone TEXT,
    address TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_clients_name
    ON clients(name);
