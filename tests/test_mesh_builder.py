"""MeshBuilder: boolean mask -> watertight extruded solid, in mm.

Asserts watertightness, the Z extent (z_offset .. z_offset+thickness), and that
interior holes (e.g. the hollow center of an eye) are preserved.
"""
from __future__ import annotations

import numpy as np
import pytest

from colorplate.mesh import MeshBuilder


def test_build_square_is_watertight_solid():
    mask = np.zeros((100, 100), bool)
    mask[20:80, 20:80] = True               # 60px square
    mesh = MeshBuilder(scale=0.5).build(mask, thickness=2.0)
    assert mesh is not None
    assert mesh.is_watertight
    assert mesh.volume > 0
    # ~30mm x 30mm x 2mm (contour rides pixel centers, so allow slack)
    assert mesh.volume == pytest.approx(30 * 30 * 2, rel=0.1)
    lo, hi = mesh.bounds
    assert lo[2] == pytest.approx(0.0)
    assert hi[2] == pytest.approx(2.0)


def test_build_preserves_holes():
    mask = np.zeros((120, 120), bool)
    mask[20:100, 20:100] = True             # 80px outer
    mask[50:70, 50:70] = False              # 20px hole
    mesh = MeshBuilder(scale=1.0).build(mask, thickness=1.0)
    assert mesh.is_watertight
    # volume = (outer - hole) * thickness
    assert mesh.volume == pytest.approx((80 * 80 - 20 * 20) * 1.0, rel=0.1)


def test_build_applies_z_offset():
    mask = np.zeros((40, 40), bool)
    mask[5:35, 5:35] = True
    mesh = MeshBuilder(scale=1.0).build(mask, thickness=2.0, z_offset=3.0)
    lo, hi = mesh.bounds
    assert lo[2] == pytest.approx(3.0)
    assert hi[2] == pytest.approx(5.0)


def test_build_empty_mask_returns_none():
    assert MeshBuilder(scale=1.0).build(np.zeros((10, 10), bool), thickness=1.0) is None


def test_build_drops_subthreshold_speckle():
    # a single stray pixel is below min_area_mm2 and should be dropped -> None
    mask = np.zeros((50, 50), bool)
    mask[10, 10] = True
    mesh = MeshBuilder(scale=0.1, min_area_mm2=0.3).build(mask, thickness=1.0)
    assert mesh is None
