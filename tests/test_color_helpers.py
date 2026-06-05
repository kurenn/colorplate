"""Color math + naming helpers (service.py) and config.Color.

These mirror the front-end spec and feed filename slugs / nearest-filament
matching, so they're worth pinning down exactly.
"""
from __future__ import annotations

from colorplate.config import Color
from colorplate.web import service


def test_hex_to_rgb_full_and_shorthand():
    assert service.hex_to_rgb("#FF8800") == (255, 136, 0)
    assert service.hex_to_rgb("#f80") == (255, 136, 0)
    assert service.hex_to_rgb("231F1D") == (35, 31, 29)


def test_rgb_to_hex_roundtrip():
    assert service.rgb_to_hex((255, 136, 0)) == "#FF8800"
    assert service.rgb_to_hex(service.hex_to_rgb("#ED4324")) == "#ED4324"


def test_color_dist_zero_for_identical_and_positive_otherwise():
    assert service.color_dist("#000000", "#000000") == 0
    assert service.color_dist("#000000", "#FFFFFF") > 0
    # closer colors are nearer than far ones
    near = service.color_dist("#F9CF26", "#F8CE28")
    far = service.color_dist("#F9CF26", "#231F1D")
    assert near < far


def test_nearest_preset_exact_and_approx():
    assert service.nearest_preset("#F9CF26")["name"] == "Gold"
    assert service.nearest_preset("#F8CE28")["name"] == "Gold"     # near-gold
    assert service.nearest_preset("#101113")["name"] == "Black"    # near-black


def test_slug():
    assert service.slug("Orange-Red") == "orange_red"
    assert service.slug("  A  B  ") == "a_b"
    assert service.slug("Gold") == "gold"


def test_filament_slug_custom_uses_hex():
    assert service._filament_slug({"name": "Custom", "hex": "#AABBCC"}) == "aabbcc"
    assert service._filament_slug({"name": "Orange-Red", "hex": "#ED4324"}) == "orange_red"


def test_config_color_from_hex():
    c = Color.from_hex("dark", "#231F1D")
    assert c.name == "dark"
    assert c.rgb == (35, 31, 29)
