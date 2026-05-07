"""Build the prompt text master sends to Claude/Codex when CMS materials change.

The master is not a developer — they just want to add or remove a material
and have the codebase catch up. The CMS records what changed in the
`codegen_tasks` table; this helper turns one row into a self-contained
brief that Claude/Codex can act on without needing the conversation.

The prompt is intentionally explicit about which files matter and what
the acceptance gate is, because the spawned dev session has no shared
context with the CMS user.
"""

from __future__ import annotations

import json
from typing import Any

# Files the spawned dev session needs to touch when materials change.
# Kept here (not in the prompt body) so we can update the list as the
# codebase evolves without retraining the master.
_MATERIAL_TOUCH_LIST = [
    "config/app_config.json — секция `materials.frame_colors` или `materials.glass_types`: добавить/удалить запись с цветом и roughness, ID должен совпадать с `material_id`.",
    "src/db/postgres.py — функция `seed_default_materials`: убедиться, что при сидинге новый материал не перезатирает БД-запись (ON CONFLICT DO NOTHING).",
    "src/llm/prompt_builder.py и src/llm/manager_prompt_builder.py — обновить перечисления допустимых материалов в системных промтах.",
    "src/llm/tools_schema.py — обновить enum в JSON-schema для action `update_partition`.",
    "GEMINI.md и AGENTS.md — секции про материалы, чтобы документация совпадала с кодом.",
    "tests/test_render_requirements.py и tests/test_pricing.py — добавить кейсы с новым material_id.",
]


def _format_spec(spec: Any) -> str:
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except Exception:
            return spec
    return json.dumps(spec, ensure_ascii=False, indent=2)


def build_codegen_prompt(task: dict[str, Any]) -> str:
    """Render the prompt for a single codegen_tasks row."""
    kind = task.get("kind", "add_material")
    material_id = task.get("material_id") or "<unknown>"
    spec_json = _format_spec(task.get("spec") or {})
    actor = task.get("actor_phone") or "—"
    task_id = task.get("id")

    action_human = {
        "add_material": "Добавить материал в код",
        "remove_material": "Убрать материал из кода (мастер пометил `is_active=false`)",
        "restore_material": "Восстановить материал в коде (мастер вернул `is_active=true`)",
    }.get(kind, kind)

    touch_block = "\n".join(f"- {line}" for line in _MATERIAL_TOUCH_LIST)

    return f"""# Codegen task #{task_id}: {action_human}

## Контекст
- Мастер изменил БД через CMS Shermos. БД уже содержит финальное состояние; нужно только догнать код/конфиги.
- material_id в БД: `{material_id}`
- инициатор: {actor}
- task kind: `{kind}`

## Что мастер указал (spec из БД)
```json
{spec_json}
```

## Что обновить в коде
{touch_block}

## Acceptance критерии (gate перед коммитом)
1. `pytest -q` проходит без новых фейлов.
2. Существующие галерейные рендеры не сломались (точечно прогнать 1 кейс на каждом изменённом kind).
3. Системный промт LLM содержит новый material_id (для `add_material` / `restore_material`) или **не** содержит его (для `remove_material`).
4. `seed_default_materials` идемпотентна — повторный запуск не дублирует и не перезатирает CMS-записи.

## После мерджа
Открой PR с заголовком `chore(codegen): material {material_id}` и в его описании оставь строку:
```
Closes codegen task #{task_id}
```
Это нужно, чтобы CMS могла отметить задачу как `merged` через POST /api/pricing/codegen/tasks/{task_id}/resolve с `{{"status":"merged","commit_sha":"<SHA>"}}`.
"""
