CREATE TABLE IF NOT EXISTS gallery_works (
    id TEXT PRIMARY KEY,
    partition_type TEXT NOT NULL
        CHECK (partition_type IN ('fixed', 'sliding_2', 'sliding_3', 'sliding_4')),
    glass_type TEXT,
    matting TEXT,
    title TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_by_chat_id BIGINT,
    is_published BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gallery_works_type_published
    ON gallery_works(partition_type, is_published);

CREATE TABLE IF NOT EXISTS gallery_photos (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES gallery_works(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    width INT,
    height INT,
    size_bytes INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gallery_photos_work
    ON gallery_photos(work_id, sort_order);
