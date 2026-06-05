"""Printability guardrails: thin-feature detection (`feature_report`), the web
service + `/api/printability` endpoint, and the CLI/pipeline report.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

from colorplate import printability as P
from colorplate.config import Color, PlateConfig
from colorplate.pipeline import PlatePipeline
from colorplate.web import server, service


# ---------------------------------------------------------------------------
# Unit: feature_report on synthetic masks
# ---------------------------------------------------------------------------
def _block(h=100, w=100):
    m = np.zeros((h, w), bool)
    m[20:80, 20:80] = True       # 60px square
    return m


def test_thick_block_is_ok():
    rep = P.feature_report([("k", _block())], scale=0.2, nozzle_mm=0.4, size_mm=100)
    assert rep["worst"] == "ok"
    assert rep["colors"][0]["level"] == "ok"
    assert rep["suggestedSizeMm"] is None


def test_hairline_strand_wont_print():
    m = np.zeros((100, 100), bool)
    m[20:80, 40:80] = True       # thick anchor
    m[49:50, 20:40] = True       # 1px (0.2mm @ scale 0.2) strand → below nozzle
    rep = P.feature_report([("k", m)], scale=0.2, nozzle_mm=0.4, size_mm=100)
    assert rep["worst"] == "wontprint"
    assert rep["colors"][0]["narrowestMm"] < 0.4
    assert rep["suggestedSizeMm"] and rep["suggestedSizeMm"] > 100


def test_midwidth_strand_is_fragile():
    m = np.zeros((100, 100), bool)
    m[20:80, 40:80] = True
    m[48:51, 20:40] = True       # 3px (0.6mm) strand → between 0.4 and 0.8
    rep = P.feature_report([("k", m)], scale=0.2, nozzle_mm=0.4, size_mm=100)
    assert rep["colors"][0]["level"] == "fragile"


def test_suggested_size_clears_the_feature():
    m = np.zeros((100, 100), bool)
    m[20:80, 40:80] = True
    m[49:50, 20:40] = True
    rep = P.feature_report([("k", m)], scale=0.2, nozzle_mm=0.4, size_mm=100)
    s = rep["suggestedSizeMm"]
    assert s and s > 100
    # at the suggested size the print scales up (scale grows with size, span fixed),
    # so the feature should no longer be a hard "won't print"
    rep2 = P.feature_report([("k", m)], scale=0.2 * (s / 100), nozzle_mm=0.4, size_mm=s)
    assert rep2["worst"] != "wontprint"


def test_empty_masks_are_ok():
    rep = P.feature_report([("k", np.zeros((10, 10), bool))], scale=0.2, nozzle_mm=0.4, size_mm=100)
    assert rep["worst"] == "ok" and rep["colors"] == []


# ---------------------------------------------------------------------------
# Web service + endpoint
# ---------------------------------------------------------------------------
def _thin_session():
    """A session whose region 1 is a 2-px strand (thin at small sizes)."""
    h = w = 200
    sil = np.zeros((h, w), bool); sil[20:180, 20:180] = True
    labels = np.full((h, w), -1, int); labels[sil] = 0
    labels[99:101, 20:180] = 1                 # 2px-wide strand = region 1
    return service.Session(id="thin", filename="t.svg", src_path="", out_dir="",
                           rgb=np.zeros((h, w, 3), int), sil=sil, labels=labels,
                           detected=["#231F1D", "#ED4324"])


def test_service_printability_small_vs_large():
    session = _thin_session()
    small = service.printability(session, size_mm=20, nozzle_mm=0.4)   # 2px ≈ 0.25mm
    large = service.printability(session, size_mm=400, nozzle_mm=0.4)  # 2px ≈ 5mm
    assert small["worst"] == "wontprint"
    assert small["overlay"] and small["overlay"].startswith("data:image/png")
    assert large["worst"] == "ok" and large["overlay"] is None


@pytest.fixture()
def client(sample_session):
    from fastapi.testclient import TestClient
    session, _ = sample_session
    server.store.put(session)
    return TestClient(server.app)


def test_api_printability_ok(client, sample_session):
    session, _ = sample_session
    r = client.post("/api/printability", json={"uploadId": session.id, "size": 25, "nozzle": 0.6})
    assert r.status_code == 200
    data = r.json()
    assert {"colors", "worst", "suggestedSizeMm", "nozzleMm", "overlay"} <= data.keys()
    assert all("index" in c for c in data["colors"])


def test_api_printability_unknown_upload_404(client):
    r = client.post("/api/printability", json={"uploadId": "nope", "size": 100, "nozzle": 0.4})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# CLI / pipeline
# ---------------------------------------------------------------------------
_PALETTE = [Color.from_hex("c0", "#231F1D"), Color.from_hex("c1", "#F9CF26"),
            Color.from_hex("c2", "#ED4324"), Color.from_hex("c3", "#F4F4F4")]


def test_pipeline_report_in_result_and_manifest(sample_svg_path, tmp_path):
    cfg = PlateConfig(size_mm=180, raster_px=600, palette=_PALETTE, nozzle_mm=0.4)
    res = PlatePipeline(cfg).run(sample_svg_path, str(tmp_path))
    assert res.printability and res.printability["worst"] == "ok"   # sample is chunky
    man = json.load(open(res.manifest))
    assert "printability" in man and man["printability"]["nozzleMm"] == 0.4
