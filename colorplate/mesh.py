"""Mesh construction.

Responsibility: convert a boolean pixel mask into a watertight extruded mesh,
correctly handling interior holes (e.g. the hollow centers of eyes), at a given
thickness and Z offset, scaled from source pixels to millimeters.
"""
from __future__ import annotations

import cv2
import numpy as np
import trimesh
from shapely.geometry import Polygon
from shapely.ops import unary_union


class MeshBuilder:
    def __init__(self, scale: float, simplify_px: float = 1.0, min_area_mm2: float = 0.3):
        self._scale = scale            # mm per source pixel
        self._simplify = simplify_px
        self._min_area = min_area_mm2
        self._img_h: int | None = None

    def build(self, mask: np.ndarray, thickness: float, z_offset: float = 0.0):
        """Return a trimesh for the mask, or None if it has no printable area."""
        self._img_h = mask.shape[0]
        polys = self._mask_to_polygons(mask)
        if not polys:
            return None
        geom = unary_union(polys)
        parts = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)

        meshes = []
        for pg in parts:
            if pg.area < self._min_area:
                continue
            m = trimesh.creation.extrude_polygon(pg, height=thickness)
            if z_offset:
                m.apply_translation([0, 0, z_offset])
            meshes.append(m)
        return trimesh.util.concatenate(meshes) if meshes else None

    def _mask_to_polygons(self, mask: np.ndarray) -> list[Polygon]:
        m = (mask * 255).astype("uint8")
        cnts, hier = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if hier is None:
            return []
        hier = hier[0]
        outers = {i: [] for i in range(len(cnts)) if hier[i][3] == -1}
        for i in range(len(cnts)):
            if hier[i][3] != -1:
                parent = hier[i][3]
                while parent != -1 and parent not in outers:
                    parent = hier[parent][3]
                if parent in outers:
                    outers[parent].append(i)

        polys: list[Polygon] = []
        for oi, holes in outers.items():
            ext = self._contour_xy(cnts[oi])
            if len(ext) < 3:
                continue
            hole_rings = []
            for hi in holes:
                h = self._contour_xy(cnts[hi])
                if len(h) >= 3:
                    hole_rings.append(h)
            try:
                pg = Polygon(ext, hole_rings).buffer(0)
                if not pg.is_empty:
                    polys.append(pg)
            except Exception:
                continue
        return polys

    def _contour_xy(self, contour) -> list[tuple[float, float]]:
        pts = cv2.approxPolyDP(contour, self._simplify, True).reshape(-1, 2)
        s, h = self._scale, self._img_h
        # flip Y so the mesh is right-way-up relative to the image
        return [(float(x) * s, float(h - y) * s) for x, y in pts]
