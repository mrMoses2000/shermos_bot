-- NOTE: This migration fixes pricing to match the real price list from Shermos.

-- Add price_modifier to materials (for frame non-black +4%)
ALTER TABLE materials ADD COLUMN IF NOT EXISTS price_modifier NUMERIC(6, 3) NOT NULL DEFAULT 1.0;

-- Set correct material modifiers
-- Glass: NO price modifier (price difference is in base rate matrix, not modifier)
UPDATE materials SET price_modifier = 1.0 WHERE kind = 'glass';
-- Frame: black(1) and aluminum(3) = 1.0, others = 1.04
UPDATE materials SET price_modifier = 1.0 WHERE id IN ('frame_1', 'frame_3');
UPDATE materials SET price_modifier = 1.04 WHERE id IN ('frame_2', 'frame_4', 'frame_5');

-- Delete old incorrect price rows
DELETE FROM prices WHERE id IN ('base_sqm', 'handle', 'section_step', 'volume_discount_rate');

-- Insert correct price matrix: base rates by (partition_type, glass_category)
-- glass_category: "standard" = transparent/gray/bronze, "textured" = ribbed
INSERT INTO prices (id, name, category, amount, currency, metadata) VALUES
    -- Fixed partition
    ('base_fixed_standard',    'Стационарная — стандартное стекло', 'base', 130, 'USD', '{"partition_type":"fixed","glass_category":"standard","unit":"sqm"}'::jsonb),
    ('base_fixed_textured',    'Стационарная — рифлёное стекло',   'base', 150, 'USD', '{"partition_type":"fixed","glass_category":"textured","unit":"sqm"}'::jsonb),
    -- Sliding 2 panels
    ('base_sliding2_standard', 'Раздвижная 2 ств. — стандартное',  'base', 150, 'USD', '{"partition_type":"sliding_2","glass_category":"standard","unit":"sqm"}'::jsonb),
    ('base_sliding2_textured', 'Раздвижная 2 ств. — рифлёное',     'base', 170, 'USD', '{"partition_type":"sliding_2","glass_category":"textured","unit":"sqm"}'::jsonb),
    -- Sliding 3 panels
    ('base_sliding3_standard', 'Раздвижная 3 ств. — стандартное',  'base', 160, 'USD', '{"partition_type":"sliding_3","glass_category":"standard","unit":"sqm"}'::jsonb),
    ('base_sliding3_textured', 'Раздвижная 3 ств. — рифлёное',     'base', 180, 'USD', '{"partition_type":"sliding_3","glass_category":"textured","unit":"sqm"}'::jsonb),
    -- Sliding 4 panels
    ('base_sliding4_standard', 'Раздвижная 4 ств. — стандартное',  'base', 160, 'USD', '{"partition_type":"sliding_4","glass_category":"standard","unit":"sqm"}'::jsonb),
    ('base_sliding4_textured', 'Раздвижная 4 ств. — рифлёное',     'base', 180, 'USD', '{"partition_type":"sliding_4","glass_category":"textured","unit":"sqm"}'::jsonb),
    -- Addons (per sqm, additive)
    ('addon_matting_solid',    'Сплошная матировка',   'addon', 7,  'USD', '{"unit":"sqm","addon_type":"matting_solid"}'::jsonb),
    ('addon_matting_stripes',  'Матовые полосы',       'addon', 12, 'USD', '{"unit":"sqm","addon_type":"matting_stripes"}'::jsonb),
    ('addon_matting_logo',     'Матовый рисунок',      'addon', 19, 'USD', '{"unit":"sqm","addon_type":"matting_logo"}'::jsonb),
    ('addon_complex_pattern',  'Сложный рисунок вставок', 'addon', 3, 'USD', '{"unit":"sqm","addon_type":"complex_pattern"}'::jsonb),
    ('addon_handle',           'Дверная ручка',        'addon', 80, 'USD', '{"unit":"piece","addon_type":"handle"}'::jsonb),
    -- Modifiers
    ('mod_frame_nonblack',     'Наценка за цвет рамки', 'modifier', 4, '%', '{"description":"% к итогу за рамку не чёрного цвета"}'::jsonb),
    ('mod_volume_discount',    'Скидка за объём',        'discount', 6, '%', '{"threshold_sqm":8,"description":"% скидка при площади > 8 м²"}'::jsonb)
ON CONFLICT (id) DO UPDATE
SET amount = EXCLUDED.amount,
    name = EXCLUDED.name,
    category = EXCLUDED.category,
    currency = EXCLUDED.currency,
    metadata = EXCLUDED.metadata,
    updated_at = now();

-- Update existing material names to Russian
UPDATE materials SET name = 'Прозрачное' WHERE id = 'glass_1';
UPDATE materials SET name = 'Серое' WHERE id = 'glass_2';
UPDATE materials SET name = 'Бронза' WHERE id = 'glass_3';
UPDATE materials SET name = 'Рифлёное' WHERE id = 'glass_4';
UPDATE materials SET name = 'Чёрный матовый' WHERE id = 'frame_1';
UPDATE materials SET name = 'Белый глянцевый' WHERE id = 'frame_2';
UPDATE materials SET name = 'Алюминий' WHERE id = 'frame_3';
UPDATE materials SET name = 'Бронза' WHERE id = 'frame_4';
UPDATE materials SET name = 'Золото' WHERE id = 'frame_5';
