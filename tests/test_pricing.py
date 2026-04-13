from src.engine.pricing_engine import calculate_price


def test_calculate_price_applies_modifiers_and_discount():
    price = calculate_price(
        shape="П-образная",
        height=2.5,
        width_a=2,
        width_b=2,
        width_c=1,
        glass_type="4",
        frame_color="5",
        rows=2,
        cols=3,
        add_handle=True,
    )

    assert price["currency"] == "USD"
    assert price["details"]["area_sq_m"] == 12.5
    assert price["details"]["glass_modifier"] == 1.15
    assert price["details"]["volume_discount"] > 0
    assert price["total_price"] > 0
