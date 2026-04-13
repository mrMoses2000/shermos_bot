from src.llm.prompt_builder import _missing_params_section, build_prompt


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
