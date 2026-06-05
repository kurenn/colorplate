"""Color detection (`service._quantize`): the heart of "drop a logo, get its
colors". The key invariants are total coverage (every silhouette pixel is
labeled, background is -1) and dominant-first ordering.
"""
from __future__ import annotations

import numpy as np
import pytest

from colorplate.web import service


def _two_color():
    """100x100 frame: left half orange-red, right half charcoal, on a bg border."""
    rgb = np.full((100, 100, 3), 255, int)
    sil = np.zeros((100, 100), bool)
    rgb[10:90, 10:50] = (237, 67, 36)
    rgb[10:90, 50:90] = (33, 31, 29)
    sil[10:90, 10:90] = True
    return rgb, sil


def test_quantize_detects_distinct_regions():
    rgb, sil = _two_color()
    labels, detected, weights = service._quantize(rgb, sil, 4)
    assert len(detected) == 2
    # total coverage: every silhouette pixel labeled, background untouched
    assert (labels[sil] >= 0).all()
    assert (labels[~sil] == -1).all()
    # weights are area fractions, summing to 1, dominant region first
    assert sum(weights) == pytest.approx(1.0)
    assert weights == sorted(weights, reverse=True)


def test_quantize_respects_max_colors():
    rgb, sil = _two_color()
    labels, detected, _ = service._quantize(rgb, sil, 1)
    assert len(detected) == 1
    assert (labels[sil] == 0).all()       # everything folds into the one region


def test_quantize_dominant_first():
    # make the charcoal area clearly larger than the red sliver
    rgb = np.full((100, 100, 3), 255, int)
    sil = np.zeros((100, 100), bool)
    rgb[10:90, 10:80] = (33, 31, 29)      # big
    rgb[10:90, 80:90] = (237, 67, 36)     # small
    sil[10:90, 10:90] = True
    _, detected, weights = service._quantize(rgb, sil, 4)
    assert weights[0] > weights[1]
    assert service.color_dist(detected[0], "#231F1D") < service.color_dist(detected[0], "#ED4324")


def test_quantize_empty_silhouette():
    labels, detected, weights = service._quantize(
        np.zeros((10, 10, 3), int), np.zeros((10, 10), bool), 4
    )
    assert detected == [] and weights == []
    assert (labels == -1).all()
