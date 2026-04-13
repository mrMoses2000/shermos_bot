#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль валидации параметров для 3D визуализации перегородок.
"""

from typing import Dict, Any, List, Tuple, Optional
from utils.config_manager import config
from utils.logger import setup_logger

logger = setup_logger(__name__)


def _parse_float(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().replace(',', '.')
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        value = value.strip().replace(',', '.')
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


class PartitionValidator:
    """
    Класс для валидации параметров перегородок согласно конфигурации.
    """
    
    @staticmethod
    def validate_shape(shape: str) -> Tuple[bool, Optional[str]]:
        """
        Валидация формы перегородки.
        
        Args:
            shape: Форма перегородки
            
        Returns:
            (valid, error_message): Кортеж с результатом валидации
        """
        valid_shapes = ['Прямая', 'Г-образная', 'П-образная']
        if shape not in valid_shapes:
            return False, f"Недопустимая форма: {shape}. Допустимые: {', '.join(valid_shapes)}"
        return True, None
    
    @staticmethod
    def validate_dimensions(params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Валидация размеров перегородки.
        
        Args:
            params: Параметры перегородки
            
        Returns:
            (valid, error_message): Кортеж с результатом валидации
        """
        shape = params.get('shape')
        
        # Проверка высоты
        height_raw = params.get('height')
        if height_raw is None:
            return False, "Не указана высота перегородки"
        height = _parse_float(height_raw)
        if height is None:
            return False, "Высота должна быть числом"

        if not config.validate_constraint('height', height):
            min_h = config.get_constraint('min', 'height')
            max_h = config.get_constraint('max', 'height')
            return False, f"Высота должна быть от {min_h} до {max_h} метров"
        
        # Проверка ширины в зависимости от формы
        if shape == 'Прямая':
            width_a_raw = params.get('width_a')
            if width_a_raw is None:
                return False, "Не указана ширина перегородки"
            width_a = _parse_float(width_a_raw)
            if width_a is None:
                return False, "Ширина должна быть числом"
            if not config.validate_constraint('width', width_a):
                min_w = config.get_constraint('min', 'width')
                max_w = config.get_constraint('max', 'width')
                return False, f"Ширина должна быть от {min_w} до {max_w} метров"
                
        elif shape == 'Г-образная':
            width_a_raw = params.get('width_a')
            width_b_raw = params.get('width_b')
            if width_a_raw is None or width_b_raw is None:
                return False, "Не указаны все размеры для Г-образной формы"
            
            for w_raw, label in [
                (width_a_raw, 'передней'),
                (width_b_raw, 'боковой'),
            ]:
                w = _parse_float(w_raw)
                if w is None:
                    return False, f"Ширина {label} стороны должна быть числом"
                if not config.validate_constraint('width', w):
                    min_w = config.get_constraint('min', 'width')
                    max_w = config.get_constraint('max', 'width')
                    return False, f"Ширина {label} стороны должна быть от {min_w} до {max_w} метров"
                    
        elif shape == 'П-образная':
            width_a_raw = params.get('width_a')
            width_b_raw = params.get('width_b')
            width_c_raw = params.get('width_c')
            if width_a_raw is None or width_b_raw is None or width_c_raw is None:
                return False, "Не указаны все размеры для П-образной формы"
            
            for w_raw, label in [
                (width_a_raw, 'левой'),
                (width_b_raw, 'центральной'),
                (width_c_raw, 'правой'),
            ]:
                w = _parse_float(w_raw)
                if w is None:
                    return False, f"Ширина {label} стороны должна быть числом"
                if not config.validate_constraint('width', w):
                    min_w = config.get_constraint('min', 'width')
                    max_w = config.get_constraint('max', 'width')
                    return False, f"Ширина {label} стороны должна быть от {min_w} до {max_w} метров"
        
        return True, None
    
    @staticmethod
    def validate_sections(rows: int, cols: int) -> Tuple[bool, Optional[str]]:
        """
        Валидация количества секций.
        
        Args:
            rows: Количество горизонтальных секций
            cols: Количество вертикальных секций
            
        Returns:
            (valid, error_message): Кортеж с результатом валидации
        """
        min_sections = config.get_constraint('min', 'sections')
        max_sections = config.get_constraint('max', 'sections')

        rows_val = _parse_int(rows) if rows is not None else 0
        cols_val = _parse_int(cols) if cols is not None else 0
        if rows_val is None or cols_val is None:
            return False, "Количество секций должно быть числом"
        
        if rows_val < min_sections or rows_val > max_sections:
            return False, f"Количество горизонтальных секций должно быть от {min_sections} до {max_sections}"
        
        if cols_val < min_sections or cols_val > max_sections:
            return False, f"Количество вертикальных секций должно быть от {min_sections} до {max_sections}"
        
        return True, None
    
    @staticmethod
    def validate_frame_thickness(thickness: float) -> Tuple[bool, Optional[str]]:
        """
        Валидация толщины рамы.
        
        Args:
            thickness: Толщина рамы в метрах
            
        Returns:
            (valid, error_message): Кортеж с результатом валидации
        """
        if thickness is None:
            return True, None
        thickness_val = _parse_float(thickness)
        if thickness_val is None:
            return False, "Толщина рамы должна быть числом"
        if not config.validate_constraint('frame_thickness', thickness_val):
            min_t = config.get_constraint('min', 'frame_thickness')
            max_t = config.get_constraint('max', 'frame_thickness')
            return False, f"Толщина рамы должна быть от {min_t} до {max_t} метров"
        
        return True, None
    
    @staticmethod
    def validate_materials(frame_color: List[float], glass_color: List[float]) -> Tuple[bool, Optional[str]]:
        """
        Валидация материалов (цветов).
        
        Args:
            frame_color: Цвет рамы [R, G, B, A]
            glass_color: Цвет стекла [R, G, B, A]
            
        Returns:
            (valid, error_message): Кортеж с результатом валидации
        """
        # Проверка формата цветов
        for color, name in [(frame_color, 'Цвет рамы'), (glass_color, 'Цвет стекла')]:
            if not isinstance(color, (list, tuple)) or len(color) != 4:
                return False, f"{name} должен быть списком из 4 значений [R, G, B, A]"
            
            for component in color:
                if not isinstance(component, (int, float)) or component < 0 or component > 1:
                    return False, f"Компоненты цвета должны быть числами от 0 до 1"
        
        return True, None

    @staticmethod
    def validate_color(color: Any, label: str) -> Tuple[bool, Optional[str]]:
        if not isinstance(color, (list, tuple)) or len(color) != 4:
            return False, f"{label} должен быть списком из 4 значений [R, G, B, A]"
        for component in color:
            if not isinstance(component, (int, float)) or component < 0 or component > 1:
                return False, f"Компоненты {label.lower()} должны быть числами от 0 до 1"
        return True, None
    
    @staticmethod
    def validate_handle(params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Валидация параметров ручки.
        
        Args:
            params: Параметры перегородки
            
        Returns:
            (valid, error_message): Кортеж с результатом валидации
        """
        if params.get('add_handle', False):
            position = params.get('handle_position')
            style = params.get('handle_style')
            sections = params.get('handle_sections')
            wall = params.get('handle_wall')
            
            if position not in ['Лево', 'Право', 'Центр']:
                return False, "Недопустимая позиция ручки. Допустимые: Лево, Право, Центр"
            
            if style not in ['Современный', 'Классический']:
                return False, "Недопустимый стиль ручки. Допустимые: Современный, Классический"

            if wall is not None and wall not in ['front', 'side', 'left', 'right', 'main']:
                return False, "Недопустимая стенка для ручки. Допустимые: передняя, боковая, левая, правая"

            if sections is not None:
                if not isinstance(sections, (list, tuple)):
                    return False, "Секции ручек должны быть списком номеров"
                for idx in sections:
                    if not isinstance(idx, int) or idx < 1:
                        return False, "Номера секций для ручки должны быть целыми числами от 1"

        door_sections = params.get('door_sections')
        door_wall = params.get('door_wall')
        if door_wall is not None and door_wall not in ['front', 'side', 'left', 'right', 'main']:
            return False, "Недопустимая стенка для дверей. Допустимые: передняя, боковая, левая, правая"
        if door_sections is not None:
            if not isinstance(door_sections, (list, tuple)):
                return False, "Секции дверей должны быть списком номеров"
            for idx in door_sections:
                if not isinstance(idx, int) or idx < 1:
                    return False, "Номера секций для дверей должны быть целыми числами от 1"
        
        return True, None
    
    @classmethod
    def validate_all(cls, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Полная валидация всех параметров.
        
        Args:
            params: Словарь с параметрами перегородки
            
        Returns:
            (valid, errors): Кортеж с результатом и списком ошибок
        """
        errors = []
        
        # Валидация формы
        valid, error = cls.validate_shape(params.get('shape', ''))
        if not valid:
            errors.append(error)
        
        # Валидация размеров
        valid, error = cls.validate_dimensions(params)
        if not valid:
            errors.append(error)
        
        # Валидация секций
        rows = params.get('rows', 0)
        cols = params.get('cols', 0)
        if any([
            params.get('vertical_mullions'),
            params.get('horizontal_mullions'),
            params.get('vertical_mullions_front'),
            params.get('vertical_mullions_side'),
            params.get('vertical_mullions_left'),
            params.get('vertical_mullions_right'),
            params.get('vertical_mullions_main'),
            params.get('horizontal_mullions_front'),
            params.get('horizontal_mullions_side'),
            params.get('horizontal_mullions_left'),
            params.get('horizontal_mullions_right'),
            params.get('horizontal_mullions_main'),
        ]):
            if rows in (None, 0):
                rows = 1
            if cols in (None, 0):
                cols = 1
        valid, error = cls.validate_sections(rows, cols)
        if not valid:
            errors.append(error)
        
        # Валидация толщины рамы
        thickness = params.get('frame_thickness')
        valid, error = cls.validate_frame_thickness(thickness)
        if not valid:
            errors.append(error)
        
        # Валидация материалов
        frame_color = params.get('frame_color')
        glass_color = params.get('glass_color')
        frame_color_id = params.get('frame_color_id')
        glass_type_id = params.get('glass_type_id')

        if frame_color is not None:
            valid, error = cls.validate_color(frame_color, 'Цвет рамы')
            if not valid:
                errors.append(error)
        elif frame_color_id is not None:
            if not config.get_material('frame_colors', str(frame_color_id)):
                errors.append("Недопустимый ID цвета рамы")
        else:
            errors.append("Не указан цвет рамы")

        if glass_color is not None:
            valid, error = cls.validate_color(glass_color, 'Цвет стекла')
            if not valid:
                errors.append(error)
        elif glass_type_id is not None:
            if not config.get_material('glass_types', str(glass_type_id)):
                errors.append("Недопустимый ID типа стекла")
        else:
            errors.append("Не указан тип стекла")
        
        # Валидация ручки
        valid, error = cls.validate_handle(params)
        if not valid:
            errors.append(error)
        
        if errors:
            logger.warning(f"Валидация не пройдена. Ошибки: {errors}")
            return False, errors
        
        logger.info("Валидация параметров успешно пройдена")
        return True, []


def validate_partition_params(params: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Удобная функция для валидации параметров перегородки.
    
    Args:
        params: Словарь с параметрами
        
    Returns:
        (valid, errors): Результат валидации
    """
    return PartitionValidator.validate_all(params)
