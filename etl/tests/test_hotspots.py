"""Hotspot polygonization on a synthetic 100x100 m grid (10 m px, UTM 20S)."""
import numpy as np
import rasterio
from rasterio.transform import from_origin
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
make_hotspots = __import__("6_make_hotspots")
polygonize = make_hotspots.polygonize

def _write(path, arr, nodata=255):
    prof = dict(driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1,
                dtype=str(arr.dtype), crs="EPSG:32720",
                transform=from_origin(600000, 8800000, 10, 10), nodata=nodata)
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(arr, 1)

@pytest.fixture
def grid(tmp_path):
    mask = np.zeros((100, 100), np.uint8)
    mask[10:20, 10:20] = 1      # 100 px = 1.0 ha
    mask[60:80, 60:80] = 1      # 400 px = 4.0 ha
    mask[0, 0] = 1              # 1 px = 0.01 ha → below min area
    labels = np.zeros((100, 100), np.uint8)
    labels[60:80, 60:80] = 1    # big blob fully matches PRODES
    m, l = tmp_path/"mask.tif", tmp_path/"lab.tif"
    _write(m, mask); _write(l, labels, nodata=None)
    return str(m), str(l)

def test_two_hotspots_sorted_by_area(grid):
    m, l = grid
    feats = polygonize(m, l, "eval", min_area_ha=0.05)["features"]
    assert len(feats) == 2
    assert feats[0]["properties"]["area_ha"] == pytest.approx(4.0, abs=0.2)
    assert feats[0]["properties"]["area_ha"] >= feats[1]["properties"]["area_ha"]

def test_prodes_overlap_and_status(grid):
    m, l = grid
    feats = polygonize(m, l, "eval", min_area_ha=0.05)["features"]
    big = feats[0]["properties"]
    assert big["prodes_frac"] == pytest.approx(1.0, abs=0.05) and big["status"] == "prodes_match"
    small = feats[1]["properties"]
    assert small["prodes_frac"] == pytest.approx(0.0, abs=0.05) and small["status"] == "model_only"

def test_centroid_in_aoi(grid):
    m, l = grid
    lon, lat = polygonize(m, l, "eval", min_area_ha=0.05)["features"][0]["properties"]["centroid"]
    assert -62.5 < lon < -61.5 and -11.5 < lat < -10.0  # UTM 20S → EPSG:4326 sane
