"""Classifier: assign every silhouette pixel to exactly one palette color, so
the per-color masks tile the surface with no gaps and no overlaps.
"""
from __future__ import annotations

import numpy as np
import pytest

from colorplate.classify import Classifier
from colorplate.config import Color
from colorplate.raster import Raster


def _raster():
    rgb = np.full((50, 50, 3), 255, int)
    sil = np.ones((50, 50), bool)
    rgb[:, :25] = (237, 67, 36)     # orange-red
    rgb[:, 25:] = (33, 31, 29)      # charcoal
    return Raster(rgb=rgb, silhouette=sil, height=50, width=50)


def test_explicit_palette_tiles_without_gaps_or_overlap():
    palette = [Color("red", (237, 67, 36)), Color("dark", (33, 31, 29))]
    res = Classifier(palette=palette).classify(_raster())
    assert set(res.masks) == {"red", "dark"}
    assert res.coverage_gap() == 0
    # no pixel belongs to two colors
    overlap = res.masks["red"] & res.masks["dark"]
    assert not overlap.any()


def test_classify_only_covers_silhouette():
    r = _raster()
    r.silhouette[:, :10] = False        # carve a background strip
    res = Classifier(palette=[Color("red", (237, 67, 36)),
                              Color("dark", (33, 31, 29))]).classify(r)
    for m in res.masks.values():
        assert not (m & ~r.silhouette).any()


def test_auto_discovery_kmeans():
    pytest.importorskip("sklearn")                        # only with the [auto] extra
    res = Classifier(auto_colors=2).classify(_raster())
    assert len(res.palette) == 2
    assert res.coverage_gap() == 0
