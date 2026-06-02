"""Pipeline orchestration.

Wires the loader, classifier and mesh builder together into one call, and
writes the result: one STL per color (the front shell), an optional single-color
backing plate, a flat-color preview PNG, and a JSON manifest mapping each color
to its file (handy for assigning toolheads in the slicer).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np
from PIL import Image

from .classify import Classifier
from .config import PlateConfig
from .mesh import MeshBuilder
from .raster import RasterLoader


@dataclass
class PlateResult:
    files: dict[str, str]      # color name (or 'backing') -> stl path
    preview: str
    manifest: str
    gap_px: int


class PlatePipeline:
    def __init__(self, config: PlateConfig):
        self.cfg = config

    def run(self, input_path: str, out_dir: str) -> PlateResult:
        os.makedirs(out_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(input_path))[0]

        loader = RasterLoader(self.cfg.raster_px)
        raster = loader.load(input_path)

        palette = self.cfg.palette
        if not palette and input_path.lower().endswith(".svg"):
            palette = RasterLoader.palette_from_svg(input_path)
        classifier = Classifier(palette=palette, auto_colors=self.cfg.auto_colors)
        regions = classifier.classify(raster)

        scale = self._scale(raster)
        builder = MeshBuilder(scale, self.cfg.simplify_px, self.cfg.min_area_mm2)

        files: dict[str, str] = {}
        # front color shells, all sharing z 0..front_mm
        for name, mask in regions.masks.items():
            mesh = builder.build(mask, self.cfg.front_mm, z_offset=0.0)
            if mesh is None:
                continue
            path = os.path.join(out_dir, f"{stem}_{name}.stl")
            mesh.export(path)
            files[name] = path

        # single-color backing plate behind everything
        if self.cfg.backing_color:
            backing = builder.build(
                regions.silhouette, self.cfg.back_mm, z_offset=self.cfg.front_mm
            )
            if backing is not None:
                path = os.path.join(out_dir, f"{stem}_backing.stl")
                backing.export(path)
                files["backing"] = path

        preview = self._write_preview(regions, os.path.join(out_dir, f"{stem}_preview.png"))
        manifest = self._write_manifest(
            regions, files, os.path.join(out_dir, f"{stem}_manifest.json")
        )
        return PlateResult(files=files, preview=preview, manifest=manifest,
                           gap_px=regions.coverage_gap())

    def _scale(self, raster) -> float:
        ys, xs = np.where(raster.silhouette)
        span = max(xs.max() - xs.min(), ys.max() - ys.min())
        return self.cfg.size_mm / span

    def _write_preview(self, regions, path: str) -> str:
        h, w = regions.silhouette.shape
        out = np.full((h, w, 3), 205, np.uint8)
        lut = {c.name: c.rgb for c in regions.palette}
        for name, mask in regions.masks.items():
            out[mask] = lut[name]
        Image.fromarray(out).resize((512, 512)).save(path)
        return path

    def _write_manifest(self, regions, files, path: str) -> str:
        lut = {c.name: c.rgb for c in regions.palette}
        data = {
            "front_mm": self.cfg.front_mm,
            "back_mm": self.cfg.back_mm,
            "size_mm": self.cfg.size_mm,
            "backing_color": self.cfg.backing_color,
            "colors": [
                {"name": n, "rgb": lut.get(n), "stl": os.path.basename(files[n])}
                for n in files if n != "backing"
            ],
            "backing": os.path.basename(files["backing"]) if "backing" in files else None,
            "note": "Load all STLs together; they share an origin. Print face-down.",
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return path
