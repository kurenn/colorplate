"""RasterLoader: SVG/PNG -> RGB + silhouette, plus SVG palette discovery."""
from __future__ import annotations

from colorplate.raster import RasterLoader


def test_load_svg_silhouette(sample_svg_path):
    r = RasterLoader(raster_px=200).load(sample_svg_path)
    assert r.rgb.ndim == 3 and r.rgb.shape[2] == 3
    assert r.silhouette.dtype == bool
    assert r.silhouette.shape == r.rgb.shape[:2]
    # filled circle: lots of foreground, transparent corners
    assert r.silhouette.any()
    assert not r.silhouette[0, 0]
    assert r.silhouette[r.height // 2, r.width // 2]


def test_load_png_alpha_silhouette(sample_png_path):
    r = RasterLoader(raster_px=100).load(sample_png_path)
    assert r.silhouette.any()
    assert not r.silhouette[0, 0]               # transparent border
    assert r.silhouette[r.height // 2, r.width // 2]


def test_palette_from_svg_finds_fills(sample_svg_path):
    palette = RasterLoader.palette_from_svg(sample_svg_path)
    rgbs = {c.rgb for c in palette}
    # all four declared fills are discovered
    assert (35, 31, 29) in rgbs       # #231F1D
    assert (249, 207, 38) in rgbs     # #F9CF26
    assert (237, 67, 36) in rgbs      # #ED4324
    assert (244, 244, 244) in rgbs    # #F4F4F4
