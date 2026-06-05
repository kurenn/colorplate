# Changelog

All notable changes to ColorPlate are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/kurenn/colorplate/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kurenn/colorplate/releases/tag/v0.1.0
