"""Fill enclosed areas: hole-filling the silhouette so blank spaces inside the
design (e.g. white letter interiors) become paintable regions.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from colorplate.config import PlateConfig
from colorplate.pipeline import PlatePipeline
from colorplate.raster import fill_enclosed
from colorplate.web import server, service


def test_fill_enclosed_fills_holes_not_border():
    sil = np.zeros((50, 50), bool)
    sil[10:40, 10:40] = True       # solid square
    sil[20:30, 20:30] = False      # an enclosed hole
    out = fill_enclosed(sil)
    assert out[25, 25]             # enclosed hole filled
    assert out[10:40, 10:40].all()
    assert not out[0, 0]           # outer (border-connected) background stays out


def _holed_session():
    """Black square frame around a white interior, on a white background — the
    interior is excluded by background detection until holes are filled."""
    h = w = 200
    rgb = np.full((h, w, 3), 255, int)
    sil = np.zeros((h, w), bool)
    sil[20:180, 20:180] = True
    sil[60:140, 60:140] = False    # white hole (interior)
    rgb[sil] = (10, 10, 10)        # black design
    rgb[60:140, 60:140] = (250, 250, 250)
    return service.Session(id="holed", filename="t.png", src_path="", out_dir="",
                           rgb=rgb, sil=sil, sil_raw=sil)


def _has_near_white(payload):
    return any(int(r["detected"][1:3], 16) > 200 for r in payload["regions"])


def test_detect_with_fill_adds_the_interior_region():
    sess = _holed_session()
    off = service.detect_from_path(sess, 4, fill_holes=False)
    on = service.detect_from_path(sess, 4, fill_holes=True)
    assert off["fillHoles"] is False and on["fillHoles"] is True
    assert not _has_near_white(off)        # interior missing without fill
    assert _has_near_white(on)             # interior surfaces as a paintable color


def test_api_redetect_fill_holes(sample_session):
    from fastapi.testclient import TestClient
    sess = _holed_session()
    server.store.put(sess)
    client = TestClient(server.app)
    off = client.post("/api/redetect", json={"uploadId": sess.id, "maxColors": 4, "fillHoles": False})
    on = client.post("/api/redetect", json={"uploadId": sess.id, "maxColors": 4, "fillHoles": True})
    assert off.status_code == 200 and on.status_code == 200
    assert len(on.json()["regions"]) > len(off.json()["regions"])


def test_cli_pipeline_fill_holes(tmp_path):
    a = np.full((200, 200, 3), 255, np.uint8)
    a[40:160, 40:160] = (10, 10, 10)       # black square
    a[80:120, 80:120] = (255, 255, 255)    # enclosed white hole
    p = tmp_path / "holed.png"
    Image.fromarray(a).save(p)

    off = PlatePipeline(PlateConfig(size_mm=100, raster_px=400, fill_holes=False)).run(
        str(p), str(tmp_path / "off"))
    on = PlatePipeline(PlateConfig(size_mm=100, raster_px=400, fill_holes=True)).run(
        str(p), str(tmp_path / "on"))
    assert len(on.files) > len(off.files)  # the white interior becomes its own color
