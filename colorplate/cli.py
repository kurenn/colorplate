"""Command-line interface for colorplate."""
from __future__ import annotations

import argparse
import sys

from .config import Color, PlateConfig
from .pipeline import PlatePipeline


def _parse_palette(spec: str) -> list[Color]:
    colors = []
    for i, token in enumerate(spec.split(",")):
        token = token.strip()
        if not token:
            continue
        if "=" in token:           # name=#hex
            name, hex_str = token.split("=", 1)
        else:                       # #hex -> auto name
            name, hex_str = f"c{i}", token
        colors.append(Color.from_hex(name.strip(), hex_str.strip()))
    return colors


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="colorplate",
        description="Turn an SVG/PNG into layered, gap-free multicolor STL plates "
                    "for face-down multi-material printing.",
    )
    p.add_argument("input", help="Source .svg or raster image")
    p.add_argument("-o", "--out", default="out", help="Output directory (default: out)")
    p.add_argument("--height", type=float, default=180.0,
                   help="Longest in-plane dimension in mm (default: 180)")
    p.add_argument("--front", type=float, default=1.0,
                   help="Front color-shell thickness in mm (default: 1.0)")
    p.add_argument("--back", type=float, default=2.0,
                   help="Backing thickness in mm (default: 2.0)")
    p.add_argument("--backing-color", default=None,
                   help="Color name for the single-color back. Omit for no backing.")
    p.add_argument("--palette", default=None,
                   help='Explicit palette, e.g. "red=#ED4324,dark=#231F1D". '
                        "Omit to auto-detect from SVG fills / quantize a raster.")
    p.add_argument("--colors", type=int, default=4,
                   help="Target color count when auto-quantizing a raster (default: 4)")
    p.add_argument("--raster-px", type=int, default=1600,
                   help="Rasterization resolution on the long edge (default: 1600)")

    se = p.add_argument_group("single-extruder (filament swaps, no MMU)")
    se.add_argument("--single-extruder", action="store_true",
                    help="Build ONE terraced STL with colors stacked by height, "
                         "printed with a filament change (M600) between bands.")
    se.add_argument("--base", type=float, default=0.8,
                    help="Base-plate height in mm for single-extruder (default: 0.8)")
    se.add_argument("--step", type=float, default=0.6,
                    help="Height added per color band in mm (default: 0.6)")
    se.add_argument("--layer-height", type=float, default=0.2,
                    help="Layer height swaps snap to, in mm (default: 0.2)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = PlateConfig(
        size_mm=args.height,
        front_mm=args.front,
        back_mm=args.back,
        backing_color=args.backing_color,
        raster_px=args.raster_px,
        auto_colors=args.colors,
        palette=_parse_palette(args.palette) if args.palette else [],
    )

    if args.single_extruder:
        res = PlatePipeline(cfg).run_stack(
            args.input, args.out,
            base_mm=args.base, step_mm=args.step, layer_mm=args.layer_height,
        )
        print(f"Wrote terraced STL ({res.total_mm:g}mm tall) to {args.out}/")
        print(f"  stl        -> {res.stl}")
        print(f"  swaps      -> {res.swaps}")
        print(f"  manifest   -> {res.manifest}")
        print(f"  preview    -> {res.preview}")
        print(f"Single extruder — print as one object, insert M600 at:")
        for b in res.bands:
            verb = "start" if b["action"] == "start" else "swap "
            print(f"  layer {b['layer']:<4d} z {b['z0']:.2f}mm  {verb}  {b['hex']}")
        return 0

    result = PlatePipeline(cfg).run(args.input, args.out)

    print(f"Wrote {len(result.files)} STL(s) to {args.out}/")
    for name, path in result.files.items():
        print(f"  {name:10s} -> {path}")
    print(f"  preview    -> {result.preview}")
    print(f"  manifest   -> {result.manifest}")
    if result.gap_px:
        print(f"WARNING: {result.gap_px} uncovered pixels (gaps in tiling)", file=sys.stderr)
    else:
        print("Coverage: 100% (no gaps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
