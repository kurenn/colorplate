"""PlatePipeline end-to-end: SVG -> per-color STLs + backing + preview +
manifest, all watertight and gap-free.
"""
from __future__ import annotations

import json
import os

import trimesh

from colorplate.config import Color, PlateConfig
from colorplate.pipeline import PlatePipeline

_PALETTE = [
    Color.from_hex("c0", "#231F1D"),
    Color.from_hex("c1", "#F9CF26"),
    Color.from_hex("c2", "#ED4324"),
    Color.from_hex("c3", "#F4F4F4"),
]


def test_pipeline_svg_end_to_end(sample_svg_path, tmp_path):
    cfg = PlateConfig(size_mm=120, front_mm=1.0, back_mm=2.0,
                      backing_color="c0", raster_px=600, palette=_PALETTE)
    res = PlatePipeline(cfg).run(sample_svg_path, str(tmp_path))

    # a backing plate plus at least a couple of color shells
    assert "backing" in res.files
    assert len([n for n in res.files if n != "backing"]) >= 2
    assert res.gap_px == 0

    # every exported STL exists and is a watertight solid
    for path in res.files.values():
        assert os.path.exists(path)
        mesh = trimesh.load(path)
        assert mesh.is_watertight
        assert mesh.volume > 0

    # backing sits behind the front shell (z starts at front_mm)
    backing = trimesh.load(res.files["backing"])
    assert backing.bounds[0][2] >= cfg.front_mm - 1e-6

    # manifest is valid and self-consistent
    man = json.load(open(res.manifest))
    assert man["size_mm"] == 120 and man["front_mm"] == 1.0 and man["back_mm"] == 2.0
    assert man["backing"] is not None
    assert {c["stl"] for c in man["colors"]} <= {os.path.basename(p) for p in res.files.values()}
    assert os.path.exists(res.preview)


def test_pipeline_no_backing_when_unset(sample_svg_path, tmp_path):
    cfg = PlateConfig(size_mm=100, backing_color=None, raster_px=500, palette=_PALETTE)
    res = PlatePipeline(cfg).run(sample_svg_path, str(tmp_path))
    assert "backing" not in res.files
    assert json.load(open(res.manifest))["backing"] is None
