CREATE TABLE IF NOT EXISTS conversation_memory (
    chat_id BIGINT PRIMARY KEY,
    summary_text TEXT NOT NULL DEFAULT '',
    facts_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    summarized_until_message_id BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversation_memory_updated
    ON conversation_memory(updated_at DESC);
