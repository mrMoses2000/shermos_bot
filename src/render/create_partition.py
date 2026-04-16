# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Mission: World-Saving 3D Glass Partition Generator (Version 2.5 - Russian)
# Objective: Generate a high-quality, photorealistic 3D render of a
#            customizable glass partition with multiple shape options and camera angles.
#            Execution must be flawless and robust.
# -----------------------------------------------------------------------------

import os
import sys
import json
import argparse
import datetime
import numpy as np
import re

# --- Платформо-специфичные настройки ---
# Подавляем предупреждение ApplePersistenceIgnoreState на macOS
if sys.platform == 'darwin':  # macOS
    os.environ['PYTHON_DISABLE_STATE_RESTORATION'] = '1'
    # Дополнительно отключаем сохранение состояния для данного процесса
    os.environ['__CF_USER_TEXT_ENCODING'] = f'{os.getuid()}:0:0'

# Импортируем наши модули
from utils.config_manager import config
from utils.logger import setup_logger, log_function_call

# --- 1. Dependency & Setup Check ---
try:
    import trimesh
    import pyrender
    from PIL import Image
except ImportError as e:
    missing_library = e.name
    print(f"[КРИТИЧЕСКАЯ ОШИБКА] Отсутствует необходимая библиотека: '{missing_library}'")
    print("Этот скрипт не может работать без своих зависимостей.")
    print("\nПожалуйста, выполните следующую команду для установки библиотек:")
    print(f"    {sys.executable} -m pip install numpy trimesh pyrender Pillow PyOpenGL")
    sys.exit(1)

# --- Cross-platform rendering patch ---
# Use EGL for headless rendering on Linux, otherwise let pyrender choose.
if sys.platform.startswith('linux'):
    os.environ['PYOPENGL_PLATFORM'] = 'egl'


# --- 2. Core Functions ---

# Удалены функции ввода пользователя, этот файл ожидает данные через JSON-конфигурацию

def _create_handle(handle_style, handle_position, width, height, door='Основная дверь', section_bounds=None):
    """
    Создает геометрию для дверной ручки.
    """
    handle_parts = []
# Определяем позицию ручки
    if door == 'Вторая дверь':
        x_pos_offset = 0.05  # Смещение на 5% от края
    else:
        x_pos_offset = 0.1
    if section_bounds:
        x_start, x_end = section_bounds
        section_width = max(0.0, x_end - x_start)
        if handle_position == 'Лево':
            x_pos = x_start + (section_width * x_pos_offset)
        elif handle_position == 'Центр':
            x_pos = x_start + (section_width * 0.5)
        else:
            x_pos = x_end - (section_width * x_pos_offset)
    else:
        if handle_position == 'Лево':
            x_pos = width * x_pos_offset
        elif handle_position == 'Центр':
            x_pos = width * 0.5
        else:
            x_pos = width * (1 - x_pos_offset)
    
    y_pos = height * 0.5  # По центру высоты
    
    if handle_style == 'Современный':
        # Современная ручка - прямоугольная планка
        handle_width = 0.02
        handle_height = 0.15
        handle_depth = 0.04
        
        # Основная планка ручки
        handle_bar = trimesh.creation.box(
            extents=[handle_width, handle_height, handle_depth],
            transform=trimesh.transformations.translation_matrix([x_pos, y_pos, handle_depth/2 + 0.01])
        )
        handle_parts.append(handle_bar)
        
        # Монтажные пластины
        mount_plate_top = trimesh.creation.box(
            extents=[handle_width*1.5, handle_width, 0.005],
            transform=trimesh.transformations.translation_matrix([x_pos, y_pos + handle_height/2, 0.01])
        )
        mount_plate_bottom = trimesh.creation.box(
            extents=[handle_width*1.5, handle_width, 0.005],
            transform=trimesh.transformations.translation_matrix([x_pos, y_pos - handle_height/2, 0.01])
        )
        handle_parts.extend([mount_plate_top, mount_plate_bottom])
        
    else:  # Классический
        # Классическая ручка - круглая с кольцом
        handle_radius = 0.04
        handle_thickness = 0.008
        
        # Создаем кольцо для ручки
        ring = trimesh.creation.torus(
            major_radius=handle_radius, 
            minor_radius=handle_thickness
        )
        # Поворачиваем кольцо, чтобы оно было перпендикулярно стеклу
        ring.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [1, 0, 0]))
        ring.apply_transform(trimesh.transformations.translation_matrix([x_pos, y_pos, handle_radius + 0.015]))
        handle_parts.append(ring)
        
        # Монтажная розетка
        mount_base = trimesh.creation.cylinder(
            radius=handle_radius * 0.6,
            height=0.01,
            transform=trimesh.transformations.translation_matrix([x_pos, y_pos, 0.01])
        )
        handle_parts.append(mount_base)
    
    return handle_parts

def _get_validated_float(prompt):
    """Вспомогательная функция для получения положительного числа с плавающей точкой."""
    while True:
        try:
            val = float(input(prompt))
            if val <= 0: raise ValueError("Value must be positive.")
            return val
        except ValueError:
            print("   [Неверный ввод] Пожалуйста, введите положительное число (например, 2.5).")

def _get_validated_int(prompt, allow_zero=False):
    """Вспомогательная функция для получения положительного (или нулевого) целого числа."""
    while True:
        try:
            val = int(input(prompt))
            if allow_zero and val < 0:
                raise ValueError("Value cannot be negative.")
            elif not allow_zero and val <= 0:
                raise ValueError("Value must be positive.")
            return val
        except ValueError:
            print("   [Неверный ввод] Пожалуйста, введите целое неотрицательное число.")

def _normalize_mullion_positions(positions, total_length, frame_thickness):
    if not positions:
        return []
    cleaned = []
    for pos in positions:
        try:
            cleaned.append(float(pos))
        except (TypeError, ValueError):
            continue
    if not cleaned:
        return []
    unique_positions = sorted(set(cleaned))
    filtered = []
    last_end = frame_thickness
    max_left = total_length - (frame_thickness * 2.0)
    for pos in unique_positions:
        if pos < frame_thickness or pos > max_left:
            continue
        if pos - last_end < frame_thickness:
            continue
        filtered.append(pos)
        last_end = pos + frame_thickness
    return filtered


def _segments_from_mullions(total_length, frame_thickness, positions):
    segments = []
    start = frame_thickness
    for pos in positions:
        end = pos
        if end - start > 0:
            segments.append((start, end))
        start = pos + frame_thickness
    end = total_length - frame_thickness
    if end - start > 0:
        segments.append((start, end))
    return segments


def _segments_from_cols(total_length, frame_thickness, cols):
    segments = []
    num_cols = max(1, cols)
    pane_width = (total_length - (num_cols + 1) * frame_thickness) / num_cols
    for idx in range(num_cols):
        x_start = frame_thickness + idx * (pane_width + frame_thickness)
        x_end = x_start + pane_width
        segments.append((x_start, x_end))
    return segments


def _segments_from_rows(total_length, frame_thickness, rows):
    segments = []
    num_rows = max(1, rows)
    pane_height = (total_length - (num_rows + 1) * frame_thickness) / num_rows
    for idx in range(num_rows):
        y_start = frame_thickness + idx * (pane_height + frame_thickness)
        y_end = y_start + pane_height
        segments.append((y_start, y_end))
    return segments


def _door_highlight_parts_for_panel(x_start, x_end, y_start, y_end, total_width, total_height, frame_thickness, multiplier=1.35):
    parts = []
    thickness = frame_thickness * multiplier
    extra = (thickness - frame_thickness) / 2.0
    z_min = -frame_thickness / 2.0
    z_max = frame_thickness / 2.0

    def _clamp(val, min_val, max_val):
        return max(min_val, min(val, max_val))

    def _add_box(x0, x1, y0, y1):
        if x1 <= x0 or y1 <= y0:
            return
        parts.append(trimesh.creation.box(bounds=[[x0, y0, z_min], [x1, y1, z_max]]))

    left_x0 = _clamp(x_start - frame_thickness - extra, 0.0, total_width)
    left_x1 = _clamp(x_start + extra, 0.0, total_width)
    right_x0 = _clamp(x_end - extra, 0.0, total_width)
    right_x1 = _clamp(x_end + frame_thickness + extra, 0.0, total_width)
    bottom_y0 = _clamp(y_start - frame_thickness - extra, 0.0, total_height)
    bottom_y1 = _clamp(y_start + extra, 0.0, total_height)
    top_y0 = _clamp(y_end - extra, 0.0, total_height)
    top_y1 = _clamp(y_end + frame_thickness + extra, 0.0, total_height)
    vertical_y0 = _clamp(y_start - frame_thickness - extra, 0.0, total_height)
    vertical_y1 = _clamp(y_end + frame_thickness + extra, 0.0, total_height)
    horizontal_x0 = _clamp(x_start - frame_thickness - extra, 0.0, total_width)
    horizontal_x1 = _clamp(x_end + frame_thickness + extra, 0.0, total_width)

    _add_box(left_x0, left_x1, vertical_y0, vertical_y1)
    _add_box(right_x0, right_x1, vertical_y0, vertical_y1)
    _add_box(horizontal_x0, horizontal_x1, bottom_y0, bottom_y1)
    _add_box(horizontal_x0, horizontal_x1, top_y0, top_y1)

    return parts


def _collect_handle_sections(params):
    return _collect_section_list(params.get('handle_sections'))


def _collect_section_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [int(s) for s in value if isinstance(s, int) or str(s).isdigit()]
    raw = str(value).strip()
    if not raw:
        return []
    result = []
    for token in re.split(r'[|,;\\s]+', raw):
        if not token:
            continue
        if token.isdigit():
            result.append(int(token))
            continue
        try:
            result.append(int(float(token.replace(',', '.'))))
        except ValueError:
            continue
    return result


def _create_wall_segment(width, height, rows, cols, frame_thickness, vertical_mullions=None, horizontal_mullions=None, door_sections=None):
    """
    Создает геометрию для одного прямого сегмента стены.
    Это основной переиспользуемый блок для построения всех форм.
    """
    FRAME_THICKNESS = frame_thickness
    GLASS_THICKNESS = 0.01
    
    frame_parts = []
    glass_panes = []

    # Внешняя рама
    frame_parts.append(trimesh.creation.box(bounds=[[0, 0, -FRAME_THICKNESS/2], [width, FRAME_THICKNESS, FRAME_THICKNESS/2]]))
    frame_parts.append(trimesh.creation.box(bounds=[[0, height - FRAME_THICKNESS, -FRAME_THICKNESS/2], [width, height, FRAME_THICKNESS/2]]))
    frame_parts.append(trimesh.creation.box(bounds=[[0, 0, -FRAME_THICKNESS/2], [FRAME_THICKNESS, height, FRAME_THICKNESS/2]]))
    frame_parts.append(trimesh.creation.box(bounds=[[width - FRAME_THICKNESS, 0, -FRAME_THICKNESS/2], [width, height, FRAME_THICKNESS/2]]))

    # Используем max(1, ...), чтобы ввод 0 обрабатывался как 1 большая панель.
    num_cols = max(1, cols)
    num_rows = max(1, rows)
    use_custom_vertical = vertical_mullions is not None
    use_custom_horizontal = horizontal_mullions is not None
    vertical_positions = _normalize_mullion_positions(vertical_mullions, width, FRAME_THICKNESS)
    horizontal_positions = _normalize_mullion_positions(horizontal_mullions, height, FRAME_THICKNESS)
    
    # Внутренние вертикальные разделители
    if vertical_positions:
        for x_pos in vertical_positions:
            mullion = trimesh.creation.box(bounds=[[x_pos, FRAME_THICKNESS, -FRAME_THICKNESS/2], [x_pos + FRAME_THICKNESS, height - FRAME_THICKNESS, FRAME_THICKNESS/2]])
            frame_parts.append(mullion)
    elif not use_custom_vertical and cols > 1:
        pane_width = (width - (num_cols + 1) * FRAME_THICKNESS) / num_cols
        for i in range(1, num_cols):
            x_pos = i * (pane_width + FRAME_THICKNESS)
            mullion = trimesh.creation.box(bounds=[[x_pos, FRAME_THICKNESS, -FRAME_THICKNESS/2], [x_pos + FRAME_THICKNESS, height - FRAME_THICKNESS, FRAME_THICKNESS/2]])
            frame_parts.append(mullion)

    # Внутренние горизонтальные разделители
    if horizontal_positions:
        for y_pos in horizontal_positions:
            mullion = trimesh.creation.box(bounds=[[FRAME_THICKNESS, y_pos, -FRAME_THICKNESS/2], [width - FRAME_THICKNESS, y_pos + FRAME_THICKNESS, FRAME_THICKNESS/2]])
            frame_parts.append(mullion)
    elif not use_custom_horizontal and rows > 1:
        pane_height = (height - (num_rows + 1) * FRAME_THICKNESS) / num_rows
        for i in range(1, num_rows):
            y_pos = i * (pane_height + FRAME_THICKNESS)
            mullion = trimesh.creation.box(bounds=[[FRAME_THICKNESS, y_pos, -FRAME_THICKNESS/2], [width - FRAME_THICKNESS, y_pos + FRAME_THICKNESS, FRAME_THICKNESS/2]])
            frame_parts.append(mullion)

    if use_custom_vertical:
        x_segments = _segments_from_mullions(width, FRAME_THICKNESS, vertical_positions)
        if not x_segments:
            x_segments = _segments_from_mullions(width, FRAME_THICKNESS, [])
    else:
        x_segments = _segments_from_cols(width, FRAME_THICKNESS, num_cols)

    if use_custom_horizontal:
        y_segments = _segments_from_mullions(height, FRAME_THICKNESS, horizontal_positions)
        if not y_segments:
            y_segments = _segments_from_mullions(height, FRAME_THICKNESS, [])
    else:
        y_segments = _segments_from_rows(height, FRAME_THICKNESS, num_rows)

    # Стеклянные панели
    for x_start, x_end in x_segments:
        for y_start, y_end in y_segments:
            pane_width = x_end - x_start
            pane_height = y_end - y_start
            pane_center = [x_start + pane_width / 2, y_start + pane_height / 2, 0]
            pane_extents = [pane_width, pane_height, GLASS_THICKNESS]
            pane = trimesh.creation.box(extents=pane_extents, transform=trimesh.transformations.translation_matrix(pane_center))
            glass_panes.append(pane)

    if door_sections:
        for section_index in door_sections:
            if not isinstance(section_index, int):
                continue
            if 1 <= section_index <= len(x_segments):
                x_start, x_end = x_segments[section_index - 1]
                for y_start, y_end in y_segments:
                    frame_parts.extend(
                        _door_highlight_parts_for_panel(
                            x_start,
                            x_end,
                            y_start,
                            y_end,
                            width,
                            height,
                            FRAME_THICKNESS,
                        )
                    )
            
    return frame_parts, glass_panes

def apply_discounts(params):
    """
    Backward-compatible total price helper.

    The authoritative pricing formula lives in src.engine.pricing_engine so the
    renderer cannot drift from the database-backed price catalog.
    """
    from src.engine.pricing_engine import calculate_price
    from src.utils.query_parser import normalize_render_params

    normalized = normalize_render_params(params)
    price = calculate_price(
        shape=normalized["shape"],
        height=float(normalized.get("height") or 3.0),
        width_a=float(normalized.get("width_a") or 2.0),
        width_b=float(normalized.get("width_b") or 0),
        width_c=float(normalized.get("width_c") or 0),
        glass_type=str(normalized.get("glass_type") or "1"),
        frame_color=str(normalized.get("frame_color_id") or normalized.get("frame_color") or "1"),
        rows=int(normalized.get("rows") or 1),
        cols=int(normalized.get("cols") or 2),
        add_handle=bool(normalized.get("add_handle")),
        partition_type=str(normalized.get("partition_type") or "sliding_2"),
        matting=str(normalized.get("matting") or "none"),
        complex_pattern=bool(normalized.get("complex_pattern")),
    )
    return price["total_price"]



# Updated function to create meshes


def _apply_transform(meshes, transform):
    for mesh in meshes:
        mesh.apply_transform(transform)


def _select_wall_param(params, base_key, wall_name, shape_side):
    candidates = []
    if wall_name == 'front':
        candidates = [f"{base_key}_front", f"{base_key}_main"]
    elif wall_name == 'side':
        candidates = [f"{base_key}_side"]
        if shape_side == 'left':
            candidates.append(f"{base_key}_left")
        elif shape_side == 'right':
            candidates.append(f"{base_key}_right")
    elif wall_name == 'left':
        candidates = [f"{base_key}_left"]
    elif wall_name == 'right':
        candidates = [f"{base_key}_right"]
    elif wall_name == 'main':
        candidates = [f"{base_key}_main", f"{base_key}_front"]
    for key in candidates:
        if params.get(key) is not None:
            return params.get(key)
    return params.get(base_key)


def _select_wall_int(params, base_key, wall_name, shape_side, default_value):
    value = _select_wall_param(params, base_key, wall_name, shape_side)
    if value is None:
        value = default_value
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default_value)
    return max(1, parsed)


def _wall_grid(params, wall_name, shape_side, default_rows, default_cols):
    return (
        _select_wall_int(params, 'rows', wall_name, shape_side, default_rows),
        _select_wall_int(params, 'cols', wall_name, shape_side, default_cols),
    )


def _matches_handle_wall(handle_wall, wall_name, shape_side):
    if not handle_wall:
        return wall_name == 'front'
    if handle_wall in ('main', 'front'):
        return wall_name == 'front'
    if handle_wall == 'side':
        return wall_name == 'side'
    if wall_name == 'side' and handle_wall in ('left', 'right'):
        return (shape_side == handle_wall)
    return handle_wall == wall_name


def _create_handles_for_wall(params, width, height, frame_thickness, vertical_mullions, cols):
    handle_style = params.get('handle_style', 'Современный')
    handle_position = params.get('handle_position', 'Лево')
    handle_door = params.get('handle_door', 'Основная дверь')
    handle_sections = _collect_handle_sections(params)

    if handle_sections:
        normalized_positions = _normalize_mullion_positions(vertical_mullions, width, frame_thickness)
        if normalized_positions:
            x_segments = _segments_from_mullions(width, frame_thickness, normalized_positions)
        else:
            x_segments = _segments_from_cols(width, frame_thickness, int(cols or 1))
        handle_parts = []
        for section_index in handle_sections:
            if 1 <= section_index <= len(x_segments):
                section_bounds = x_segments[section_index - 1]
                handle_parts.extend(
                    _create_handle(
                        handle_style,
                        handle_position,
                        width,
                        height,
                        handle_door,
                        section_bounds=section_bounds,
                    )
                )
        return handle_parts

    return _create_handle(handle_style, handle_position, width, height, handle_door)


def create_partition_mesh(params):
    """
    Функция верхнего уровня для генерации геометрии на основе выбранной формы.
    Она комбинирует один или несколько сегментов стены.
    """
    # Безопасное извлечение параметров с дефолтными значениями
    H = float(params.get('height', 3.0))
    R = int(params.get('rows', 1))
    C = int(params.get('cols', 1))
    FT = float(params.get('frame_thickness', 0.04)) # Толщина рамы
    vertical_mullions = params.get('vertical_mullions')
    horizontal_mullions = params.get('horizontal_mullions')
    handle_wall = params.get('handle_wall')
    add_handle = params.get('add_handle', False)
    door_wall = params.get('door_wall') or handle_wall or 'front'
    door_sections = _collect_section_list(params.get('door_sections'))
    
    # Дефолтная форма, если не указана
    shape = params.get('shape', 'Прямая')
    shape_side_raw = params.get('shape_side')
    if shape_side_raw is None:
        shape_side = 'right'
    else:
        shape_side = str(shape_side_raw).strip().lower()
        if shape_side not in ('left', 'right'):
            shape_side = 'right'

    all_frame_parts = []
    all_glass_panes = []
    all_handle_parts = []

    if shape == 'Прямая':
        # Default width if missing
        W_A = float(params.get('width_a', 2.0))
        R_FRONT, C_FRONT = _wall_grid(params, 'front', shape_side, R, C)
        vm = _select_wall_param(params, 'vertical_mullions', 'front', shape_side)
        hm = _select_wall_param(params, 'horizontal_mullions', 'front', shape_side)
        door_sections_front = door_sections if _matches_handle_wall(door_wall, 'front', shape_side) else None
        frame, glass = _create_wall_segment(W_A, H, R_FRONT, C_FRONT, FT, vm, hm, door_sections_front)
        all_frame_parts.extend(frame)
        all_glass_panes.extend(glass)
        if add_handle and _matches_handle_wall(handle_wall, 'front', shape_side):
            all_handle_parts.extend(_create_handles_for_wall(params, W_A, H, FT, vm, C_FRONT))

    elif shape == 'Г-образная':
        W_A = float(params.get('width_a', 2.0))
        W_B = float(params.get('width_b', 1.5))
        
        # Стена A (основная)
        R_A, C_A = _wall_grid(params, 'front', shape_side, R, C)
        vm_a = _select_wall_param(params, 'vertical_mullions', 'front', shape_side)
        hm_a = _select_wall_param(params, 'horizontal_mullions', 'front', shape_side)
        door_sections_front = door_sections if _matches_handle_wall(door_wall, 'front', shape_side) else None
        frame_a, glass_a = _create_wall_segment(W_A, H, R_A, C_A, FT, vm_a, hm_a, door_sections_front)
        all_frame_parts.extend(frame_a)
        all_glass_panes.extend(glass_a)
        if add_handle and _matches_handle_wall(handle_wall, 'front', shape_side):
            all_handle_parts.extend(_create_handles_for_wall(params, W_A, H, FT, vm_a, C_A))
        
        # Стена B (боковая)
        R_B, C_B = _wall_grid(params, 'side', shape_side, R, C)
        vm_b = _select_wall_param(params, 'vertical_mullions', 'side', shape_side)
        hm_b = _select_wall_param(params, 'horizontal_mullions', 'side', shape_side)
        door_sections_side = door_sections if _matches_handle_wall(door_wall, 'side', shape_side) else None
        frame_b, glass_b = _create_wall_segment(W_B, H, R_B, C_B, FT, vm_b, hm_b, door_sections_side)
        handle_b_parts = []
        if add_handle and _matches_handle_wall(handle_wall, 'side', shape_side):
            handle_b_parts = _create_handles_for_wall(params, W_B, H, FT, vm_b, C_B)
        
        # Поворот на 90 градусов (вокруг Y), чтобы направить вдоль -Z
        rotation = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])
        
        if shape_side == 'left':
            # Стыкуем слева (начало стены A)
            # Wall B (rotated) starts at X=0 (thickness center), extends -Z
            translation = trimesh.transformations.translation_matrix([0, 0, FT])
        else:
            # Стыкуем справа (конец стены A)
            translation = trimesh.transformations.translation_matrix([W_A - FT, 0, FT])
            
        for part in frame_b:
            part.apply_transform(rotation)
            part.apply_transform(translation)
            all_frame_parts.append(part)
        for part in glass_b:
            part.apply_transform(rotation)
            part.apply_transform(translation)
            all_glass_panes.append(part)
        if handle_b_parts:
            _apply_transform(handle_b_parts, rotation)
            _apply_transform(handle_b_parts, translation)
            all_handle_parts.extend(handle_b_parts)

    elif shape == 'П-образная':
        W_FRONT = float(params.get('width_a', 2.0))
        W_LEFT = float(params.get('width_b', 1.5))
        W_RIGHT = float(params.get('width_c', 1.5))

        # Стена A (основная/центральная) - основа координат
        R_FRONT, C_FRONT = _wall_grid(params, 'front', shape_side, R, C)
        vm_b = _select_wall_param(params, 'vertical_mullions', 'front', shape_side)
        hm_b = _select_wall_param(params, 'horizontal_mullions', 'front', shape_side)
        door_sections_front = door_sections if _matches_handle_wall(door_wall, 'front', shape_side) else None
        frame_b, glass_b = _create_wall_segment(W_FRONT, H, R_FRONT, C_FRONT, FT, vm_b, hm_b, door_sections_front)
        all_frame_parts.extend(frame_b)
        all_glass_panes.extend(glass_b)
        if add_handle and _matches_handle_wall(handle_wall, 'front', shape_side):
            all_handle_parts.extend(_create_handles_for_wall(params, W_FRONT, H, FT, vm_b, C_FRONT))

        # Стена B (левая боковая)
        R_LEFT, C_LEFT = _wall_grid(params, 'left', shape_side, R, C)
        vm_a = _select_wall_param(params, 'vertical_mullions', 'left', shape_side)
        hm_a = _select_wall_param(params, 'horizontal_mullions', 'left', shape_side)
        door_sections_left = door_sections if _matches_handle_wall(door_wall, 'left', shape_side) else None
        frame_a, glass_a = _create_wall_segment(W_LEFT, H, R_LEFT, C_LEFT, FT, vm_a, hm_a, door_sections_left)
        handle_a_parts = []
        if add_handle and _matches_handle_wall(handle_wall, 'left', shape_side):
            handle_a_parts = _create_handles_for_wall(params, W_LEFT, H, FT, vm_a, C_LEFT)
        rot_a = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])
        trans_a = trimesh.transformations.translation_matrix([0, 0, FT])
        for part in frame_a: 
            part.apply_transform(rot_a)
            part.apply_transform(trans_a) 
            all_frame_parts.append(part)
        for part in glass_a: 
            part.apply_transform(rot_a)
            part.apply_transform(trans_a)
            all_glass_panes.append(part)
        if handle_a_parts:
            _apply_transform(handle_a_parts, rot_a)
            _apply_transform(handle_a_parts, trans_a)
            all_handle_parts.extend(handle_a_parts)
        
        # Стена C (правая боковая)
        R_RIGHT, C_RIGHT = _wall_grid(params, 'right', shape_side, R, C)
        vm_c = _select_wall_param(params, 'vertical_mullions', 'right', shape_side)
        hm_c = _select_wall_param(params, 'horizontal_mullions', 'right', shape_side)
        door_sections_right = door_sections if _matches_handle_wall(door_wall, 'right', shape_side) else None
        frame_c, glass_c = _create_wall_segment(W_RIGHT, H, R_RIGHT, C_RIGHT, FT, vm_c, hm_c, door_sections_right)
        handle_c_parts = []
        if add_handle and _matches_handle_wall(handle_wall, 'right', shape_side):
            handle_c_parts = _create_handles_for_wall(params, W_RIGHT, H, FT, vm_c, C_RIGHT)
        rot_c = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])
        trans_c = trimesh.transformations.translation_matrix([W_FRONT - FT, 0, FT])
        for part in frame_c: 
            part.apply_transform(rot_c)
            part.apply_transform(trans_c)
            all_frame_parts.append(part)
        for part in glass_c: 
            part.apply_transform(rot_c)
            part.apply_transform(trans_c)
            all_glass_panes.append(part)
        if handle_c_parts:
            _apply_transform(handle_c_parts, rot_c)
            _apply_transform(handle_c_parts, trans_c)
            all_handle_parts.extend(handle_c_parts)

    if not all_frame_parts:
        # Fallback если ничего не создалось (не должно случаться с дефолтами)
        raise RuntimeError("Не удалось сгенерировать геометрию.")

    full_frame_mesh = trimesh.util.concatenate(all_frame_parts)
    full_glass_mesh = trimesh.util.concatenate(all_glass_panes)
    
    # Комбинируем ручку, если она есть
    if all_handle_parts:
        full_handle_mesh = trimesh.util.concatenate(all_handle_parts)
    else:
        full_handle_mesh = None

    # Центрируем всю составную модель в начале координат
    center_offset = trimesh.transformations.translation_matrix(-full_frame_mesh.bounds.mean(axis=0))
    full_frame_mesh.apply_transform(center_offset)
    full_glass_mesh.apply_transform(center_offset)
    if full_handle_mesh:
        full_handle_mesh.apply_transform(center_offset)

    return full_frame_mesh, full_glass_mesh, full_handle_mesh

def render_scene(frame_mesh, glass_mesh, params, handle_mesh=None, y_rotation_deg=0, system_config=None):
    """
    Настраивает и рендерит сцену pyrender с улучшенной камерой и PBR материалами.
    Использует system_config для получения параметров материалов, если они доступны.
    """
    if system_config is None: system_config = {}
    
    # Настройка логгера
    logger = setup_logger(__name__)
    
    IMG_WIDTH, IMG_HEIGHT = 2560, 1440 # 2K разрешение
    SUPERSAMPLE_FACTOR = 2

    # --- Материалы (PBR) ---
    materials_db = system_config.get('materials', {})
    
    # 1. Рама (Frame)
    # По умолчанию используем цвет из params
    frame_color = params.get('frame_color', [0.1, 0.1, 0.1, 1.0])
    frame_roughness = 0.5
    frame_metallic = 0.7
    
    # Если передан ID материала (будущая фича), ищем в базе
    # if 'frame_material_id' in params: ...
    
    frame_material = pyrender.MetallicRoughnessMaterial(
        baseColorFactor=frame_color, 
        metallicFactor=frame_metallic, 
        roughnessFactor=frame_roughness
    )

    # 2. Стекло (Glass)
    glass_color = params.get('glass_color', [0.85, 0.85, 0.85, 0.3])
    glass_roughness = params.get('glass_roughness', 0.05)
    
    glass_material = pyrender.MetallicRoughnessMaterial(
        baseColorFactor=glass_color, 
        metallicFactor=0.1,
        roughnessFactor=glass_roughness, 
        alphaMode='BLEND'
    )
    
    # 3. Ручка (Handle)
    handle_material = pyrender.MetallicRoughnessMaterial(
        baseColorFactor=[0.8, 0.8, 0.85, 1.0], 
        metallicFactor=0.9, 
        roughnessFactor=0.1
    )

    # Настройка сцены
    scene = pyrender.Scene(ambient_light=[0.2, 0.2, 0.2], bg_color=[0.1, 0.1, 0.15, 1.0])
    scene.add(pyrender.Mesh.from_trimesh(frame_mesh, material=frame_material))
    scene.add(pyrender.Mesh.from_trimesh(glass_mesh, material=glass_material))
    
    if handle_mesh is not None:
        scene.add(pyrender.Mesh.from_trimesh(handle_mesh, material=handle_material))

    # Настройка камеры. Для технической визуализации используем orthographic,
    # чтобы расстояние между секциями не менялось от ракурса к ракурсу.
    aspect_ratio = float(IMG_WIDTH) / IMG_HEIGHT
    max_extent = np.max(frame_mesh.extents)
    horizontal_diag = float(np.linalg.norm(frame_mesh.extents[[0, 2]]))
    view_half_width = max(horizontal_diag * 0.62, 1.0)
    view_half_height = max(float(frame_mesh.extents[1]) * 0.62, view_half_width / aspect_ratio, 1.0)
    camera_distance = max(max_extent * 3.0, 4.0)

    camera = pyrender.OrthographicCamera(
        xmag=view_half_width,
        ymag=view_half_height,
        znear=0.05,
        zfar=1000.0,
    )

    # Углы для камеры
    y_rot_angle = np.radians(y_rotation_deg)
    x_rot_angle = np.radians(-15) # Наклон вниз

    # Составляем матрицу позиции камеры
    cam_rotation_y = trimesh.transformations.rotation_matrix(y_rot_angle, [0, 1, 0])
    cam_rotation_x = trimesh.transformations.rotation_matrix(x_rot_angle, [1, 0, 0])
    cam_rotation = cam_rotation_y @ cam_rotation_x
    cam_translation = trimesh.transformations.translation_matrix([0, 0, camera_distance])
    
    camera_pose = cam_rotation @ cam_translation
    
    # Safe height access
    height_val = float(params.get('height', 3.0))
    camera_pose[1, 3] = height_val * 0.2

    scene.add(camera, pose=camera_pose)

    # Профессиональное студийное освещение (3-точечное)
    
    # 1. Key Light (Основной) - теплый, справа-сверху
    key_light = pyrender.DirectionalLight(color=[1.0, 0.9, 0.8], intensity=5.0)
    key_pose = trimesh.transformations.rotation_matrix(np.radians(-45), [1, 0, 0]) @ \
               trimesh.transformations.rotation_matrix(np.radians(45), [0, 1, 0])
    scene.add(key_light, pose=key_pose)

    # 2. Fill Light (Заполняющий) - холодный, слева
    fill_light = pyrender.DirectionalLight(color=[0.8, 0.85, 1.0], intensity=2.5)
    fill_pose = trimesh.transformations.rotation_matrix(np.radians(-30), [1, 0, 0]) @ \
                trimesh.transformations.rotation_matrix(np.radians(-60), [0, 1, 0])
    scene.add(fill_light, pose=fill_pose)

    # 3. Rim Light (Контровой) - яркий белый, сзади-сверху для выделения контуров
    rim_light = pyrender.DirectionalLight(color=[1.0, 1.0, 1.0], intensity=4.0)
    rim_pose = trimesh.transformations.rotation_matrix(np.radians(-135), [0, 1, 0]) @ \
               trimesh.transformations.rotation_matrix(np.radians(-30), [1, 0, 0])
    scene.add(rim_light, pose=rim_pose)

    # --- Рендеринг высокого качества с суперсэмплингом ---
    render_width = IMG_WIDTH * SUPERSAMPLE_FACTOR
    render_height = IMG_HEIGHT * SUPERSAMPLE_FACTOR
    
    # Пытаемся создать рендерер с обработкой ошибок
    renderer = None
    try:
        renderer = pyrender.OffscreenRenderer(render_width, render_height)
        logger.info(f"Рендерер создан успешно: {render_width}x{render_height}")
    except Exception as e:
        logger.warning(f"Не удалось создать рендерер с текущими настройками: {e}")
        
        # Попытка использовать программный рендеринг (osmesa)
        if sys.platform.startswith('linux'):
            logger.info("Пытаемся использовать osmesa для программного рендеринга...")
            original_platform = os.environ.get('PYOPENGL_PLATFORM')
            os.environ['PYOPENGL_PLATFORM'] = 'osmesa'
            try:
                renderer = pyrender.OffscreenRenderer(render_width, render_height)
                logger.info("Успешно создан рендерер через osmesa")
            except:
                # Восстанавливаем оригинальную платформу
                if original_platform:
                    os.environ['PYOPENGL_PLATFORM'] = original_platform
                else:
                    os.environ.pop('PYOPENGL_PLATFORM', None)
                raise
        
        # Если все еще не удалось, пытаемся с меньшим разрешением
        if renderer is None:
            logger.warning("Пытаемся создать рендерер с меньшим разрешением...")
            render_width = IMG_WIDTH
            render_height = IMG_HEIGHT
            SUPERSAMPLE_FACTOR = 1
            try:
                renderer = pyrender.OffscreenRenderer(render_width, render_height)
                logger.info(f"Успешно создан рендерер без суперсэмплинга: {render_width}x{render_height}")
            except Exception as final_error:
                logger.error(f"Не удалось создать рендерер: {final_error}")
                raise RuntimeError("Не удалось инициализировать рендеринг. Проверьте установку OpenGL.")
    
    try:
        color, depth = renderer.render(scene)
    finally:
        # Всегда удаляем рендерер для освобождения ресурсов
        if renderer:
            renderer.delete()

    # Уменьшаем изображение до целевого размера с качественным фильтром
    img = Image.fromarray(color)
    try:
        resampling_filter = Image.Resampling.LANCZOS
    except AttributeError:
        resampling_filter = Image.LANCZOS
    img = img.resize((IMG_WIDTH, IMG_HEIGHT), resample=resampling_filter)

    return np.array(img)


def generate_from_params(user_params, system_config=None):
    """Generate renders based on prepared parameters."""
    if system_config is None: system_config = {}

    # Определяем директорию для сохранения результатов
    # Если запущено через сервер, сохраняем в текущую директорию (сервер уже изменил ее на results/request_id/)
    # Если запущено напрямую, сохраняем в локальную директорию outputs
    if os.environ.get('SERVER_MODE'):
        # При запуске через сервер сохраняем в текущую директорию
        output_dir = "."
    else:
        # При прямом запуске используем OUTPUT_DIR или outputs по умолчанию
        output_dir = os.environ.get('OUTPUT_DIR', 'outputs')
        os.makedirs(output_dir, exist_ok=True)

    frame, glass, handle = create_partition_mesh(user_params)
    
    current_shape = user_params.get('shape', 'Прямая')
    is_complex_shape = current_shape in ['Г-образная', 'П-образная']

    if is_complex_shape:
        print(f"\n[ИНФО] Генерация 4 ракурсов для {current_shape.lower()} формы...")
        angles = [0, 90, 180, 270]
        base_angle = -45  # Базовый угол для красивого вида в 3/4
        output_files = []
        for i, angle_offset in enumerate(angles):
            current_angle = base_angle + angle_offset
            print(f"[ИНФО] Рендеринг ракурса {i+1}/4 (угол: {int(current_angle)}°)...")
            image_data = render_scene(frame, glass, user_params, handle, y_rotation_deg=current_angle, system_config=system_config)
            filename = f"partition_render_hq_{angle_offset}deg.png"
            output_path = os.path.join(output_dir, filename)
            Image.fromarray(image_data).save(output_path)
            output_files.append(output_path)

    # --- РАСЧЕТ СТАТИСТИКИ (ПЛОЩАДЬ) ---
    width_a = float(user_params.get('width_a', 2.0))
    height = float(user_params.get('height', 3.0))
    
    calc_area = width_a * height
    
    # Добавляем площадь боковых стен для сложных форм
    if user_params.get('shape') in ['Г-образная', 'П-образная']:
        # Для Г- и П-образных всегда есть side_b (ширина B)
        width_b = float(user_params.get('width_b', 0.0))
        calc_area += width_b * height
        
        # Для П-образной добавляем side_c (ширина C)
        if user_params.get('shape') == 'П-образная':
            width_c = float(user_params.get('width_c', 0.0))
            calc_area += width_c * height

    stats_data = {
        "area_sq_m": round(calc_area, 2),
        "params": user_params,
        "generated_at": datetime.datetime.now().isoformat()
    }

    stats_path = os.path.join(output_dir, "stats.json")
    with open(stats_path, 'w', encoding='utf-8') as f:
        json.dump(stats_data, f, indent=2, ensure_ascii=False)
    
    print(f"[ИНФО] Статистика сохранена: {stats_path} (Площадь: {stats_data['area_sq_m']} м2)")

    if is_complex_shape:
        print("\n--------------------------------------------------")
        print("\033[92m[УСПЕХ] Задача выполнена.\033[0m")
        print(f"Сгенерировано {len(output_files)} рендера высокого качества:")
        for f in output_files:
            # Показываем только имя файла, без полного пути
            print(f"  - \033[1m{os.path.basename(f)}\033[0m")
        print(f"Файлы сохранены в: {output_dir}")
        print("--------------------------------------------------")
    else:
        print("[ИНФО] Рендеринг высококачественной 3D-сцены...")
        image_data = render_scene(frame, glass, user_params, handle, y_rotation_deg=0, system_config=system_config)
        output_path = os.path.join(output_dir, "partition_render_hq.png")
        Image.fromarray(image_data).save(output_path)

        print("\n--------------------------------------------------")
        print("\033[92m[УСПЕХ] Задача выполнена.\033[0m")
        print(f"Рендер высокого качества сохранен как: \033[1m{os.path.basename(output_path)}\033[0m")
        print(f"Путь: {output_dir}")
        print("--------------------------------------------------")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Генератор 3D-перегородок")
    parser.add_argument("--config", help="Путь к JSON с параметрами", required=True)
    args = parser.parse_args()

    try:
        with open(args.config, "r", encoding="utf-8") as fh:
            loaded_config = json.load(fh)
        
        # Поддержка новой (с system_config) и старой (без) структуры
        if 'user_params' in loaded_config:
            user_params = loaded_config['user_params']
            system_config = loaded_config.get('system', {})
        else:
            user_params = loaded_config
            system_config = {}

        generate_from_params(user_params, system_config)
    except KeyboardInterrupt:
        print("\n\n[ИНФО] Процесс прерван пользователем. Выход.")
        sys.exit(0)
    except FileNotFoundError:
        print(f"\n\n\033[91m[КРИТИЧЕСКАЯ ОШИБКА] Файл конфигурации не найден: {args.config}\033[0m")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"\n\n\033[91m[КРИТИЧЕСКАЯ ОШИБКА] Ошибка парсинга JSON: {e}\033[0m")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n\033[91m[КРИТИЧЕСКАЯ ОШИБКА] Произошла непредвиденная ошибка: {e}\033[0m")
        print("Целостность системы может быть нарушена. Пожалуйста, просмотрите отчет об ошибке.")
        import traceback
        traceback.print_exc()
        sys.exit(1)
