"""CLI: palette parsing and an end-to-end `main()` invocation."""
from __future__ import annotations

import os

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
