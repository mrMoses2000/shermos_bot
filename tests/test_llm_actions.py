from src.llm.actions_parser import parse_actions


def test_parse_actions_from_fenced_json():
    parsed = parse_actions(
        """```json
        {
          "reply_text": "Готово",
          "actions": {
            "render_partition": {
              "shape": "Прямая",
              "height": 2.7,
              "width_a": 3.0,
              "glass_type": "1",
              "frame_color": "1"
            }
          }
        }
        ```"""
    )

    assert parsed.reply_text == "Готово"
    assert parsed.actions["render_partition"]["height"] == 2.7


def test_parse_actions_fallback_on_invalid_json():
    parsed = parse_actions("not-json")

    assert parsed.reply_text == "Ошибка, попробуйте снова"
    assert parsed.actions is None
