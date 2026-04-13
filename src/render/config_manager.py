#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль для централизованного управления конфигурацией приложения.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional


class ConfigManager:
    """
    Менеджер конфигурации для централизованного доступа к настройкам.
    """
    
    _instance = None
    _config = None
    
    def __new__(cls):
        """Синглтон паттерн для единственного экземпляра конфигурации."""
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, config_path: str = 'config/app_config.json'):
        """
        Инициализация менеджера конфигурации.
        
        Args:
            config_path: Путь к файлу конфигурации
        """
        if ConfigManager._config is None:
            # Используем абсолютный путь относительно корня проекта
            if not Path(config_path).is_absolute():
                # Находим корневую директорию проекта
                current_file = Path(__file__).resolve()
                project_root = current_file.parent.parent
                self.config_path = project_root / config_path
            else:
                self.config_path = Path(config_path)
            self.reload()
    
    def reload(self):
        """Перезагрузка конфигурации из файла."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Файл конфигурации не найден: {self.config_path}")
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            ConfigManager._config = json.load(f)
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Получение значения из конфигурации по ключу.
        Поддерживает вложенные ключи через точку.
        
        Args:
            key: Ключ в формате 'section.subsection.value'
            default: Значение по умолчанию
            
        Returns:
            Значение из конфигурации или default
            
        Example:
            config.get('server.port', 8080)
            config.get('rendering.image_width')
        """
        keys = key.split('.')
        value = ConfigManager._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """
        Получение целой секции конфигурации.
        
        Args:
            section: Название секции
            
        Returns:
            Словарь с настройками секции
        """
        return ConfigManager._config.get(section, {})
    
    def get_constraint(self, constraint_type: str, field: str) -> Optional[float]:
        """
        Получение ограничений для валидации.
        
        Args:
            constraint_type: Тип ограничения ('min' или 'max')
            field: Поле для которого нужно ограничение
            
        Returns:
            Значение ограничения или None
        """
        constraints = self.get_section('constraints')
        if field in constraints:
            return constraints[field].get(constraint_type)
        return None
    
    def get_material(self, material_type: str, material_id: str) -> Optional[Dict[str, Any]]:
        """
        Получение информации о материале.
        
        Args:
            material_type: Тип материала ('frame_colors' или 'glass_types')
            material_id: ID материала
            
        Returns:
            Словарь с информацией о материале или None
        """
        materials = self.get_section('materials')
        if material_type in materials and material_id in materials[material_type]:
            return materials[material_type][material_id]
        return None
    
    def get_all_materials(self, material_type: str) -> Dict[str, Dict[str, Any]]:
        """
        Получение всех материалов определенного типа.
        
        Args:
            material_type: Тип материала ('frame_colors' или 'glass_types')
            
        Returns:
            Словарь со всеми материалами данного типа
        """
        materials = self.get_section('materials')
        return materials.get(material_type, {})
    
    def validate_constraint(self, field: str, value: float) -> bool:
        """
        Валидация значения согласно ограничениям из конфигурации.
        
        Args:
            field: Имя поля
            value: Значение для проверки
            
        Returns:
            True если значение валидно, False в противном случае
        """
        min_val = self.get_constraint('min', field)
        max_val = self.get_constraint('max', field)
        
        if min_val is not None and value < min_val:
            return False
        if max_val is not None and value > max_val:
            return False
        
        return True
    
    def save(self, config_dict: Dict[str, Any] = None):
        """
        Сохранение конфигурации в файл.
        
        Args:
            config_dict: Словарь с конфигурацией (если None, сохраняется текущая)
        """
        if config_dict is not None:
            ConfigManager._config = config_dict
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(ConfigManager._config, f, ensure_ascii=False, indent=2)


# Глобальный экземпляр конфигурации
config = ConfigManager()
