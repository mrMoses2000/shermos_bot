ALTER TABLE measurements
    ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_measurements_reminder_due
    ON measurements (scheduled_time)
    WHERE reminder_sent_at IS NULL AND status = 'confirmed';
