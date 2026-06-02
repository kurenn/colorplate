"""colorplate -- SVG/PNG to layered multicolor STL plates."""
from .config import Color, PlateConfig
from .pipeline import PlatePipeline, PlateResult

__version__ = "0.1.0"
__all__ = ["Color", "PlateConfig", "PlatePipeline", "PlateResult"]
