"""Single-extruder ("filament swap") geometry + export.

Covers the terraced band-slab model, the layer-snapped swap schedule, and the
`generate_stack` export (one terraced STL + schedule + manifest + zip), plus the
`/api/generate-stack` endpoint.
"""
from __future__ import annotations

import json
import os
import zipfile

import pytest
import trimesh

from colorplate.web import server, service


def _assignments_and_order(payload):
    assignments = [{"name": r["filament"]["name"], "hex": r["filament"]["hex"]}
                   for r in payload["regions"]]
    order = []
    for a in assignments:
        if a["hex"] not in order:
            order.append(a["hex"])
    return assignments, order


# ---------------------------------------------------------------------------
# Layer snapping + swap schedule
# ---------------------------------------------------------------------------
def test_snap_to_layer():
    assert service._snap(0.8, 0.2) == pytest.approx(0.8)
    assert service._snap(0.75, 0.2) == pytest.approx(0.8)     # nearest layer
    assert service._snap(0.05, 0.2) == pytest.approx(0.2)     # min one layer


def test_swap_bands_layers_and_heights():
    order = ["#231F1D", "#F9CF26", "#ED4324", "#F4F4F4"]
    bands = service._swap_bands(order, base_mm=0.8, step_mm=0.6, layer_mm=0.2)
    assert [b["action"] for b in bands] == ["start", "swap", "swap", "swap"]
    assert [b["z0"] for b in bands] == [0.0, 0.8, 1.4, 2.0]
    assert [b["layer"] for b in bands] == [1, 5, 8, 11]       # z/layer + 1


# ---------------------------------------------------------------------------
# Band-slab geometry
# ---------------------------------------------------------------------------
def test_stack_slabs_are_nested_from_base(sample_session):
    session, payload = sample_session
    assignments, order = _assignments_and_order(payload)
    assign_hex = [a["hex"] for a in assignments]
    slabs, total = service._stack_slabs(session, assign_hex, order,
                                        size_mm=120, base_mm=0.8, step_mm=0.6)
    assert len(slabs) == len(order)
    # band 0 is the full-silhouette base plate; every band has geometry here
    assert all(s["mesh"] is not None for s in slabs)
    # footprints shrink as you go up: base slab is the widest
    areas = [s["mesh"].area for s in slabs]
    assert areas[0] == max(areas)
    assert total == pytest.approx(0.8 + 3 * 0.6, abs=1e-6)


def test_build_stack3d_payload(sample_session):
    session, payload = sample_session
    assignments, order = _assignments_and_order(payload)
    assign_hex = [a["hex"] for a in assignments]
    out = service.build_stack3d(session, assignments=assign_hex, order=order,
                                size_mm=120, base_mm=0.8, step_mm=0.6, layer_mm=0.2)
    assert len(out["regions"]) == len(order)
    assert out["regions"][0]["color"] == order[0]            # base band carries its color
    assert out["backing"] is None                            # base is band 0, not a separate plate
    assert out["bbox"][2] == pytest.approx(0.0, abs=1e-6)
    assert out["bbox"][5] == pytest.approx(out["totalHeight"], abs=1e-2)
    assert len(out["bands"]) == len(order)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def test_generate_stack_export(sample_session):
    session, payload = sample_session
    assignments, order = _assignments_and_order(payload)
    res = service.generate_stack(session, assignments, order,
                                 size_mm=120, base_mm=0.8, step_mm=0.6, layer_mm=0.2)

    names = [f["name"] for f in res["files"]]
    assert any(n.endswith("_stack.stl") for n in names)
    assert any(n.endswith("_swaps.txt") for n in names)
    assert any(n.endswith("_manifest.json") for n in names)
    assert res["totalHeight"] == pytest.approx(2.6, abs=1e-6)
    assert res["swaps"] == len(order) - 1

    # the single STL is a closed solid spanning 0..total height
    stl = next(n for n in names if n.endswith("_stack.stl"))
    mesh = trimesh.load(os.path.join(session.out_dir, stl))
    assert mesh.is_watertight
    assert mesh.bounds[0][2] == pytest.approx(0.0, abs=1e-3)
    assert mesh.bounds[1][2] == pytest.approx(2.6, abs=1e-2)

    # manifest is single-extruder with one band per color
    man = json.load(open(os.path.join(session.out_dir, stl.replace("_stack.stl", "_manifest.json"))))
    assert man["mode"] == "single-extruder"
    assert len(man["bands"]) == len(order)
    assert man["bands"][0]["action"] == "start"

    # zip bundles everything
    zpath = os.path.join(session.out_dir, res["zip"])
    with zipfile.ZipFile(zpath) as zf:
        members = zf.namelist()
    assert any(m.endswith("_stack.stl") for m in members)
    assert any(m.endswith("_swaps.txt") for m in members)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(sample_session):
    from fastapi.testclient import TestClient
    session, _ = sample_session
    server.store.put(session)
    return TestClient(server.app)


def test_api_generate_stack(client, sample_session):
    session, payload = sample_session
    assignments, order = _assignments_and_order(payload)
    resp = client.post("/api/generate-stack", json={
        "uploadId": session.id, "assignments": assignments, "order": order,
        "size": 120, "base": 0.8, "step": 0.6, "layer": 0.2,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["swaps"] == len(order) - 1
    assert any(f["name"].endswith("_stack.stl") for f in data["files"])
    assert data["zip"].endswith(".zip")


def test_api_generate_stack_unknown_upload_404(client):
    resp = client.post("/api/generate-stack", json={
        "uploadId": "nope", "assignments": [], "order": [],
        "size": 120, "base": 0.8, "step": 0.6, "layer": 0.2,
    })
    assert resp.status_code == 404
