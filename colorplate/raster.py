"""Loading and rasterizing source artwork.

Responsibility: turn an input path (SVG or raster) into a single RGBA numpy
array at a known resolution, plus a boolean silhouette mask (which pixels are
part of the design vs. background).
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy.ndimage import binary_fill_holes

from .config import Color


def fill_enclosed(silhouette: np.ndarray) -> np.ndarray:
    """Fill *enclosed* background ('holes') into the silhouette — e.g. the white
    interiors of letters that background detection excluded — so they become
    paintable regions. Background that touches the image border (the real
    outside) is left out."""
    return binary_fill_holes(silhouette)


@dataclass
class Raster:
    rgb: np.ndarray        # (H, W, 3) int
    silhouette: np.ndarray  # (H, W) bool
    height: int
    width: int


class RasterLoader:
    """Loads SVG/PNG into a normalized Raster."""

    SVG_EXT = (".svg",)

    def __init__(self, raster_px: int = 1600):
        self.raster_px = raster_px

    def load(self, path: str, *, fill_holes: bool = False) -> Raster:
        if path.lower().endswith(self.SVG_EXT):
            rgba = self._render_svg(path)
        else:
            rgba = self._load_raster(path)
        raster = self._to_raster(rgba)
        if fill_holes:
            raster.silhouette = fill_enclosed(raster.silhouette)
        return raster

    # -- SVG -------------------------------------------------------------
    def _render_svg(self, path: str) -> np.ndarray:
        import cairosvg
        png_bytes = cairosvg.svg2png(
            url=path,
            output_width=self.raster_px,
            output_height=self.raster_px,
        )  # transparent background -> alpha gives silhouette
        img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        return np.array(img)

    @staticmethod
    def palette_from_svg(path: str) -> list[Color]:
        """Best-effort palette discovery from an SVG's fill/stroke colors."""
        text = open(path, encoding="utf-8", errors="ignore").read()
        hexes: list[str] = []
        for m in re.finditer(r'(?:fill|stroke)\s*[:=]\s*"?(#[0-9a-fA-F]{6})"?', text):
            h = m.group(1).lower()
            if h not in hexes and h != "#000000" or hexes.count(h) == 0:
                if h not in hexes:
                    hexes.append(h)
        # de-dup while preserving order
        seen, ordered = set(), []
        for h in hexes:
            if h not in seen:
                seen.add(h)
                ordered.append(h)
        return [Color.from_hex(f"c{i}", h) for i, h in enumerate(ordered)]

    # -- raster ----------------------------------------------------------
    def _load_raster(self, path: str) -> np.ndarray:
        img = Image.open(path).convert("RGBA")
        # normalize long edge to raster_px
        w, h = img.size
        scale = self.raster_px / max(w, h)
        if scale != 1.0:
            img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
        return np.array(img)

    # -- shared ----------------------------------------------------------
    def _to_raster(self, rgba: np.ndarray) -> Raster:
        h, w = rgba.shape[:2]
        alpha = rgba[:, :, 3]
        rgb = rgba[:, :, :3].astype(int)
        if alpha.min() < 250:
            silhouette = alpha > 128
        else:
            # opaque raster: treat the most common corner color as background
            corners = np.array([rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]])
            bg = corners.mean(axis=0)
            dist = np.sqrt(((rgb - bg) ** 2).sum(axis=2))
            silhouette = dist > 40
        return Raster(rgb=rgb, silhouette=silhouette, height=h, width=w)
