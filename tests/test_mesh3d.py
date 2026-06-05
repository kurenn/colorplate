"""Tests for the live 3D preview geometry (`build_mesh3d`) and the
`POST /api/mesh3d` endpoint added with the 3D preview feature.

The 3D view must render the *same* geometry that gets exported, so these
assert structural validity (well-formed, indexable, watertight meshes) and the
Z-layering contract (front shell at 0..front, backing at front..front+back).
"""
from __future__ import annotations

import numpy as np
import pytest
import trimesh

from colorplate.web import server, service


# ---------------------------------------------------------------------------
# Unit: service.build_mesh3d
# ---------------------------------------------------------------------------
def _as_trimesh(geom):
    v = np.asarray(geom["positions"], dtype=float).reshape(-1, 3)
    f = np.asarray(geom["indices"], dtype=np.int64).reshape(-1, 3)
    return trimesh.Trimesh(vertices=v, faces=f, process=False)


def test_build_mesh3d_shape_and_layering(sample_session):
    session, payload = sample_session
    n = len(payload["regions"])
    assert n == 4                                  # the sample has 4 colors

    front, back = 1.0, 2.0
    out = service.build_mesh3d(session, size_mm=180, front_mm=front, back_mm=back)

    # one entry per detected region, all with real geometry for this sample
    assert len(out["regions"]) == n
    assert all(r["geometry"] for r in out["regions"])
    assert out["backing"] is not None

    # every mesh is well-formed: flat triples, indices in range
    for r in out["regions"]:
        g = r["geometry"]
        assert len(g["positions"]) % 3 == 0 and g["positions"]
        assert len(g["indices"]) % 3 == 0 and g["indices"]
        assert max(g["indices"]) < len(g["positions"]) // 3

    # Z-layering contract: model spans exactly 0 .. front+back
    bbox = out["bbox"]
    assert bbox is not None
    assert bbox[2] == pytest.approx(0.0, abs=1e-6)            # min z
    assert bbox[5] == pytest.approx(front + back, abs=1e-3)   # max z

    # in-plane size honors the requested longest dimension (~180mm)
    width, height = bbox[3] - bbox[0], bbox[4] - bbox[1]
    assert max(width, height) == pytest.approx(180, rel=0.02)


def test_build_mesh3d_regions_are_solid(sample_session):
    """Each region mesh is a watertight solid with positive volume."""
    session, _ = sample_session
    out = service.build_mesh3d(session, size_mm=120, front_mm=1.0, back_mm=2.0)
    for r in out["regions"]:
        mesh = _as_trimesh(r["geometry"])
        assert len(mesh.faces) > 0
        assert mesh.is_watertight
        assert mesh.volume > 0


def test_build_mesh3d_thickness_changes_z(sample_session):
    session, _ = sample_session
    thin = service.build_mesh3d(session, size_mm=180, front_mm=0.4, back_mm=1.0)
    thick = service.build_mesh3d(session, size_mm=180, front_mm=2.0, back_mm=3.0)
    assert thin["bbox"][5] == pytest.approx(1.4, abs=1e-3)
    assert thick["bbox"][5] == pytest.approx(5.0, abs=1e-3)


def test_build_mesh3d_empty_silhouette_is_safe():
    """A session with no silhouette yields an empty (but valid) payload."""
    s = service.Session(
        id="empty", filename="x.svg", src_path="", out_dir="",
        rgb=np.zeros((8, 8, 3), int), sil=np.zeros((8, 8), bool),
    )
    out = service.build_mesh3d(s, size_mm=180, front_mm=1.0, back_mm=2.0)
    assert out["regions"] == []
    assert out["backing"] is None
    assert out["bbox"] is None


def test_build_mesh3d_matches_detected_regions(sample_session):
    """Region geometry lines up 1:1 with the cached detection labels — the same
    masks STL export uses, so what you preview is what you print."""
    session, _ = sample_session
    out = service.build_mesh3d(session, size_mm=180, front_mm=1.0, back_mm=2.0)
    assert [r["index"] for r in out["regions"]] == list(range(len(session.detected)))
    for r in out["regions"]:
        has_pixels = bool((session.labels == r["index"]).any())
        assert bool(r["geometry"]) == has_pixels


# ---------------------------------------------------------------------------
# API: POST /api/mesh3d
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(sample_session):
    """TestClient with the sample session preloaded into the server store."""
    from fastapi.testclient import TestClient

    session, _ = sample_session
    server.store.put(session)
    return TestClient(server.app)


def test_api_mesh3d_ok(client, sample_session):
    session, _ = sample_session
    resp = client.post("/api/mesh3d", json={
        "uploadId": session.id, "size": 180, "front": 1.0, "back": 2.0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert {"regions", "backing", "bbox", "front", "back", "size"} <= data.keys()
    assert len(data["regions"]) == len(session.detected)
    assert data["backing"] is not None
    assert data["bbox"][5] == pytest.approx(3.0, abs=1e-3)


def test_api_mesh3d_unknown_upload_404(client):
    resp = client.post("/api/mesh3d", json={
        "uploadId": "does-not-exist", "size": 180, "front": 1.0, "back": 2.0,
    })
    assert resp.status_code == 404


def test_api_mesh3d_clamps_degenerate_thickness(client, sample_session):
    """Zero/negative thickness is clamped to a printable minimum, not crashed."""
    session, _ = sample_session
    resp = client.post("/api/mesh3d", json={
        "uploadId": session.id, "size": 180, "front": 0.0, "back": 2.0,
    })
    assert resp.status_code == 200
    # front clamped to 0.1 -> total height 0.1 + 2.0
    assert resp.json()["bbox"][5] == pytest.approx(2.1, abs=1e-3)
