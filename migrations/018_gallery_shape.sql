ALTER TABLE gallery_works
    ADD COLUMN IF NOT EXISTS shape TEXT
        CHECK (shape IN ('Прямая', 'Г-образная', 'П-образная'));
