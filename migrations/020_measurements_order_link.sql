-- Link a scheduled measurement to the rendered order that produced it.
-- This lets the dialogue keep one current 3D order through scheduling and
-- lets order status move only after the measurement record is complete.

ALTER TABLE measurements
    ADD COLUMN IF NOT EXISTS order_request_id TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_measurements_order_request'
    ) THEN
        ALTER TABLE measurements
            ADD CONSTRAINT fk_measurements_order_request
            FOREIGN KEY (order_request_id)
            REFERENCES orders(request_id)
            ON DELETE SET NULL;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_measurements_order_request
    ON measurements(order_request_id)
    WHERE order_request_id IS NOT NULL;
