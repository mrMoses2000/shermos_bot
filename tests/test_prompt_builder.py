from src.llm.prompt_builder import _missing_params_section, _slots_section, build_prompt


def test_missing_params_section_lists_required_fields():
    section = _missing_params_section({"collected_params": {"shape": "П-образная", "height": 2.5}})

    assert "Ширина B" in section
    assert "Ширина C" in section


def test_missing_params_section_when_complete():
    section = _missing_params_section(
        {
            "collected_params": {
                "shape": "Прямая",
                "height": 2.5,
                "width_a": 3,
                "glass_type": "1",
                "frame_color": "1",
                "rows": 1,
                "cols": 2,
            }
        }
    )

    assert "ВСЕ ОБЯЗАТЕЛЬНЫЕ ПАРАМЕТРЫ" in section


def test_build_prompt_includes_context_and_contract():
    prompt = build_prompt(
        "хочу перегородку",
        {"name": "Иван", "phone": "+1", "address": "Адрес"},
        {"mode": "collecting", "step": "ask_dimensions", "collected_params": {"shape": "Прямая"}},
        [{"role": "user", "text": "привет"}, {"role": "assistant", "text": "Здравствуйте"}],
    )

    assert "Иван" in prompt
    assert "ask_dimensions" in prompt
    assert "render_partition" in prompt
    assert "хочу перегородку" in prompt


def test_slots_section_with_data():
    section = _slots_section({"2026-04-15": ["10:00", "10:30"], "2026-04-16": []})

    assert "Свободное время" in section
    assert "2026-04-15: 10:00, 10:30" in section
    assert "2026-04-16: всё занято" in section


def test_slots_section_empty():
    section = _slots_section(None)

    assert "Данные о слотах не загружены" in section


def test_build_prompt_includes_slots():
    prompt = build_prompt(
        "хочу замер",
        None,
        None,
        [],
        available_slots={"2026-04-15": ["12:00"]},
    )

    assert "ДОСТУПНЫЕ СЛОТЫ ДЛЯ ЗАМЕРА" in prompt
    assert "2026-04-15: 12:00" in prompt
