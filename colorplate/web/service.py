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
