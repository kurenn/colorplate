"""CLI: palette parsing and an end-to-end `main()` invocation."""
from __future__ import annotations

import os

import pytest

from colorplate import cli


def test_parse_palette_named():
    pal = cli._parse_palette("red=#ED4324, dark=#231F1D")
    assert [c.name for c in pal] == ["red", "dark"]
    assert pal[0].rgb == (237, 67, 36)
    assert pal[1].rgb == (35, 31, 29)


def test_parse_palette_auto_names_and_skips_blanks():
    pal = cli._parse_palette("#ED4324,,#231F1D")
    assert [c.name for c in pal] == ["c0", "c2"]   # index follows position; blank skipped


def test_cli_main_writes_outputs(sample_svg_path, tmp_path, capsys):
    rc = cli.main([
        sample_svg_path, "-o", str(tmp_path),
        "--height", "100", "--raster-px", "600",
        "--palette", "c0=#231F1D,c1=#F9CF26,c2=#ED4324,c3=#F4F4F4",
        "--backing-color", "c0",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "STL" in out and "Coverage: 100%" in out

    files = os.listdir(tmp_path)
    assert any(f.endswith("_backing.stl") for f in files)
    assert any(f.endswith("_manifest.json") for f in files)
    assert any(f.endswith("_preview.png") for f in files)


def test_cli_single_extruder(sample_svg_path, tmp_path, capsys):
    import json

    import trimesh

    rc = cli.main([
        sample_svg_path, "-o", str(tmp_path),
        "--height", "100", "--raster-px", "600",
        "--palette", "dark=#231F1D,gold=#F9CF26,red=#ED4324,white=#F4F4F4",
        "--single-extruder", "--base", "0.8", "--step", "0.6", "--layer-height", "0.2",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "terraced STL" in out and "M600" in out

    files = os.listdir(tmp_path)
    stl = next(f for f in files if f.endswith("_stack.stl"))
    assert any(f.endswith("_swaps.txt") for f in files)
    # one watertight terraced solid spanning 0..base+3*step
    mesh = trimesh.load(os.path.join(tmp_path, stl))
    assert mesh.is_watertight
    assert mesh.bounds[1][2] == pytest.approx(2.6, abs=1e-2)
    man = json.load(open(os.path.join(tmp_path, stl.replace("_stack.stl", "_manifest.json"))))
    assert man["mode"] == "single-extruder"
    assert len(man["bands"]) == 4
