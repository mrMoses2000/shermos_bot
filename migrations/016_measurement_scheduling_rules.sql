-- Measurement scheduling v3:
-- - default planning gap is 45 minutes between measurement starts
-- - manager has 15 minutes to confirm before automatic confirmation
-- - manager-proposed open slots are stored for calendar/audit visibility

ALTER TABLE measurements
    ALTER COLUMN duration_minutes SET DEFAULT 45;

ALTER TABLE measurements
    ADD COLUMN IF NOT EXISTS auto_confirm_at TIMESTAMPTZ;

UPDATE measurements
SET duration_minutes = 45
WHERE status IN ('scheduled', 'confirmed')
  AND duration_minutes = 60;

UPDATE measurements
SET auto_confirm_at = created_at + interval '15 minutes'
WHERE auto_confirm_at IS NULL
  AND status = 'scheduled';

CREATE TABLE IF NOT EXISTS measurement_slots (
    id BIGSERIAL PRIMARY KEY,
    slot_start TIMESTAMPTZ NOT NULL UNIQUE,
    duration_minutes INT NOT NULL DEFAULT 45,
    source TEXT NOT NULL DEFAULT 'manager',
    manager_chat_id BIGINT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (duration_minutes > 0),
    CHECK (status IN ('open', 'booked', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_measurement_slots_open_time
    ON measurement_slots(slot_start)
    WHERE status = 'open';
