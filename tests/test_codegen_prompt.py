"""Tests for src/utils/codegen_prompt.build_codegen_prompt."""

from __future__ import annotations

import json

from src.utils.codegen_prompt import build_codegen_prompt


def test_prompt_contains_task_id_and_material_id():
    task = {
        "id": 42,
        "kind": "add_material",
        "material_id": "glass_ab12cd34",
        "spec": {"material_kind": "glass", "name": "Бронзовое затемнённое 6мм"},
        "actor_phone": "+77005766841",
    }
    prompt = build_codegen_prompt(task)
    assert "Codegen task #42" in prompt
    assert "glass_ab12cd34" in prompt
    assert "Бронзовое" in prompt
    # Должны упомянуть конкретные файлы
    assert "config/app_config.json" in prompt
    assert "src/llm/prompt_builder.py" in prompt


def test_prompt_distinguishes_add_vs_remove():
    add = build_codegen_prompt({"id": 1, "kind": "add_material", "material_id": "x", "spec": {}})
    rem = build_codegen_prompt({"id": 2, "kind": "remove_material", "material_id": "x", "spec": {}})
    assert "Добавить" in add
    assert "Убрать" in rem


def test_prompt_handles_string_spec():
    """spec may arrive as JSON string from sqlite/asyncpg row roundtrip."""
    task = {
        "id": 7,
        "kind": "add_material",
        "material_id": "frame_x",
        "spec": json.dumps({"material_kind": "frame", "name": "Test"}),
    }
    prompt = build_codegen_prompt(task)
    assert "frame_x" in prompt
    assert '"material_kind": "frame"' in prompt


def test_prompt_includes_close_instructions():
    """The closing paragraph tells the dev session how to mark the task merged."""
    prompt = build_codegen_prompt(
        {"id": 99, "kind": "add_material", "material_id": "g", "spec": {}}
    )
    assert "Closes codegen task #99" in prompt
    assert "/api/pricing/codegen/tasks/99/resolve" in prompt
