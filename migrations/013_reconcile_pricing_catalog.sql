-- Reconcile the runtime pricing catalog with the PDF price list and renderer materials.
-- Idempotent: safe on fresh databases and on already deployed databases.

INSERT INTO prices (id, name, category, amount, currency, metadata) VALUES
    ('base_fixed_standard',    'Стационарная — стандартное стекло', 'base', 130, 'USD', '{"partition_type":"fixed","glass_category":"standard","unit":"sqm"}'::jsonb),
    ('base_fixed_textured',    'Стационарная — рифлёное стекло',   'base', 150, 'USD', '{"partition_type":"fixed","glass_category":"textured","unit":"sqm"}'::jsonb),
    ('base_sliding2_standard', 'Раздвижная 2 ств. — стандартное',  'base', 150, 'USD', '{"partition_type":"sliding_2","glass_category":"standard","unit":"sqm"}'::jsonb),
    ('base_sliding2_textured', 'Раздвижная 2 ств. — рифлёное',     'base', 170, 'USD', '{"partition_type":"sliding_2","glass_category":"textured","unit":"sqm"}'::jsonb),
    ('base_sliding3_standard', 'Раздвижная 3 ств. — стандартное',  'base', 160, 'USD', '{"partition_type":"sliding_3","glass_category":"standard","unit":"sqm"}'::jsonb),
    ('base_sliding3_textured', 'Раздвижная 3 ств. — рифлёное',     'base', 180, 'USD', '{"partition_type":"sliding_3","glass_category":"textured","unit":"sqm"}'::jsonb),
    ('base_sliding4_standard', 'Раздвижная 4 ств. — стандартное',  'base', 160, 'USD', '{"partition_type":"sliding_4","glass_category":"standard","unit":"sqm"}'::jsonb),
    ('base_sliding4_textured', 'Раздвижная 4 ств. — рифлёное',     'base', 180, 'USD', '{"partition_type":"sliding_4","glass_category":"textured","unit":"sqm"}'::jsonb),
    ('addon_matting_solid',    'Сплошная матировка',              'addon', 7,   'USD', '{"unit":"sqm","addon_type":"matting_solid"}'::jsonb),
    ('addon_matting_stripes',  'Матовые полосы',                  'addon', 12,  'USD', '{"unit":"sqm","addon_type":"matting_stripes"}'::jsonb),
    ('addon_matting_logo',     'Матовый рисунок',                 'addon', 19,  'USD', '{"unit":"sqm","addon_type":"matting_logo"}'::jsonb),
    ('addon_complex_pattern',  'Сложный рисунок вставок',         'addon', 3,   'USD', '{"unit":"sqm","addon_type":"complex_pattern"}'::jsonb),
    ('addon_handle',           'Дверная ручка',                   'addon', 80,  'USD', '{"unit":"piece","addon_type":"handle"}'::jsonb),
    ('mod_frame_nonblack',     'Наценка за цвет рамки',           'modifier', 4, '%',  '{"description":"% к итогу за рамку не чёрного цвета"}'::jsonb),
    ('mod_volume_discount',    'Скидка за объём',                 'discount', 6, '%',  '{"threshold_sqm":8,"description":"% скидка при площади > 8 м²"}'::jsonb)
ON CONFLICT (id) DO UPDATE
SET amount = EXCLUDED.amount,
    name = EXCLUDED.name,
    category = EXCLUDED.category,
    currency = EXCLUDED.currency,
    metadata = EXCLUDED.metadata,
    updated_at = now();

INSERT INTO materials (id, kind, name, color, roughness, metadata, price_modifier) VALUES
    ('glass_1', 'glass', 'Прозрачное',      '[0.85, 0.95, 1.0, 0.28]'::jsonb, 0.02, '{"source_id":"1"}'::jsonb, 1.0),
    ('glass_2', 'glass', 'Серое',           '[0.45, 0.5, 0.55, 0.35]'::jsonb, 0.04, '{"source_id":"2"}'::jsonb, 1.0),
    ('glass_3', 'glass', 'Бронза',          '[0.65, 0.45, 0.28, 0.35]'::jsonb, 0.04, '{"source_id":"3"}'::jsonb, 1.0),
    ('glass_4', 'glass', 'Рифлёное',        '[0.8, 0.9, 0.95, 0.42]'::jsonb, 0.22, '{"source_id":"4"}'::jsonb, 1.0),
    ('frame_1', 'frame', 'Чёрный матовый',  '[0.05, 0.05, 0.05, 1.0]'::jsonb, NULL, '{"source_id":"1"}'::jsonb, 1.0),
    ('frame_2', 'frame', 'Белый глянцевый', '[0.95, 0.95, 0.92, 1.0]'::jsonb, NULL, '{"source_id":"2"}'::jsonb, 1.04),
    ('frame_3', 'frame', 'Алюминий',        '[0.65, 0.65, 0.62, 1.0]'::jsonb, NULL, '{"source_id":"3"}'::jsonb, 1.0),
    ('frame_4', 'frame', 'Бронза',          '[0.5, 0.32, 0.18, 1.0]'::jsonb, NULL, '{"source_id":"4"}'::jsonb, 1.04),
    ('frame_5', 'frame', 'Золото',          '[0.95, 0.72, 0.25, 1.0]'::jsonb, NULL, '{"source_id":"5"}'::jsonb, 1.04)
ON CONFLICT (id) DO UPDATE
SET kind = EXCLUDED.kind,
    name = EXCLUDED.name,
    color = EXCLUDED.color,
    roughness = EXCLUDED.roughness,
    metadata = EXCLUDED.metadata,
    price_modifier = EXCLUDED.price_modifier,
    updated_at = now();
