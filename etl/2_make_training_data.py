"""Rasterize PRODES v20260717 labels onto the mosaic grid → training data.

For pair (t1,t2):  change=1 yearly polygon with t1<year<=t2;
                   ignore=1 year==t1 or year>t2 (ambiguous, excluded from scoring).
NaN pixels of either mosaic are OR-ed into ignore by 3_train/5_eval at load time.
Patch index (TRAIN pair only): positives on the stride-256 grid + 3:1 negatives.
"""
import os
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize

PAIRS = {"train": (2019, 2021), "eval": (2021, 2024)}
LABELS = "data/ground_truth/prodes_yearly_deforestation_v20260717.gpkg"
PATCH = 256
NEG_PER_POS = 3
RNG = np.random.default_rng(42)


def label_windows(gdf: gpd.GeoDataFrame, t1: int, t2: int):
    change = gdf[(gdf.year > t1) & (gdf.year <= t2)]
    ignore = gdf[(gdf.year == t1) | (gdf.year > t2)]
    return change, ignore


def _burn(gdf, profile):
    if len(gdf) == 0:
        return np.zeros((profile["height"], profile["width"]), np.uint8)
    return rasterize(
        [(g.geometry, 1) for g in gdf.itertuples()],
        out_shape=(profile["height"], profile["width"]),
        transform=profile["transform"], fill=0, dtype="uint8", all_touched=True,
    )


def _write(path, arr, profile):
    prof = {**profile, "count": 1, "dtype": "uint8", "compress": "deflate", "nodata": 0}
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(arr, 1)
        dst.build_overviews([2, 4, 8, 16], Resampling.nearest)
        dst.update_tags(ns="rio_overview", resampling="nearest")


def build_pair(name, t1, t2):
    gdf = gpd.read_file(LABELS)
    change, ignore = label_windows(gdf, t1, t2)
    with rasterio.open(f"data/mosaics/mosaic_{t2}.tif") as src:
        profile, proj = src.profile, src.crs
    os.makedirs("models/labels", exist_ok=True)
    _write(f"models/labels/change_{name}.tif", _burn(change.to_crs(proj), profile), profile)
    _write(f"models/labels/ignore_{name}.tif", _burn(ignore.to_crs(proj), profile), profile)

    if name == "train":  # patch index only needed for training
        h, w = profile["height"], profile["width"]
        with rasterio.open(f"models/labels/change_{name}.tif") as s:
            ch = s.read(1)
        with rasterio.open(f"models/labels/ignore_{name}.tif") as s:
            ig = s.read(1)
        pos, neg = [], []
        for r in range(0, h - PATCH + 1, PATCH):
            for c in range(0, w - PATCH + 1, PATCH):
                win = (slice(r, r + PATCH), slice(c, c + PATCH))
                if ch[win].mean() > 0 and ig[win].mean() < 0.5:
                    pos.append((c, r))
                elif ch[win].mean() == 0 and ig[win].mean() < 0.05:
                    neg.append((c, r))
        sel = RNG.choice(len(neg), size=min(len(neg), NEG_PER_POS * len(pos)), replace=False)
        offs = np.array(pos + [neg[i] for i in sel], np.int32)
        np.savez("models/patch_index_train.npz", offs=offs)
        print(f"train: {len(pos)} pos + {len(sel)} neg patches")

    print(f"{name}: change px={int(_burn(change.to_crs(proj), profile).sum()):,}")
    os.makedirs("data/ground_truth/pairs", exist_ok=True)
    change.to_file(f"data/ground_truth/pairs/prodes_{name}.geojson", driver="GeoJSON")


if __name__ == "__main__":
    for name, (t1, t2) in PAIRS.items():
        build_pair(name, t1, t2)
