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
from .printability import feature_report
from .raster import RasterLoader
from .stack import merge_terrace, snap, swap_bands


@dataclass
class PlateResult:
    files: dict[str, str]      # color name (or 'backing') -> stl path
    preview: str
    manifest: str
    gap_px: int
    printability: dict = None  # per-color thin-feature report


@dataclass
class StackResult:
    """Single-extruder export: one terraced STL + the filament-swap schedule."""
    stl: str
    swaps: str
    manifest: str
    preview: str
    bands: list[dict]
    total_mm: float
    printability: dict = None


def _rgb_to_hex(rgb) -> str:
    return "#%02X%02X%02X" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def _printability(regions, scale: float, cfg: PlateConfig) -> dict:
    rep = feature_report(list(regions.masks.items()), scale, cfg.nozzle_mm,
                         min_area_mm2=cfg.min_area_mm2, size_mm=cfg.size_mm)
    # name the offenders by color (CLI/manifest are keyed by palette name)
    return rep


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

        printability = _printability(regions, scale, self.cfg)
        preview = self._write_preview(regions, os.path.join(out_dir, f"{stem}_preview.png"))
        manifest = self._write_manifest(
            regions, files, os.path.join(out_dir, f"{stem}_manifest.json"), printability
        )
        return PlateResult(files=files, preview=preview, manifest=manifest,
                           gap_px=regions.coverage_gap(), printability=printability)

    def run_stack(self, input_path: str, out_dir: str, *, base_mm: float,
                  step_mm: float, layer_mm: float) -> StackResult:
        """Single-extruder build: one terraced STL where colors are stacked by
        height (base->top in palette order), plus a filament-swap schedule and a
        manifest. Print as one object on one nozzle, inserting an ``M600`` at
        each swap layer."""
        os.makedirs(out_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(input_path))[0]

        loader = RasterLoader(self.cfg.raster_px)
        raster = loader.load(input_path)
        palette = self.cfg.palette
        if not palette and input_path.lower().endswith(".svg"):
            palette = RasterLoader.palette_from_svg(input_path)
        regions = Classifier(palette=palette, auto_colors=self.cfg.auto_colors).classify(raster)

        base_mm, step_mm = snap(base_mm, layer_mm), snap(step_mm, layer_mm)
        builder = MeshBuilder(self._scale(raster), self.cfg.simplify_px, self.cfg.min_area_mm2)
        sil = regions.silhouette
        overlap = min(0.05, step_mm * 0.5)

        # base -> top in palette order, keeping only colors that actually appear
        ordered = [c for c in regions.palette if c.name in regions.masks]
        order_hex = [_rgb_to_hex(c.rgb) for c in ordered]
        nb = len(ordered)

        meshes = []
        for b in range(nb):
            foot = np.zeros_like(sil)
            for j in range(b, nb):                       # union of bands >= b
                foot |= regions.masks[ordered[j].name]
            if b == 0:
                z0, z1 = 0.0, base_mm
            else:
                z0, z1 = base_mm + (b - 1) * step_mm - overlap, base_mm + b * step_mm
            meshes.append(builder.build(foot, z1 - z0, z_offset=z0))
        solid = merge_terrace(meshes)
        if solid is None:
            raise ValueError("Nothing printable to export.")

        stl_path = os.path.join(out_dir, f"{stem}_stack.stl")
        solid.export(stl_path)

        bands = swap_bands(order_hex, base_mm, step_mm, layer_mm)
        name_by_hex = {h: ordered[i].name for i, h in enumerate(order_hex)}
        total = base_mm + (nb - 1) * step_mm

        swaps_path = os.path.join(out_dir, f"{stem}_swaps.txt")
        lines = [
            "ColorPlate — single-extruder filament-swap schedule",
            f"{stem}  ·  {self.cfg.size_mm:g}mm  ·  base {base_mm:g}mm  ·  "
            f"step {step_mm:g}mm  ·  layer {layer_mm:g}mm",
            f"Total height: {total:g}mm   ·   {max(0, nb - 1)} filament change(s)",
            "",
            f"Print {stem}_stack.stl as a single object. Insert M600 at each swap.",
            "",
        ]
        for band in bands:
            verb = "Start" if band["action"] == "start" else "Swap "
            lines.append("  %s  %-14s %-9s  layer %-4d  z %.2fmm" % (
                verb, name_by_hex[band["hex"]], "(" + band["hex"] + ")",
                band["layer"], band["z0"]))
        with open(swaps_path, "w") as fh:
            fh.write("\n".join(lines) + "\n")

        printability = _printability(regions, self._scale(raster), self.cfg)
        man_path = os.path.join(out_dir, f"{stem}_manifest.json")
        with open(man_path, "w") as fh:
            json.dump({
                "mode": "single-extruder",
                "size_mm": self.cfg.size_mm, "base_mm": base_mm, "step_mm": step_mm,
                "layer_mm": layer_mm, "total_mm": round(total, 2),
                "stl": os.path.basename(stl_path),
                "bands": [{"name": name_by_hex[b["hex"]], "hex": b["hex"],
                           "action": b["action"], "z_mm": b["z0"], "layer": b["layer"]}
                          for b in bands],
                "printability": printability,
                "note": "Single extruder: print the STL and insert an M600 at each swap layer.",
            }, fh, indent=2)

        preview = self._write_preview(regions, os.path.join(out_dir, f"{stem}_preview.png"))
        return StackResult(stl=stl_path, swaps=swaps_path, manifest=man_path,
                           preview=preview, bands=bands, total_mm=round(total, 2),
                           printability=printability)

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

    def _write_manifest(self, regions, files, path: str, printability=None) -> str:
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
            "printability": printability,
            "note": "Load all STLs together; they share an origin. Print face-down.",
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return path
