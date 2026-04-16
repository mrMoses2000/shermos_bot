-- Repair accidental double-encoded JSONB payloads and enforce core data shape.
-- The double encoding happened when asyncpg JSONB codecs were enabled while
-- application code still passed pre-serialized JSON strings.

CREATE OR REPLACE FUNCTION _shermos_unwrap_jsonb(value JSONB, fallback JSONB)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    decoded JSONB;
BEGIN
    IF value IS NULL THEN
        RETURN fallback;
    END IF;

    IF jsonb_typeof(value) <> 'string' THEN
        RETURN value;
    END IF;

    BEGIN
        decoded := (value #>> '{}')::jsonb;
    EXCEPTION WHEN others THEN
        RETURN fallback;
    END;

    IF decoded IS NULL THEN
        RETURN fallback;
    END IF;

    RETURN decoded;
END
$$;

UPDATE conversation_state
SET collected_params = _shermos_unwrap_jsonb(collected_params, '{}'::jsonb)
WHERE jsonb_typeof(collected_params) = 'string';

UPDATE inbound_events
SET raw_update = _shermos_unwrap_jsonb(raw_update, '{}'::jsonb)
WHERE jsonb_typeof(raw_update) = 'string';

UPDATE outbound_events
SET reply_markup = _shermos_unwrap_jsonb(reply_markup, '{}'::jsonb)
WHERE reply_markup IS NOT NULL AND jsonb_typeof(reply_markup) = 'string';

UPDATE orders
SET details_json = _shermos_unwrap_jsonb(details_json, '{}'::jsonb)
WHERE jsonb_typeof(details_json) = 'string';

UPDATE orders
SET render_paths = _shermos_unwrap_jsonb(render_paths, '{}'::jsonb)
WHERE jsonb_typeof(render_paths) = 'string';

UPDATE orders
SET price = _shermos_unwrap_jsonb(price, '{}'::jsonb)
WHERE jsonb_typeof(price) = 'string';

UPDATE prices
SET metadata = _shermos_unwrap_jsonb(metadata, '{}'::jsonb)
WHERE jsonb_typeof(metadata) = 'string';

UPDATE materials
SET metadata = _shermos_unwrap_jsonb(metadata, '{}'::jsonb)
WHERE jsonb_typeof(metadata) = 'string';

UPDATE materials
SET color = _shermos_unwrap_jsonb(color, '[]'::jsonb)
WHERE color IS NOT NULL AND jsonb_typeof(color) = 'string';

DROP FUNCTION _shermos_unwrap_jsonb(JSONB, JSONB);

-- Backfill clients so FK constraints can be added without breaking old rows.
INSERT INTO clients (chat_id)
SELECT DISTINCT chat_id FROM conversation_state
UNION
SELECT DISTINCT chat_id FROM chat_messages
UNION
SELECT DISTINCT chat_id FROM orders
ON CONFLICT (chat_id) DO NOTHING;

INSERT INTO processed_updates (telegram_update_id, status)
SELECT DISTINCT telegram_update_id, 'received'
FROM inbound_events
ON CONFLICT (telegram_update_id) DO NOTHING;

ALTER TABLE conversation_state DROP CONSTRAINT IF EXISTS chk_conversation_state_collected_params_object;
ALTER TABLE conversation_state
    ADD CONSTRAINT chk_conversation_state_collected_params_object
    CHECK (jsonb_typeof(collected_params) = 'object');

ALTER TABLE inbound_events DROP CONSTRAINT IF EXISTS chk_inbound_events_raw_update_object;
ALTER TABLE inbound_events
    ADD CONSTRAINT chk_inbound_events_raw_update_object
    CHECK (jsonb_typeof(raw_update) = 'object');

ALTER TABLE outbound_events DROP CONSTRAINT IF EXISTS chk_outbound_events_reply_markup_object;
ALTER TABLE outbound_events
    ADD CONSTRAINT chk_outbound_events_reply_markup_object
    CHECK (reply_markup IS NULL OR jsonb_typeof(reply_markup) = 'object');

ALTER TABLE orders DROP CONSTRAINT IF EXISTS chk_orders_json_objects;
ALTER TABLE orders
    ADD CONSTRAINT chk_orders_json_objects
    CHECK (
        jsonb_typeof(details_json) = 'object'
        AND jsonb_typeof(render_paths) = 'object'
        AND jsonb_typeof(price) = 'object'
    );

ALTER TABLE prices DROP CONSTRAINT IF EXISTS chk_prices_metadata_object;
ALTER TABLE prices
    ADD CONSTRAINT chk_prices_metadata_object
    CHECK (jsonb_typeof(metadata) = 'object');

ALTER TABLE prices DROP CONSTRAINT IF EXISTS chk_prices_amount_nonnegative;
ALTER TABLE prices
    ADD CONSTRAINT chk_prices_amount_nonnegative
    CHECK (amount >= 0);

ALTER TABLE materials DROP CONSTRAINT IF EXISTS chk_materials_json_shapes;
ALTER TABLE materials
    ADD CONSTRAINT chk_materials_json_shapes
    CHECK (
        jsonb_typeof(metadata) = 'object'
        AND (color IS NULL OR jsonb_typeof(color) = 'array')
    );

ALTER TABLE materials DROP CONSTRAINT IF EXISTS chk_materials_price_modifier_positive;
ALTER TABLE materials
    ADD CONSTRAINT chk_materials_price_modifier_positive
    CHECK (price_modifier > 0);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'inbound_events_telegram_update_id_fkey') THEN
        ALTER TABLE inbound_events
            ADD CONSTRAINT inbound_events_telegram_update_id_fkey
            FOREIGN KEY (telegram_update_id)
            REFERENCES processed_updates(telegram_update_id)
            ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'conversation_state_chat_id_fkey') THEN
        ALTER TABLE conversation_state
            ADD CONSTRAINT conversation_state_chat_id_fkey
            FOREIGN KEY (chat_id)
            REFERENCES clients(chat_id)
            ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chat_messages_chat_id_fkey') THEN
        ALTER TABLE chat_messages
            ADD CONSTRAINT chat_messages_chat_id_fkey
            FOREIGN KEY (chat_id)
            REFERENCES clients(chat_id)
            ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'orders_chat_id_fkey') THEN
        ALTER TABLE orders
            ADD CONSTRAINT orders_chat_id_fkey
            FOREIGN KEY (chat_id)
            REFERENCES clients(chat_id)
            ON DELETE CASCADE;
    END IF;
END
$$;
