"""HTTP API (server.py): the full detect -> preview -> mesh3d -> generate ->
download flow, plus the error paths.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from colorplate.web import server


@pytest.fixture()
def api():
    # context-manager form runs startup (analytics.init)
    with TestClient(server.app) as client:
        yield client


def _detect(api, svg_bytes, max_colors=4):
    return api.post(
        "/api/detect",
        files={"file": ("logo.svg", svg_bytes, "image/svg+xml")},
        data={"maxColors": str(max_colors)},
    )


def test_full_flow(api, sample_svg_bytes):
    r = _detect(api, sample_svg_bytes)
    assert r.status_code == 200
    j = r.json()
    uid = j["uploadId"]
    assert j["filename"] == "logo.svg"
    assert len(j["regions"]) >= 3
    assert j["preview"].startswith("data:image/png;base64,")

    hexes = [reg["filament"]["hex"] for reg in j["regions"]]

    rp = api.post("/api/preview", json={"uploadId": uid, "assignments": hexes})
    assert rp.status_code == 200
    assert rp.json()["preview"].startswith("data:image/png;base64,")

    rm = api.post("/api/mesh3d", json={"uploadId": uid, "size": 150, "front": 1.0, "back": 2.0})
    assert rm.status_code == 200
    assert len(rm.json()["regions"]) == len(j["regions"])

    asg = [{"name": reg["filament"]["name"], "hex": reg["filament"]["hex"]} for reg in j["regions"]]
    rg = api.post("/api/generate", json={
        "uploadId": uid, "assignments": asg,
        "size": 150, "front": 1.0, "back": 2.0, "backing": hexes[0],
    })
    assert rg.status_code == 200
    gen = rg.json()
    assert gen["zip"].endswith(".zip") and gen["files"]

    # the assembled, pre-colored 3MF bundle is offered first
    assert gen["model3mf"] and gen["files"][0]["name"].endswith(".3mf")

    # download an STL and the zip
    fname = next(f["name"] for f in gen["files"] if f["name"].endswith(".stl"))
    rf = api.get(f"/api/file/{uid}/{fname}")
    assert rf.status_code == 200 and rf.content
    # the 3MF is downloadable too
    r3 = api.get(f"/api/file/{uid}/{gen['model3mf']}")
    assert r3.status_code == 200 and r3.content
    rz = api.get(f"/api/zip/{uid}/{gen['zip']}")
    assert rz.status_code == 200 and rz.content


def test_redetect_changes_region_count(api, sample_svg_bytes):
    uid = _detect(api, sample_svg_bytes, max_colors=4).json()["uploadId"]
    r = api.post("/api/redetect", json={"uploadId": uid, "maxColors": 2})
    assert r.status_code == 200
    assert len(r.json()["regions"]) <= 2


def test_detect_rejects_unknown_extension(api):
    r = api.post("/api/detect", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_detect_rejects_empty_file(api):
    r = api.post("/api/detect", files={"file": ("empty.svg", b"", "image/svg+xml")})
    assert r.status_code == 400


def test_unknown_session_is_404(api):
    r = api.post("/api/preview", json={"uploadId": "does-not-exist", "assignments": []})
    assert r.status_code == 404


def test_file_path_traversal_blocked(api, sample_svg_bytes):
    uid = _detect(api, sample_svg_bytes).json()["uploadId"]
    r = api.get(f"/api/file/{uid}/..%2f..%2fetc%2fpasswd")
    assert r.status_code == 404
