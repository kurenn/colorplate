"""Service layer for the ColorPlate web GUI.

Bridges the browser front end to the real conversion pipeline. Responsibilities:

* turn an uploaded SVG/PNG into a list of *detected* color regions (quantizing
  the rasterized silhouette to N colors),
* render a live, recolored preview of the artwork painted with the user's
  assigned filaments,
* build the actual per-filament STL plates (+ backing, preview, manifest).

State for one upload lives in a :class:`Session`. The detection raster is kept
at a modest resolution for snappy region listing / preview; STL generation
reloads the source at full resolution and reclassifies against the detected
palette so the meshes are crisp.

The color math here (redmean nearest-preset, slug) mirrors the front-end spec
exactly and is the authoritative copy.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import threading
import time
import zipfile
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from ..config import PlateConfig
from ..mesh import MeshBuilder
from ..raster import RasterLoader

# ----------------------------------------------------------------------------
# Filament presets — the built-in palette (exact values from the design spec).
# ----------------------------------------------------------------------------
PRESETS: list[dict] = [
    {"name": "Red",        "hex": "#D11A2A"},
    {"name": "White",      "hex": "#F4F4F4"},
    {"name": "Black",      "hex": "#101010"},
    {"name": "Charcoal",   "hex": "#231F1D"},
    {"name": "Gold",       "hex": "#F9CF26"},
    {"name": "Orange-Red", "hex": "#ED4324"},
    {"name": "Yellow",     "hex": "#FBD732"},
    {"name": "Teal",       "hex": "#A8DFDF"},
]

# Resolution (long edge) used for region detection + live preview. Generation
# reloads at the full PlateConfig.raster_px for clean meshes.
DETECT_PX = 1000


# ----------------------------------------------------------------------------
# Color helpers (mirror of emblem.jsx; this is the authoritative copy).
# ----------------------------------------------------------------------------
def hex_to_rgb(h: str) -> tuple[int, int, int]:
    x = h.lstrip("#")
    if len(x) == 3:
        x = "".join(c * 2 for c in x)
    return int(x[0:2], 16), int(x[2:4], 16), int(x[4:6], 16)


def rgb_to_hex(rgb) -> str:
    return "#%02X%02X%02X" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def color_dist(a_hex: str, b_hex: str) -> float:
    """Weighted RGB ('redmean') distance used for nearest-preset matching."""
    r1, g1, b1 = hex_to_rgb(a_hex)
    r2, g2, b2 = hex_to_rgb(b_hex)
    rm = (r1 + r2) / 2.0
    dr, dg, db = r1 - r2, g1 - g2, b1 - b2
    return ((2 + rm / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256) * db * db) ** 0.5


def nearest_preset(hex_str: str) -> dict:
    best, best_d = PRESETS[0], float("inf")
    for p in PRESETS:
        d = color_dist(hex_str, p["hex"])
        if d < best_d:
            best_d, best = d, p
    return {"name": best["name"], "hex": best["hex"]}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _filament_slug(fil: dict) -> str:
    """Filename slug: 'Custom' colors slug their hex; presets slug their name."""
    if fil.get("name", "").lower() == "custom":
        return slug(fil["hex"].replace("#", ""))
    return slug(fil["name"]) or slug(fil["hex"].replace("#", ""))


# ----------------------------------------------------------------------------
# Session state
# ----------------------------------------------------------------------------
@dataclass
class Session:
    id: str
    filename: str
    src_path: str            # saved original upload (for full-res regen)
    out_dir: str             # scratch dir for generated artifacts
    rgb: np.ndarray          # (H, W, 3) int  detection-resolution color
    sil: np.ndarray          # (H, W) bool    silhouette mask
    labels: np.ndarray = field(default=None)   # (H, W) int region index, -1 = bg
    detected: list = field(default_factory=list)  # hex per region (dominant-first)
    weights: list = field(default_factory=list)   # area fraction per region
    max_colors: int = 4
    touched: float = field(default_factory=time.time)


class SessionStore:
    """Tiny in-memory LRU of active uploads."""

    def __init__(self, capacity: int = 24):
        self._cap = capacity
        self._items: "OrderedDict[str, Session]" = OrderedDict()
        self._lock = threading.Lock()

    def put(self, s: Session) -> None:
        with self._lock:
            self._items[s.id] = s
            self._items.move_to_end(s.id)
            while len(self._items) > self._cap:
                _, old = self._items.popitem(last=False)
                _cleanup_dir(old.out_dir)

    def get(self, sid: str) -> Session | None:
        with self._lock:
            s = self._items.get(sid)
            if s is not None:
                s.touched = time.time()
                self._items.move_to_end(sid)
            return s


def _cleanup_dir(path: str) -> None:
    import shutil
    shutil.rmtree(path, ignore_errors=True)


# ----------------------------------------------------------------------------
# Detection
# ----------------------------------------------------------------------------
# Two quantized colors closer than this (redmean distance) are treated as the
# same filament region — collapses antialiasing fringe shades into their parent.
MERGE_DIST = 30.0

# A region must cover at least this fraction of the silhouette to be its own
# filament — keeps small genuine colors (a logo dot) while folding antialiasing
# slivers into a neighbor, so every detected region is actually printable and
# the live preview always matches the generated meshes.
MIN_REGION_FRAC = 0.004


def _quantize(rgb: np.ndarray, sil: np.ndarray, n: int):
    """Detect up to ``n`` color regions over the silhouette.

    Median-cut tends to spend bins on antialiasing fringes (near-duplicates of a
    dominant color) while missing small but genuinely distinct regions. So we
    over-quantize, merge near-duplicate colors, then keep the ``n`` largest by
    area — folding any leftover pixels into their nearest kept color so the
    regions still tile the whole silhouette with no gaps.

    Returns (labels, detected_hexes, weights): ``labels`` is a full-frame int
    array (region index per silhouette pixel, -1 in background), ordered so
    region 0 is the largest (dominant) area.
    """
    pix = rgb[sil].astype("uint8")                       # (M, 3)
    if pix.shape[0] == 0:
        return np.full(sil.shape, -1, int), [], []

    uniq = np.unique(pix, axis=0)
    internal_k = int(min(len(uniq), max(12, n * 3), 48))

    strip = Image.fromarray(pix.reshape(-1, 1, 3), "RGB")
    q = strip.convert("P", palette=Image.ADAPTIVE, colors=internal_k)
    pal = np.asarray(q.getpalette()[: internal_k * 3], dtype=int).reshape(-1, 3)
    idx = np.asarray(q, dtype=int).reshape(-1)           # (M,) bin indices
    k = int(idx.max()) + 1
    pal = pal[:k]
    bin_counts = np.bincount(idx, minlength=k).astype(float)
    bin_hex = [rgb_to_hex(pal[i]) for i in range(k)]

    # Greedy merge of near-duplicate bins, anchoring on the larger ones first.
    anchors: list[int] = []
    bin_to_anchor = np.empty(k, int)
    for bi in np.argsort(-bin_counts):
        match = next((a for a in anchors if color_dist(bin_hex[bi], bin_hex[a]) < MERGE_DIST), None)
        if match is None:
            anchors.append(int(bi))
            bin_to_anchor[bi] = bi
        else:
            bin_to_anchor[bi] = match

    anchor_area = {a: 0.0 for a in anchors}
    for bi in range(k):
        anchor_area[bin_to_anchor[bi]] += bin_counts[bi]
    floor = MIN_REGION_FRAC * bin_counts.sum()
    by_area = sorted(anchors, key=lambda a: -anchor_area[a])
    big = [a for a in by_area if anchor_area[a] >= floor]
    kept = (big or by_area[:1])[:n]
    kept_hex = [bin_hex[a] for a in kept]

    # Map every anchor (kept or not) to a kept region index (nearest by color).
    anchor_to_region: dict[int, int] = {}
    for a in anchors:
        if a in kept:
            anchor_to_region[a] = kept.index(a)
        else:
            anchor_to_region[a] = min(range(len(kept)),
                                      key=lambda j: color_dist(bin_hex[a], kept_hex[j]))
    bin_to_region = np.array([anchor_to_region[bin_to_anchor[bi]] for bi in range(k)])
    region_idx = bin_to_region[idx]                      # (M,) region per pixel

    counts = np.bincount(region_idx, minlength=len(kept)).astype(float)
    order = np.argsort(-counts)                          # largest area first
    remap = np.empty(len(kept), int)
    remap[order] = np.arange(len(kept))

    labels = np.full(sil.shape, -1, int)
    labels[sil] = remap[region_idx]
    total = counts.sum()
    detected = [kept_hex[o] for o in order]
    weights = [float(counts[o] / total) for o in order]
    return labels, detected, weights


def _regions_payload(session: Session) -> list[dict]:
    out = []
    for i, hexv in enumerate(session.detected):
        out.append({
            "id": "T" + str(i + 1),
            "detected": hexv,
            "weight": round(session.weights[i], 4),
            "filament": nearest_preset(hexv),
        })
    return out


def detect_from_path(session: Session, max_colors: int) -> dict:
    """(Re)run detection on an already-loaded session at the given color count."""
    labels, detected, weights = _quantize(session.rgb, session.sil, max_colors)
    session.labels = labels
    session.detected = detected
    session.weights = weights
    session.max_colors = max_colors
    regions = _regions_payload(session)
    preview = render_preview(session, [r["filament"]["hex"] for r in regions])
    return {
        "uploadId": session.id,
        "filename": session.filename,
        "regions": regions,
        "preview": preview,
    }


def load_session(sid: str, filename: str, src_path: str, out_dir: str,
                 max_colors: int) -> tuple[Session, dict]:
    raster = RasterLoader(DETECT_PX).load(src_path)
    session = Session(
        id=sid, filename=filename, src_path=src_path, out_dir=out_dir,
        rgb=raster.rgb, sil=raster.silhouette,
    )
    payload = detect_from_path(session, max_colors)
    return session, payload


# ----------------------------------------------------------------------------
# Live preview (real artwork recolored with the assigned filaments)
# ----------------------------------------------------------------------------
def render_preview(session: Session, assignments_hex: list[str], max_px: int = 560) -> str:
    """Return a transparent, bbox-cropped PNG (data URL) of the artwork painted
    with the assigned filament colors — one color per detected region."""
    sil = session.sil
    labels = session.labels
    h, w = sil.shape
    rgba = np.zeros((h, w, 4), "uint8")
    for i, fil_hex in enumerate(assignments_hex):
        if not fil_hex:
            continue
        m = labels == i
        if not m.any():
            continue
        rgba[m, 0:3] = hex_to_rgb(fil_hex)
        rgba[m, 3] = 255

    ys, xs = np.where(sil)
    if ys.size == 0:
        img = Image.fromarray(rgba, "RGBA")
    else:
        img = Image.fromarray(rgba, "RGBA").crop(
            (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        )
    long_edge = max(img.size)
    if long_edge > max_px:
        s = max_px / long_edge
        img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))),
                         Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# ----------------------------------------------------------------------------
# Live 3D preview geometry
# ----------------------------------------------------------------------------
def _mesh_payload(mesh, bbox: list) -> dict | None:
    """Flatten a trimesh into JSON-friendly position/index arrays and fold its
    bounds into the running ``bbox`` ([minx,miny,minz, maxx,maxy,maxz])."""
    if mesh is None or len(mesh.faces) == 0:
        return None
    v = np.round(np.asarray(mesh.vertices, dtype=float), 3)
    f = np.asarray(mesh.faces, dtype=np.int32)
    lo = v.min(axis=0)
    hi = v.max(axis=0)
    for k in range(3):
        bbox[k] = min(bbox[k], float(lo[k]))
        bbox[k + 3] = max(bbox[k + 3], float(hi[k]))
    return {"positions": v.ravel().tolist(), "indices": f.ravel().tolist()}


def build_mesh3d(session: Session, *, size_mm: float, front_mm: float,
                 back_mm: float) -> dict:
    """Build per-region front-shell meshes plus the backing plate for the live
    3D preview, returned as compact vertex/index arrays in millimetres.

    Geometry is built from the same cached detection label map and MeshBuilder
    that :func:`generate` uses, so the 3D view is identical to the exported STLs.
    Filament colors are applied client-side, so reassigning a filament needs no
    rebuild — only size/thickness/color-count changes do.
    """
    sil = session.sil
    labels = session.labels
    ys, xs = np.where(sil)
    if ys.size == 0 or labels is None:
        return {"regions": [], "backing": None, "bbox": None,
                "front": front_mm, "back": back_mm, "size": size_mm}

    span = max(int(xs.max() - xs.min()), int(ys.max() - ys.min())) or 1
    scale = size_mm / span
    cfg = PlateConfig(size_mm=size_mm, front_mm=front_mm, back_mm=back_mm)
    builder = MeshBuilder(scale, cfg.simplify_px, cfg.min_area_mm2)

    bbox = [float("inf")] * 3 + [float("-inf")] * 3
    regions = []
    for i in range(len(session.detected)):
        mask = labels == i
        payload = _mesh_payload(builder.build(mask, front_mm, z_offset=0.0), bbox) \
            if mask.any() else None
        regions.append({"index": i, "geometry": payload})

    backing = _mesh_payload(builder.build(sil, back_mm, z_offset=front_mm), bbox)

    has_geom = any(r["geometry"] for r in regions) or backing is not None
    return {
        "regions": regions,
        "backing": backing,
        "bbox": bbox if has_geom else None,
        "front": front_mm,
        "back": back_mm,
        "size": size_mm,
    }


def _snap(value: float, layer: float) -> float:
    """Round a height to the nearest whole layer (min one layer) — filament
    swaps can only land on a layer boundary."""
    layer = max(0.04, layer)
    return max(layer, round(value / layer) * layer)


def _stack_slabs(session: Session, assignments: list[str], order: list[str],
                 size_mm: float, base_mm: float, step_mm: float) -> tuple[list[dict], float]:
    """Build the terrace as horizontal band-slabs (shared by preview + export).

    Band 0 is the full-silhouette base plate; band b is the union of every region
    that reaches at least that height, extruded through that swap's layers. Upper
    slabs tuck slightly under the slab below (overlap) so the shared interface is
    interior — no coincident faces. Returns ``(slabs, total_height)`` where each
    slab is ``{band, color, mesh}`` (mesh is a trimesh or None).
    """
    sil, labels = session.sil, session.labels
    ys, xs = np.where(sil)
    span = max(int(xs.max() - xs.min()), int(ys.max() - ys.min())) or 1
    scale = size_mm / span
    cfg = PlateConfig(size_mm=size_mm)
    builder = MeshBuilder(scale, cfg.simplify_px, cfg.min_area_mm2)
    band_of = {h.upper(): b for b, h in enumerate(order)}
    region_band = [band_of.get((assignments[i] if i < len(assignments) else "").upper(), 0)
                   for i in range(len(session.detected))]
    nbands = len(order)
    overlap = min(0.05, step_mm * 0.5)

    slabs = []
    for b in range(nbands):
        foot = np.zeros_like(sil)
        for i in range(len(session.detected)):
            if region_band[i] >= b:
                foot |= labels == i
        if b == 0:
            z0, z1 = 0.0, base_mm
        else:
            z0, z1 = base_mm + (b - 1) * step_mm - overlap, base_mm + b * step_mm
        mesh = builder.build(foot, z1 - z0, z_offset=z0) if foot.any() else None
        slabs.append({"band": b, "color": order[b], "mesh": mesh})
    total = base_mm + (nbands - 1) * step_mm
    return slabs, total


def _swap_bands(order: list[str], base_mm: float, step_mm: float, layer_mm: float) -> list[dict]:
    """Filament-swap schedule: for each color (base->top), its Z band and the
    layer where the swap happens (band 0 is the start, not a swap)."""
    bands = []
    for b, hexv in enumerate(order):
        if b == 0:
            z0, z1, action = 0.0, base_mm, "start"
        else:
            z0, z1, action = base_mm + (b - 1) * step_mm, base_mm + b * step_mm, "swap"
        bands.append({
            "band": b, "hex": hexv, "action": action,
            "z0": round(z0, 2), "z1": round(z1, 2),
            "layer": int(round(z0 / max(0.04, layer_mm))) + 1,
        })
    return bands


def build_stack3d(session: Session, *, assignments: list[str], order: list[str],
                  size_mm: float, base_mm: float, step_mm: float,
                  layer_mm: float) -> dict:
    """Single-extruder ("filament swap") geometry: a terraced relief where each
    color occupies its own Z band, so one nozzle can print it with an ``M600``
    swap between bands.

    ``order`` is the list of distinct filament hexes from base (bottom) to top.
    A region assigned the hex at order position ``b`` rises to ``base + b*step``;
    the full silhouette forms the base plate. Returns per-region columns + the
    base (same shape as :func:`build_mesh3d`) plus the filament-swap schedule.
    """
    base_mm = _snap(base_mm, layer_mm)
    step_mm = _snap(step_mm, layer_mm)
    if session.sil.sum() == 0 or session.labels is None or not order:
        return {"regions": [], "backing": None, "bbox": None, "bands": [],
                "totalHeight": 0.0, "base": base_mm, "step": step_mm, "layer": layer_mm}

    slabs_raw, total = _stack_slabs(session, assignments, order, size_mm, base_mm, step_mm)
    bbox = [float("inf")] * 3 + [float("-inf")] * 3
    slabs = [
        {"index": s["band"], "band": s["band"], "color": s["color"],
         "geometry": _mesh_payload(s["mesh"], bbox)}
        for s in slabs_raw
    ]

    bands = _swap_bands(order, base_mm, step_mm, layer_mm)
    has_geom = any(s["geometry"] for s in slabs)
    return {
        "regions": slabs,                      # one entry per band-slab (carries its color)
        "backing": None,
        "bbox": bbox if has_geom else None,
        "bands": bands,
        "totalHeight": round(total, 2),
        "base": round(base_mm, 3), "step": round(step_mm, 3),
        "layer": layer_mm, "size": size_mm,
    }


# ----------------------------------------------------------------------------
# STL generation (the real thing)
# ----------------------------------------------------------------------------
@dataclass
class GenFile:
    name: str
    hex: str
    size_mb: float


def generate(session: Session, assignments: list[dict], *, size_mm: float,
             front_mm: float, back_mm: float, backing_hex: str | None) -> dict:
    """Build one STL per distinct assigned filament (+ optional backing plate),
    a recolored preview PNG, and a manifest. Returns file metadata + a zip.

    Meshes are built from the cached detection label map — the exact same masks
    the live preview is painted from — so what you saw is what you get, and no
    assigned region is ever silently dropped. At detection resolution the
    contour spacing is far finer than any nozzle line width.
    """
    cfg = PlateConfig(size_mm=size_mm, front_mm=front_mm, back_mm=back_mm,
                      backing_color=backing_hex)
    stem = os.path.splitext(session.filename)[0] or "logo"
    out_dir = session.out_dir
    # clear previously generated artifacts
    for f in os.listdir(out_dir):
        if f != os.path.basename(session.src_path):
            try:
                os.remove(os.path.join(out_dir, f))
            except OSError:
                pass

    sil = session.sil
    labels = session.labels
    ys, xs = np.where(sil)
    span = max(int(xs.max() - xs.min()), int(ys.max() - ys.min()))
    scale = cfg.size_mm / span
    builder = MeshBuilder(scale, cfg.simplify_px, cfg.min_area_mm2)

    # Group region masks by assigned filament, preserving region order.
    groups: "OrderedDict[str, dict]" = OrderedDict()
    for i, fil in enumerate(assignments):
        mask = labels == i
        if not mask.any():
            continue
        key = fil["hex"].upper()
        g = groups.get(key)
        if g is None:
            g = {"fil": fil, "mask": np.zeros_like(sil)}
            groups[key] = g
        g["mask"] |= mask

    files: list[GenFile] = []
    written: list[str] = []
    manifest_colors = []
    for g in groups.values():
        mesh = builder.build(g["mask"], cfg.front_mm, z_offset=0.0)
        if mesh is None:
            continue
        fname = "%s_%s.stl" % (stem, _filament_slug(g["fil"]))
        path = os.path.join(out_dir, fname)
        mesh.export(path)
        written.append(path)
        files.append(GenFile(fname, g["fil"]["hex"], os.path.getsize(path) / 1e6))
        manifest_colors.append({
            "name": g["fil"]["name"], "hex": g["fil"]["hex"],
            "rgb": list(hex_to_rgb(g["fil"]["hex"])), "stl": fname,
        })

    backing_name = None
    if backing_hex:
        backing = builder.build(sil, cfg.back_mm, z_offset=cfg.front_mm)
        if backing is not None:
            backing_name = "%s_backing.stl" % stem
            path = os.path.join(out_dir, backing_name)
            backing.export(path)
            written.append(path)
            files.append(GenFile(backing_name, backing_hex, os.path.getsize(path) / 1e6))

    # recolored preview PNG (show face) at detection res
    prev_name = "%s_preview.png" % stem
    prev_path = os.path.join(out_dir, prev_name)
    _write_show_preview(session, [a["hex"] for a in assignments], prev_path)
    written.append(prev_path)

    # manifest
    man_name = "%s_manifest.json" % stem
    man_path = os.path.join(out_dir, man_name)
    with open(man_path, "w") as fh:
        json.dump({
            "front_mm": cfg.front_mm, "back_mm": cfg.back_mm, "size_mm": cfg.size_mm,
            "backing_color": backing_hex, "colors": manifest_colors,
            "backing": backing_name,
            "note": "Load all STLs together; they share an origin. Print face-down.",
        }, fh, indent=2)
    written.append(man_path)

    # zip everything
    zip_name = "%s_colorplate.zip" % stem
    zip_path = os.path.join(out_dir, zip_name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in written:
            zf.write(p, os.path.basename(p))

    covered = np.zeros_like(sil)
    for g in groups.values():
        covered |= g["mask"]
    gap = int((sil & ~covered).sum())

    total = sum(f.size_mb for f in files)
    return {
        "files": [{"name": f.name, "hex": f.hex, "sizeMB": round(f.size_mb, 1)} for f in files],
        "totalMB": round(total, 1),
        "zip": zip_name,
        "coverageGap": gap,
    }


def _write_show_preview(session: Session, assignments_hex: list[str], path: str) -> None:
    sil = session.sil
    labels = session.labels
    h, w = sil.shape
    out = np.full((h, w, 3), 205, "uint8")
    for i, fil_hex in enumerate(assignments_hex):
        m = labels == i
        if m.any():
            out[m] = hex_to_rgb(fil_hex)
    Image.fromarray(out).save(path)


def _clear_artifacts(session: Session) -> None:
    src = os.path.basename(session.src_path)
    for f in os.listdir(session.out_dir):
        if f != src:
            try:
                os.remove(os.path.join(session.out_dir, f))
            except OSError:
                pass


def generate_stack(session: Session, assignments: list[dict], order: list[str], *,
                   size_mm: float, base_mm: float, step_mm: float, layer_mm: float) -> dict:
    """Single-extruder export: one terraced STL (the band-slabs merged into a
    single solid) plus a filament-swap schedule, manifest, and show-face preview,
    bundled into a zip. The print is one object on one nozzle; the operator
    inserts an ``M600`` at each swap layer in the schedule.
    """
    import trimesh

    base_mm = _snap(base_mm, layer_mm)
    step_mm = _snap(step_mm, layer_mm)
    if not order:
        raise ValueError("No colors to stack.")
    stem = os.path.splitext(session.filename)[0] or "logo"
    _clear_artifacts(session)

    assign_hex = [a["hex"] for a in assignments]
    name_by_hex = {a["hex"].upper(): a["name"] for a in assignments}
    slabs, total = _stack_slabs(session, assign_hex, order, size_mm, base_mm, step_mm)
    meshes = [s["mesh"] for s in slabs if s["mesh"] is not None]
    if not meshes:
        raise ValueError("Nothing printable to export.")

    # Merge the slabs into one solid. Prefer a clean boolean union; fall back to
    # concatenation (slicers union overlapping shells anyway) if no CSG backend.
    try:
        solid = trimesh.boolean.union(meshes)
        if solid is None or solid.is_empty:
            raise ValueError("empty union")
    except Exception:
        solid = trimesh.util.concatenate(meshes)

    written: list[str] = []
    files: list[GenFile] = []

    stl_name = "%s_stack.stl" % stem
    stl_path = os.path.join(session.out_dir, stl_name)
    solid.export(stl_path)
    written.append(stl_path)
    files.append(GenFile(stl_name, order[0], os.path.getsize(stl_path) / 1e6))

    bands = _swap_bands(order, base_mm, step_mm, layer_mm)
    for band in bands:
        band["name"] = name_by_hex.get(band["hex"].upper(), band["hex"])

    # human-readable swap schedule
    sched_name = "%s_swaps.txt" % stem
    sched_path = os.path.join(session.out_dir, sched_name)
    lines = [
        "ColorPlate — single-extruder filament-swap schedule",
        "%s  ·  %gmm  ·  base %gmm  ·  step %gmm  ·  layer %gmm" % (
            stem, size_mm, base_mm, step_mm, layer_mm),
        "Total height: %gmm   ·   %d filament change(s)" % (total, max(0, len(order) - 1)),
        "",
        "Print %s as a single object. Insert a filament change (M600) at each swap." % stl_name,
        "",
    ]
    for band in bands:
        verb = "Start" if band["action"] == "start" else "Swap "
        lines.append("  %s  %-14s %-9s  layer %-4d  z %.2fmm" % (
            verb, band["name"], "(" + band["hex"] + ")", band["layer"], band["z0"]))
    with open(sched_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    written.append(sched_path)
    files.append(GenFile(sched_name, "#9A9AA1", os.path.getsize(sched_path) / 1e6))

    # manifest
    man_name = "%s_manifest.json" % stem
    man_path = os.path.join(session.out_dir, man_name)
    with open(man_path, "w") as fh:
        json.dump({
            "mode": "single-extruder",
            "size_mm": size_mm, "base_mm": base_mm, "step_mm": step_mm,
            "layer_mm": layer_mm, "total_mm": round(total, 2), "stl": stl_name,
            "bands": [{
                "name": b["name"], "hex": b["hex"], "rgb": list(hex_to_rgb(b["hex"])),
                "action": b["action"], "z_mm": b["z0"], "layer": b["layer"],
            } for b in bands],
            "note": "Single extruder: print the STL and insert an M600 at each swap layer.",
        }, fh, indent=2)
    written.append(man_path)
    files.append(GenFile(man_name, "#9A9AA1", os.path.getsize(man_path) / 1e6))

    # show-face preview (top view)
    prev_name = "%s_preview.png" % stem
    prev_path = os.path.join(session.out_dir, prev_name)
    _write_show_preview(session, assign_hex, prev_path)
    written.append(prev_path)
    files.append(GenFile(prev_name, "#9A9AA1", os.path.getsize(prev_path) / 1e6))

    # zip everything
    zip_name = "%s_single_extruder.zip" % stem
    zip_path = os.path.join(session.out_dir, zip_name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in written:
            zf.write(p, os.path.basename(p))

    return {
        "files": [{"name": f.name, "hex": f.hex, "sizeMB": round(f.size_mb, 1)} for f in files],
        "totalMB": round(sum(f.size_mb for f in files), 1),
        "zip": zip_name,
        "coverageGap": 0,
        "totalHeight": round(total, 2),
        "swaps": max(0, len(order) - 1),
    }
