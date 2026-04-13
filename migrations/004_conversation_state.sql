CREATE TABLE IF NOT EXISTS conversation_state (
    chat_id BIGINT PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'idle',
    step TEXT,
    collected_params JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
