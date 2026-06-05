"""Printability guardrails (shared by the CLI and the web service).

Detects color regions with features narrower than the nozzle line width at the
chosen print size — strands that the slicer would skip or print fragile — and
flags colors that are so thin they'd vanish entirely (the mesh builder drops
islands below ``min_area_mm2``). Reports per color, with the width of the
thinnest real feature and the size you'd need to scale to so it clears the
nozzle. Warns only; nothing is blocked or modified.

Dependency-light: numpy + scipy.ndimage + cv2 (all already required).
"""
from __future__ import annotations

import math

import cv2
import numpy as np
from scipy import ndimage

OK, FRAGILE, WONTPRINT = "ok", "fragile", "wontprint"
_RANK = {OK: 0, FRAGILE: 1, WONTPRINT: 2}


def _thin_mask(mask: np.ndarray, width_px: float) -> np.ndarray:
    """Pixels of ``mask`` belonging to features narrower than ``width_px`` —
    i.e. removed by a morphological opening with a disk of that diameter. Opening
    keeps the thick core and strips only genuinely thin parts, so region
    boundaries of thick blobs are NOT flagged."""
    if width_px < 1.5:        # threshold finer than the pixel grid → nothing to flag
        return np.zeros_like(mask, dtype=bool)
    r = max(1, int(round(width_px / 2.0)))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    opened = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, k)
    return mask & ~opened.astype(bool)


def _keep_significant(lost: np.ndarray, min_px: float) -> np.ndarray:
    """Drop connected components smaller than ``min_px`` so 1-px noise isn't
    flagged (mirrors MeshBuilder's min-area speckle filter)."""
    if not lost.any():
        return lost
    labeled, n = ndimage.label(lost)
    if n == 0:
        return lost
    sizes = ndimage.sum(np.ones_like(labeled), labeled, index=range(1, n + 1))
    keep = {i + 1 for i, s in enumerate(sizes) if s >= min_px}
    return np.isin(labeled, list(keep)) if keep else np.zeros_like(lost)


def _narrowest_mm(mask: np.ndarray, lost: np.ndarray, scale: float) -> float | None:
    """Width (mm) of the thinnest real thin-feature: per connected component of
    ``lost``, the strand width ≈ ``2*EDT_max - 1`` px (the -1 corrects the
    half-pixel discretization bias of the distance transform on thin strands)."""
    if not lost.any():
        return None
    edt = ndimage.distance_transform_edt(mask)
    labeled, n = ndimage.label(lost)
    if n == 0:
        return None
    widths = [max(0.5, 2.0 * float(edt[labeled == i].max()) - 1.0) * scale
              for i in range(1, n + 1)]
    return round(min(widths), 3) if widths else None


def feature_report(masks, scale: float, nozzle_mm: float, *,
                   min_area_mm2: float = 0.3, fragile_mult: float = 2.0,
                   size_mm: float | None = None,
                   return_masks: bool = False) -> dict:
    """Assess printability of each color region.

    ``masks``  : iterable of ``(key, bool_mask)``.
    ``scale``  : mm per pixel (``size_mm / span``).
    Returns ``{colors: [{key, level, narrowestMm, atRiskPct}], worst,
    suggestedSizeMm, nozzleMm}``. With ``return_masks`` also yields per-color
    ``hardMask`` / ``fragileMask`` (numpy bool) for rendering an overlay.
    """
    nozzle_mm = max(0.05, float(nozzle_mm))
    px_area = scale * scale
    min_px = max(1.0, min_area_mm2 / px_area) if px_area > 0 else 1.0
    nozzle_px = nozzle_mm / scale if scale > 0 else 1.0

    colors, worst_rank, narrowest_offender = [], 0, None
    for key, mask in masks:
        mask = np.asarray(mask, dtype=bool)
        area_px = int(mask.sum())
        if area_px == 0:
            continue

        hard = _keep_significant(_thin_mask(mask, nozzle_px), min_px)
        frag = _keep_significant(_thin_mask(mask, nozzle_px * fragile_mult), min_px)
        frag_only = frag & ~hard

        hard_px = int(hard.sum())
        printable_px = area_px - hard_px
        vanish = printable_px * px_area < min_area_mm2

        # a level needs a *meaningful* at-risk area (≥ min_area_mm2), so the
        # rounded corners an opening shaves off a thick block don't trip it
        hard_area = hard_px * px_area
        frag_area = int(frag_only.sum()) * px_area
        if (hard_area >= min_area_mm2) or vanish:
            level = WONTPRINT
        elif frag_area >= min_area_mm2:
            level = FRAGILE
        else:
            level = OK

        at_risk_pct = round(100.0 * (hard_px + int(frag_only.sum())) / area_px, 1)
        narrow = _narrowest_mm(mask, hard if hard.any() else frag_only, scale)
        entry = {"key": key, "level": level, "narrowestMm": narrow,
                 "atRiskPct": at_risk_pct, "vanish": bool(vanish)}
        if return_masks:
            entry["hardMask"], entry["fragileMask"] = hard, frag_only
        colors.append(entry)

        worst_rank = max(worst_rank, _RANK[level])
        if level != OK and narrow:
            narrowest_offender = narrow if narrowest_offender is None else min(narrowest_offender, narrow)

    worst = next(k for k, v in _RANK.items() if v == worst_rank)

    # Suggest the size that brings the thinnest at-risk feature up to a *safe*
    # width (2× nozzle), so one click lands it cleanly printable. Capped at 4×.
    suggested = None
    if size_mm and narrowest_offender and narrowest_offender > 0:
        factor = min(4.0, (fragile_mult * nozzle_mm) / narrowest_offender)
        if factor > 1.01:
            suggested = int(math.ceil(size_mm * factor / 5.0) * 5)  # round up to 5mm

    return {"colors": colors, "worst": worst,
            "suggestedSizeMm": suggested, "nozzleMm": round(nozzle_mm, 2)}
