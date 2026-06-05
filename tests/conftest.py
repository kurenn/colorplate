"""Shared test fixtures.

Keeps analytics writes in a throwaway dir and provides a ready-made detection
``Session`` built from a small synthetic 4-color SVG, so tests don't depend on
any external artwork.
"""
from __future__ import annotations

import os

import pytest

# A compact logo with four flat, well-separated colors (charcoal / gold /
# orange-red / white) — enough to exercise multi-region detection + meshing.
SAMPLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240">
  <circle cx="120" cy="120" r="116" fill="#231F1D"/>
  <circle cx="120" cy="120" r="92" fill="#F9CF26"/>
  <path d="M120 44 a76 76 0 0 1 0 152 Z" fill="#ED4324"/>
  <circle cx="120" cy="120" r="40" fill="#F4F4F4"/>
</svg>"""


@pytest.fixture(scope="session", autouse=True)
def _isolate_analytics(tmp_path_factory):
    """Point analytics at a temp dir so no .data/ file is written in the repo."""
    os.environ["COLORPLATE_DATA_DIR"] = str(tmp_path_factory.mktemp("cp_data"))
    yield


@pytest.fixture(scope="session")
def sample_session(tmp_path_factory):
    """A loaded, detected Session for the sample SVG (4 regions)."""
    from colorplate.web import service

    d = tmp_path_factory.mktemp("cp_session")
    src = d / "sample.svg"
    src.write_text(SAMPLE_SVG)
    session, payload = service.load_session(
        "test-upload", "sample.svg", str(src), str(d), max_colors=4
    )
    return session, payload


@pytest.fixture(scope="session")
def sample_svg_path(tmp_path_factory):
    """Filesystem path to the sample SVG."""
    p = tmp_path_factory.mktemp("svg") / "sample.svg"
    p.write_text(SAMPLE_SVG)
    return str(p)


@pytest.fixture()
def sample_svg_bytes():
    """The sample SVG as raw bytes (for multipart uploads)."""
    return SAMPLE_SVG.encode()


@pytest.fixture(scope="session")
def sample_png_path(tmp_path_factory):
    """A small RGBA PNG: transparent border, two flat-color halves in the middle."""
    import numpy as np
    from PIL import Image

    a = np.zeros((80, 80, 4), "uint8")
    a[15:65, 15:40] = (237, 67, 36, 255)   # orange-red
    a[15:65, 40:65] = (33, 31, 29, 255)    # charcoal
    p = tmp_path_factory.mktemp("png") / "sample.png"
    Image.fromarray(a, "RGBA").save(p)
    return str(p)
