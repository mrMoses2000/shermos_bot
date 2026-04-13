"""Parse and validate Gemini JSON action responses."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from src.models import (
    ActionsJson,
    RenderPartitionAction,
    ScheduleMeasurementAction,
    StatePatch,
    UpdateClientProfileAction,
)

FALLBACK = ActionsJson(reply_text="Ошибка, попробуйте снова", actions=None)


def _extract_fenced_json(raw_output: str) -> str | None:
    match = re.search(r"```(?:json)?\s*(.*?)```", raw_output, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _extract_first_object(raw_output: str) -> str | None:
    start = raw_output.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(raw_output)):
        char = raw_output[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return raw_output[start : index + 1]
    return None


def _loads(raw_output: str) -> dict[str, Any] | None:
    candidates = [raw_output.strip(), _extract_fenced_json(raw_output), _extract_first_object(raw_output)]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _validate_nested(actions: dict[str, Any] | None) -> dict[str, Any] | None:
    if not actions:
        return None
    cleaned = {key: value for key, value in actions.items() if value is not None}
    if "render_partition" in cleaned:
        cleaned["render_partition"] = RenderPartitionAction(**cleaned["render_partition"]).model_dump()
    if "schedule_measurement" in cleaned:
        cleaned["schedule_measurement"] = ScheduleMeasurementAction(
            **cleaned["schedule_measurement"]
        ).model_dump()
    if "update_client_profile" in cleaned:
        cleaned["update_client_profile"] = UpdateClientProfileAction(
            **cleaned["update_client_profile"]
        ).model_dump()
    if "state_patch" in cleaned:
        cleaned["state_patch"] = StatePatch(**cleaned["state_patch"]).model_dump()
    return cleaned or None


def parse_actions(raw_output: str) -> ActionsJson:
    payload = _loads(raw_output)
    if payload is None:
        return FALLBACK
    try:
        parsed = ActionsJson(**payload)
        parsed.actions = _validate_nested(parsed.actions)
        return parsed
    except (TypeError, ValueError, ValidationError):
        return FALLBACK
