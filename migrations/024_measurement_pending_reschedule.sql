ALTER TABLE measurements
    ADD COLUMN IF NOT EXISTS pending_reschedule_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS pending_reschedule_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_measurements_pending_reschedule
    ON measurements (pending_reschedule_at)
    WHERE pending_reschedule_at IS NOT NULL;
