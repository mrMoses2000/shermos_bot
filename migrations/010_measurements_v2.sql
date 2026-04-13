-- Measurement scheduling v2: conflict detection, full status lifecycle, manager assignment
-- Statuses: scheduled → confirmed → completed
--                     → rejected
--                     → cancelled (by client)
--                     → rescheduled (creates new measurement)

-- Add manager_chat_id (who is assigned / confirmed)
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS manager_chat_id BIGINT;

-- Add rejection/cancellation reason
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS reason TEXT NOT NULL DEFAULT '';

-- Add duration in minutes (default 60)
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS duration_minutes INT NOT NULL DEFAULT 60;

-- Add client phone + name denormalized for quick access
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS client_name TEXT NOT NULL DEFAULT '';
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS client_phone TEXT NOT NULL DEFAULT '';

-- Prevent overlapping measurements:
-- Two active measurements cannot overlap in time.
-- "Active" = status IN ('scheduled', 'confirmed').
-- We use an exclusion constraint with tsrange.
-- First, ensure btree_gist extension (needed for exclusion with =).
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Create a function that returns the time range for a measurement
-- We'll use a partial unique index approach instead (simpler, no extension dependency fallback)
-- Exclusion constraint: no two active measurements can have overlapping time ranges
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'no_overlapping_measurements'
    ) THEN
        ALTER TABLE measurements
        ADD CONSTRAINT no_overlapping_measurements
        EXCLUDE USING gist (
            tstzrange(scheduled_time, scheduled_time + (duration_minutes || ' minutes')::interval) WITH &&
        )
        WHERE (status IN ('scheduled', 'confirmed'));
    END IF;
EXCEPTION
    WHEN others THEN
        -- If btree_gist not available, fall back to application-level check
        RAISE NOTICE 'Could not create exclusion constraint, will use app-level conflict check';
END
$$;

-- Index for fast slot availability queries
CREATE INDEX IF NOT EXISTS idx_measurements_active_time
    ON measurements(scheduled_time, duration_minutes)
    WHERE status IN ('scheduled', 'confirmed');

-- Index for manager lookups
CREATE INDEX IF NOT EXISTS idx_measurements_manager
    ON measurements(manager_chat_id)
    WHERE manager_chat_id IS NOT NULL;
