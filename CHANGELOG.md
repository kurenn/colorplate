# Changelog

All notable changes to ColorPlate are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.1] - 2026-06-05

### Added
- Packaging metadata for discoverability — PyPI keywords, trove classifiers,
  project URLs (homepage, repository, issues, changelog), and an author/contact
  email. README gains a Contact section.

## [0.3.0] - 2026-06-05

### Added
- **Single-extruder mode** (CLI + web GUI). For printers without an MMU /
  toolchanger, colors are stacked by height into a terraced relief — a base
  plate, then each color raised one step higher — printable on one nozzle with an
  `M600` filament change between bands. Export produces one watertight terraced
  STL plus a filament-swap schedule (Z height + layer per swap, snapped to the
  layer height), a manifest, and a preview.
  - CLI: `colorplate logo.svg --single-extruder [--base --step --layer-height]`.
  - GUI: a Printer toggle (Multi-material ⟷ Single extruder) with a live 3D
    relief preview and a reorderable base→top color stack
    (`POST /api/stack3d`, `POST /api/generate-stack`).
- Full test suite (54 tests) covering the core pipeline (raster loading,
  detection/quantization, classification, mesh building, end-to-end plate
  generation), the CLI, the web service + HTTP API, single-extruder geometry +
  export, and analytics (including the IP-hashing privacy guarantee), run in CI
  on Python 3.10 & 3.12.

### Changed
- Migrate the web server's startup hook from the deprecated FastAPI
  `@app.on_event("startup")` to a `lifespan` context manager.

### Fixed
- Results sheet now fully covers the controls column when they're taller than the
  viewport (the column no longer scrolls behind the overlay).

## [0.2.0] - 2026-06-05

### Added
- **Real 3D preview** in the web GUI: a 2D/3D toggle on the print preview renders
  the actual layered geometry (one extruded mesh per color region plus the
  backing plate) with Three.js — drag to rotate, scroll or pinch to zoom,
  double-click or "Reset view" to recenter. Geometry is built from the same
  label map and `MeshBuilder` as STL export, so the preview matches what you
  print; filament reassignments recolor instantly client-side. Backed by a new
  `POST /api/mesh3d` endpoint. Degrades gracefully when WebGL is unavailable and
  honors `prefers-reduced-motion`.
- Test suite for the 3D geometry path (`build_mesh3d` and `/api/mesh3d`) and a
  CI workflow that runs `pytest` on every push and pull request (Python 3.10 &
  3.12).

## [0.1.0] - 2026-06-05

### Added
- Core pipeline: turn SVG/PNG artwork into layered, gap-free multicolor STL
  plates for face-down multi-material printing — extruded colored front shells
  plus an optional single-color backing plate, all sharing one origin.
- `colorplate` CLI: palette auto-detection from SVG fills/strokes, explicit
  named palettes (`--palette name=#hex,...`), raster quantization (`--colors`),
  and size/thickness/backing controls.
- `colorplate-web` browser GUI driving the **same** pipeline: drop a logo,
  detect colors, map each to a filament, preview the recolored art live, and
  download the generated STLs as a `.zip`.
- SQLite usage analytics with a token-protected `/stats` dashboard.
- Single-image Docker deploy (`Dockerfile`) and Render Blueprint (`render.yaml`);
  live at [colorplate.spoolr.io](https://colorplate.spoolr.io/).
- Graphical README with brand assets (hero banner, logo, pipeline graphic,
  GUI screenshots) and an MIT license.

[Unreleased]: https://github.com/kurenn/colorplate/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/kurenn/colorplate/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/kurenn/colorplate/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/kurenn/colorplate/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kurenn/colorplate/releases/tag/v0.1.0
