"""F1/IoU on the EVAL pair (2021→2024): U-Net vs NDVI-diff baseline.
Baseline threshold tuned on the TRAIN pair only (no eval leakage)."""
import json
import os

import numpy as np
import rasterio
from rasterio.enums import Resampling

HA_PER_PX = 0.01  # 10 m pixels


def metrics(pred, change, ignore):
    v = ignore == 0
    tp = int(((pred == 1) & (change == 1) & v).sum())
    fp = int(((pred == 1) & (change == 0) & v).sum())
    fn = int(((pred == 0) & (change == 1) & v).sum())
    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    return {"precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(2 * prec * rec / max(prec + rec, 1e-9), 4),
            "iou": round(tp / max(tp + fp + fn, 1), 4),
            "pred_ha": round(int((pred == 1).sum()) * HA_PER_PX, 2),
            "label_ha": round(int((change == 1).sum()) * HA_PER_PX, 2)}


def ndvidiff_native(t1, t2, thr, out_path=None):
    """ΔNDVI < thr at full 10 m res, in 2048-row strips (RAM < ~8 GB)."""
    with rasterio.open(f"data/mosaics/mosaic_{t1}.tif") as a, \
         rasterio.open(f"data/mosaics/mosaic_{t2}.tif") as b:
        H, W = a.height, a.width
        mask = np.zeros((H, W), np.uint8)
        for row0 in range(0, H, 2048):
            rows = min(2048, H - row0)
            win = ((row0, row0 + rows), (0, W))
            d1 = a.read([1, 4], window=win).astype(np.float32)   # red, nir @ t1
            d2 = b.read([1, 4], window=win).astype(np.float32)
            with np.errstate(invalid="ignore", divide="ignore"):
                n1 = (d1[1] - d1[0]) / (d1[1] + d1[0])
                n2 = (d2[1] - d2[0]) / (d2[1] + d2[0])
            m = (n2 - n1) < thr
            m[np.isnan(n1) | np.isnan(n2)] = False
            mask[row0:row0 + rows] = m
    if out_path:
        write_mask(out_path, mask)
    return mask


def write_mask(path, mask_u8):
    with rasterio.open("data/mosaics/mosaic_2021.tif") as ref:
        prof = {**ref.profile, "count": 1, "dtype": "uint8", "compress": "deflate", "nodata": 255}
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(mask_u8, 1)
        dst.build_overviews([2, 4, 8, 16, 32], Resampling.nearest)
        dst.update_tags(ns="rio_overview", resampling="nearest")


def load_eval_truth():
    with rasterio.open("models/labels/change_eval.tif") as s:
        ch = (s.read(1) > 0).astype(np.uint8)
    with rasterio.open("models/labels/ignore_eval.tif") as s:
        ig = s.read(1) > 0
    for yr in (2021, 2024):
        with rasterio.open(f"data/mosaics/mosaic_{yr}.tif") as s:
            for row0 in range(0, s.height, 2048):
                rows = min(2048, s.height - row0)
                ig[row0:row0 + rows] |= np.isnan(s.read(1, window=((row0, row0 + rows), (0, s.width))))
    return ch, ig.astype(np.uint8)


def tune_baseline():
    """Grid-search ΔNDVI threshold on the TRAIN pair at 4× decimation (40 m)."""
    with rasterio.open("models/labels/change_train.tif") as s:
        q = (s.height // 4, s.width // 4)
        ch = (s.read(1, out_shape=q) > 0).astype(np.uint8)
    with rasterio.open("models/labels/ignore_train.tif") as s:
        ig = (s.read(1, out_shape=q) > 0).astype(np.uint8)
    with rasterio.open("data/mosaics/mosaic_2019.tif") as r1, \
         rasterio.open("data/mosaics/mosaic_2021.tif") as r2:
        d1, d2 = r1.read([1, 4], out_shape=q).astype(np.float32), r2.read([1, 4], out_shape=q).astype(np.float32)
    with np.errstate(invalid="ignore", divide="ignore"):
        n1 = (d1[1] - d1[0]) / (d1[1] + d1[0])
        n2 = (d2[1] - d2[0]) / (d2[1] + d2[0])
    dd, nan = n2 - n1, np.isnan(n1) | np.isnan(n2)
    ig2 = ((ig > 0) | nan).astype(np.uint8)
    return max((-0.05, -0.10, -0.15, -0.20, -0.25, -0.30),
               key=lambda t: metrics((dd < t).astype(np.uint8), ch, ig2)["f1"])


if __name__ == "__main__":
    thr = tune_baseline()
    ch, ig = load_eval_truth()
    out = {"pair": "2021→2024", "labels": "PRODES v20260717",
           "ndvidiff_threshold_tuned_on_train": thr}
    base = ndvidiff_native(2021, 2024, thr, "models/mask_ndvidiff_eval.tif")
    ndvidiff_native(2019, 2021, thr, "models/mask_ndvidiff_train.tif")
    out["ndvidiff"] = metrics(base, ch, ig)
    if os.path.exists("models/mask_unet_eval.tif"):
        with rasterio.open("models/mask_unet_eval.tif") as s:
            out["unet"] = metrics((s.read(1) == 1).astype(np.uint8), ch, ig)  # ==1: mask nodata border is 255
    json.dump(out, open("models/metrics_eval.json", "w"), indent=1)
    print(json.dumps(out, indent=1))
