-- Master-CMS: materials lifecycle (soft-delete, restore, codegen pipeline)
--
-- Why: master needs to mark a material as out-of-stock without losing
-- order/measurement history. New materials enter with pending_codegen=true
-- so the renderer keeps using a fallback until /codegen_dispatch produces
-- the matching code update.

ALTER TABLE materials
    ADD COLUMN IF NOT EXISTS is_active        BOOLEAN     NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS canonical_key    TEXT,
    ADD COLUMN IF NOT EXISTS pending_codegen  BOOLEAN     NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS created_via      TEXT        NOT NULL DEFAULT 'seed',
    ADD COLUMN IF NOT EXISTS deactivated_at   TIMESTAMPTZ;

-- Backfill canonical_key for existing rows: kind:lower(name) with non-letters → '-'
UPDATE materials
   SET canonical_key = kind || ':' || regexp_replace(lower(name), '[^a-zа-яё0-9]+', '-', 'g')
 WHERE canonical_key IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS materials_canonical_key_uniq
    ON materials (canonical_key);

CREATE INDEX IF NOT EXISTS materials_kind_active_idx
    ON materials (kind, is_active);

-- Audit log: every change to a material's lifecycle
CREATE TABLE IF NOT EXISTS material_history (
    id            BIGSERIAL PRIMARY KEY,
    material_id   TEXT        NOT NULL,
    action        TEXT        NOT NULL,           -- created | restored | deactivated | edited
    actor_phone   TEXT,                            -- manager phone (E.164), nullable for system
    actor_chat_id BIGINT,                          -- bot chat id, nullable
    payload       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS material_history_material_idx
    ON material_history (material_id, created_at DESC);

-- Codegen task queue: master-CMS issues a task each time a new material is
-- added (or removed) so a follow-up dev session updates code/config files.
CREATE TABLE IF NOT EXISTS codegen_tasks (
    id            BIGSERIAL PRIMARY KEY,
    kind          TEXT        NOT NULL,           -- add_material | remove_material | restore_material
    material_id   TEXT,
    spec          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    prompt_text   TEXT,                           -- generated lazily on /codegen_dispatch
    status        TEXT        NOT NULL DEFAULT 'pending',  -- pending | prompt_issued | merged | cancelled
    actor_phone   TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    issued_at     TIMESTAMPTZ,
    resolved_at   TIMESTAMPTZ,
    commit_sha    TEXT
);

CREATE INDEX IF NOT EXISTS codegen_tasks_status_idx
    ON codegen_tasks (status, created_at);
