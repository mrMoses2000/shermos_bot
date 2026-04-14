from src.engine.pricing_engine import calculate_price


class LegacyCache:
    def get_base_rate(self, partition_type, glass_type):
        return 180.0

    def get_addon_price(self, addon_type):
        return 80.0 if addon_type == "handle" else 0.0

    def get_frame_modifier_pct(self):
        return 0.04

    def get_volume_discount(self):
        return 0.06, 8.0

    def is_frame_nonblack(self, frame_color):
        return str(frame_color) not in {"1", "3"}


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
        cache=LegacyCache(),
    )

    assert price["currency"] == "USD"
    assert price["details"]["area_sq_m"] == 12.5
    assert price["details"]["base_rate_per_sqm"] == 180.0
    assert price["details"]["frame_surcharge"] > 0
    assert price["details"]["volume_discount"] > 0
    assert price["total_price"] > 0
