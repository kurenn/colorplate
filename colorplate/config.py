"""Configuration objects for the colorplate pipeline.

Everything tunable lives here so the rest of the code takes a typed config
object rather than a long argument list.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Color:
    """A named print color and its RGB value."""
    name: str
    rgb: tuple[int, int, int]

    @staticmethod
    def from_hex(name: str, hex_str: str) -> "Color":
        h = hex_str.lstrip("#")
        return Color(name, (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))


@dataclass
class PlateConfig:
    """Geometry + rendering settings for a single conversion."""

    # Output size: the longest in-plane dimension of the silhouette, in mm.
    size_mm: float = 180.0

    # Thickness of the visible, multicolor front shell (bed/show side), in mm.
    front_mm: float = 1.0

    # Thickness of the single-color backing plate behind the shell, in mm.
    back_mm: float = 2.0

    # Which color name to use for the backing. None => no backing plate.
    backing_color: str | None = None

    # Resolution the source is rasterized to (px on the long edge) before tracing.
    raster_px: int = 1600

    # Contour simplification tolerance in source pixels (higher = fewer vertices).
    simplify_px: float = 1.0

    # Drop traced islands smaller than this area (mm^2) to remove speckle.
    min_area_mm2: float = 0.3

    # Nozzle line width (mm) used by the printability check to flag features
    # that are too thin to print at the chosen size.
    nozzle_mm: float = 0.4

    # Explicit palette. If empty, the pipeline auto-discovers colors
    # (from SVG fills/strokes, or by quantization for rasters).
    palette: list[Color] = field(default_factory=list)

    # When auto-quantizing a raster with no known palette, target this many colors.
    auto_colors: int = 4
