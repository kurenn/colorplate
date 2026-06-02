"""Color classification.

Responsibility: given a Raster and a palette, assign every silhouette pixel to
exactly one color. Because the assignment is total over the silhouette, the
resulting per-color masks tile the surface with no gaps and no overlaps -- which
is exactly what a multicolor plate needs.

If no palette is supplied, one is discovered by k-means quantization.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import Color
from .raster import Raster


@dataclass
class ClassifiedRegions:
    masks: dict[str, np.ndarray]   # color name -> (H, W) bool
    palette: list[Color]
    silhouette: np.ndarray

    def coverage_gap(self) -> int:
        covered = np.zeros_like(self.silhouette)
        for m in self.masks.values():
            covered |= m
        return int((self.silhouette & ~covered).sum())


class Classifier:
    def __init__(self, palette: list[Color] | None = None, auto_colors: int = 4):
        self._palette = palette or []
        self._auto_colors = auto_colors

    def classify(self, raster: Raster) -> ClassifiedRegions:
        palette = self._palette or self._discover(raster)
        ref = np.array([c.rgb for c in palette])
        sil = raster.silhouette

        flat = raster.rgb.reshape(-1, 3)
        # nearest palette color for every pixel
        d = ((flat[:, None, :] - ref[None, :, :]) ** 2).sum(axis=2)
        label = d.argmin(axis=1).reshape(raster.height, raster.width)

        masks = {}
        for i, c in enumerate(palette):
            m = (label == i) & sil
            if m.any():
                masks[c.name] = m
        return ClassifiedRegions(masks=masks, palette=palette, silhouette=sil)

    def _discover(self, raster: Raster) -> list[Color]:
        from sklearn.cluster import KMeans  # optional dep, only for auto mode
        pts = raster.rgb[raster.silhouette].astype(float)
        k = min(self._auto_colors, max(1, len(np.unique(pts, axis=0))))
        km = KMeans(n_clusters=k, n_init=4, random_state=0).fit(pts)
        centers = km.cluster_centers_.round().astype(int)
        return [Color(f"c{i}", tuple(int(v) for v in centers[i])) for i in range(len(centers))]
