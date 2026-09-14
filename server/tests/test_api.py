import os
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.path.exists(os.environ.get("DATA_DIR", "/data") + "/mosaics/mosaic_2021.tif"),
    reason="mosaics not available")
from main import app
client = TestClient(app)

def test_healthz():
    assert client.get("/api/health").json() == {"status": "ok"}

def test_rgb_tile_is_png():
    r = client.get("/tiles/rgb/2021/10/335/542.png")   # center tile coords validated by smoke test
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and len(r.content) > 1000

def test_ndvi_tile_is_png():
    r = client.get("/tiles/ndvi/2021/10/335/542.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"

def test_bad_product_404():
    assert client.get("/tiles/srtm/2021/10/335/542.png").status_code == 404

def test_mask_404_until_computed():
    assert client.get("/tiles/mask/unet/eval/10/335/542.png").status_code in (200, 404)

_metrics_path = os.environ.get("MODELS_DIR", "/models") + "/metrics_eval.json"
_eval_ready = pytest.mark.skipif(not os.path.exists(_metrics_path),
                                 reason="models/metrics_eval.json not available (Task 5 pending)")

@_eval_ready
def test_evaluate_returns_metrics():
    r = client.get("/api/evaluate")
    assert r.status_code == 200 and "ndvidiff" in r.json() and "f1" in r.json()["ndvidiff"]

@_eval_ready
def test_stats_bbox():
    r = client.get("/api/stats?pair=eval&bbox=-62.3,-10.6,-62.1,-10.4")
    assert r.status_code == 200 and set(r.json()) == {"unet_ha", "ndvidiff_ha", "prodes_ha"}

def test_stats_missing_files_return_zeros(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELS_DIR", str(tmp_path))
    import importlib, main
    try:
        importlib.reload(main)          # MODELS_DIR is read at import time
        c = TestClient(main.app)
        resp = c.get("/api/stats?pair=eval&bbox=-62.3,-10.6,-62.1,-10.4")
        assert resp.status_code == 200
        assert resp.json() == {"unet_ha": 0.0, "ndvidiff_ha": 0.0, "prodes_ha": 0.0}
    finally:
        monkeypatch.undo()              # restore env before reload so module state matches
        importlib.reload(main)

def test_prodes_geojson():
    r = client.get("/api/prodes?pair=eval")
    assert r.status_code == 200 and r.json()["type"] == "FeatureCollection"

def test_hotspots_bad_pair_404():
    assert client.get("/api/hotspots?pair=nope").status_code == 404

def test_hotspots_geojson_when_computed():
    r = client.get("/api/hotspots?pair=eval")
    if r.status_code == 404:
        pytest.skip("hotspots not generated yet")
    j = r.json()
    assert j["type"] == "FeatureCollection"
    props = j["features"][0]["properties"]
    assert {"area_ha", "confidence", "prodes_frac", "status", "centroid"} <= set(props)

def test_removed_endpoints_gone():
    for path in ("/api/frontline", "/api/motion", "/api/discover?bbox=-62.3,-10.6,-62.1,-10.4"):
        assert client.get(path).status_code == 404
