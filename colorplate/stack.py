"""Single-extruder ("filament swap") terrace helpers, shared by the CLI and the
web service so both agree on layer snapping, the swap schedule, and how the
band-slabs merge into one printable solid.

A single nozzle can only lay one filament per layer, so colors are stacked by
height: band 0 is the full-silhouette base plate (printed in the base filament),
and each higher band is the union of regions that reach that height, printed
through that swap's layers. The operator inserts an ``M600`` at each swap.
"""
from __future__ import annotations


def snap(value: float, layer: float) -> float:
    """Round a height to the nearest whole layer (min one layer) — filament
    swaps can only land on a layer boundary."""
    layer = max(0.04, layer)
    return max(layer, round(value / layer) * layer)


def swap_bands(order: list[str], base_mm: float, step_mm: float,
               layer_mm: float) -> list[dict]:
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


def merge_terrace(meshes: list):
    """Merge the band-slabs into one solid. Prefer a clean boolean union; fall
    back to concatenation (slicers union overlapping shells anyway) if there's
    no CSG backend. Returns a trimesh, or None if there are no meshes."""
    import trimesh

    meshes = [m for m in meshes if m is not None]
    if not meshes:
        return None
    try:
        solid = trimesh.boolean.union(meshes)
        if solid is None or solid.is_empty:
            raise ValueError("empty union")
        return solid
    except Exception:
        return trimesh.util.concatenate(meshes)
