"""service.generate: build per-filament STLs (+ backing), preview, manifest, zip
from a detection session — the web GUI's "Generate" step.
"""
from __future__ import annotations

import os
import zipfile

from colorplate.web import service


def test_generate_produces_stls_and_zip(sample_session):
    session, _ = sample_session
    regions = service._regions_payload(session)
    assignments = [{"name": r["filament"]["name"], "hex": r["filament"]["hex"]} for r in regions]

    res = service.generate(
        session, assignments,
        size_mm=120, front_mm=1.0, back_mm=2.0, backing_hex=assignments[0]["hex"],
    )

    assert res["coverageGap"] == 0
    names = [f["name"] for f in res["files"]]
    assert any(n.endswith("_backing.stl") for n in names)
    assert any(n.endswith(".stl") and not n.endswith("_backing.stl") for n in names)

    zpath = os.path.join(session.out_dir, res["zip"])
    assert os.path.exists(zpath)
    with zipfile.ZipFile(zpath) as zf:
        members = zf.namelist()
    assert any(m.endswith("_manifest.json") for m in members)
    assert any(m.endswith("_preview.png") for m in members)
    assert any(m.endswith(".stl") for m in members)


def test_generate_merges_regions_sharing_a_filament(sample_session):
    """Two regions assigned the same filament collapse into one STL."""
    session, _ = sample_session
    regions = service._regions_payload(session)
    same = regions[0]["filament"]
    assignments = [{"name": same["name"], "hex": same["hex"]} for _ in regions]

    res = service.generate(
        session, assignments,
        size_mm=100, front_mm=1.0, back_mm=2.0, backing_hex=None,
    )
    color_stls = [f for f in res["files"] if not f["name"].endswith("_backing.stl")]
    assert len(color_stls) == 1            # all regions share one filament -> one file
