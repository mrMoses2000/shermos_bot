"""Configuration reader for render materials and constraints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


class ConfigManager:
    _instance: "ConfigManager | None" = None
    _config: dict[str, Any] | None = None

    def __new__(cls, *_args: Any, **_kwargs: Any) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_path: str = "config/app_config.json"):
        if ConfigManager._config is not None:
            return
        root = Path(__file__).resolve().parents[2]
        self.config_path = Path(config_path)
        if not self.config_path.is_absolute():
            self.config_path = root / self.config_path
        self.reload()

    def reload(self) -> None:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Файл конфигурации не найден: {self.config_path}")
        ConfigManager._config = json.loads(self.config_path.read_text(encoding="utf-8"))

    def get(self, key: str, default: Any = None) -> Any:
        value: Any = ConfigManager._config or {}
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    def get_section(self, section: str) -> dict[str, Any]:
        value = self.get(section, {})
        return value if isinstance(value, dict) else {}

    def get_constraint(self, constraint_type: str, field: str) -> Optional[float]:
        field_config = self.get(f"constraints.{field}", {})
        if not isinstance(field_config, dict):
            return None
        value = field_config.get(constraint_type)
        return float(value) if value is not None else None

    def validate_constraint(self, field: str, value: float) -> bool:
        min_value = self.get_constraint("min", field)
        max_value = self.get_constraint("max", field)
        if min_value is not None and value < min_value:
            return False
        if max_value is not None and value > max_value:
            return False
        return True

    def get_material(self, material_type: str, material_id: str) -> Optional[dict[str, Any]]:
        material = self.get(f"materials.{material_type}.{material_id}")
        return material if isinstance(material, dict) else None

    def get_all_materials(self, material_type: str) -> dict[str, dict[str, Any]]:
        materials = self.get(f"materials.{material_type}", {})
        return materials if isinstance(materials, dict) else {}

    def save(self, config_dict: dict[str, Any] | None = None) -> None:
        if config_dict is not None:
            ConfigManager._config = config_dict
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(ConfigManager._config or {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


config = ConfigManager()
