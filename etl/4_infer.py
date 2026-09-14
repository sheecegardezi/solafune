"""Full-mosaic U-Net inference → models/mask_unet_{train,eval}.tif (uint8 COG).

Non-overlapping 256-px windows, fixed 0.5 threshold, PRODES 6.25 ha minimum
mapping unit filter. Border pixels not covered by a window are nodata (255).
"""
import numpy as np
import rasterio
import torch
from scipy import ndimage

train = __import__("3_train")  # digit-prefixed module: not importable via `from`
DEV, PATCH = train.DEV, train.PATCH
build_model, load_pair, normalize = train.build_model, train.load_pair, train.normalize
THR = 0.5


def mmu_filter(mask_u8, min_px=625):
    """Drop change blobs < 6.25 ha (625 px @ 10 m), PRODES minimum mapping unit."""
    lab, n = ndimage.label(mask_u8 == 1)
    if n == 0:
        return mask_u8
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    out = np.where(sizes[lab] >= min_px, mask_u8, 0).astype(np.uint8)
    out[mask_u8 == 255] = 255
    return out


def infer_pair(name, model):
    with rasterio.open(f"data/mosaics/mosaic_{train.PAIR_YEARS[name][1]}.tif") as ref:
        prof = {**ref.profile, "count": 1, "dtype": "uint8", "compress": "deflate",
                "nodata": 255}
        H, W = ref.height, ref.width
    mask = np.full((H, W), 255, np.uint8)
    for r in range(0, H - PATCH + 1, PATCH):
        for c in range(0, W - PATCH + 1, PATCH):
            x, _, _ = load_pair(name, c, r)
            with torch.no_grad():
                p = torch.sigmoid(model(torch.from_numpy(normalize(x)[None]).to(DEV)))
            mask[r:r + PATCH, c:c + PATCH] = (p[0, 0].cpu().numpy() > THR).astype(np.uint8)
    mask = mmu_filter(mask)
    with rasterio.open(f"models/mask_unet_{name}.tif", "w", **prof) as dst:
        dst.write(mask, 1)
        dst.build_overviews([2, 4, 8, 16, 32], rasterio.enums.Resampling.nearest)
        dst.update_tags(ns="rio_overview", resampling="nearest")
    n = int((mask == 1).sum())
    print(f"{name}: deforested px={n:,} ≈ {n * 0.01:,.0f} ha", flush=True)


if __name__ == "__main__":
    ck = torch.load("models/unet.pt", map_location=DEV, weights_only=True)
    model = build_model()
    model.load_state_dict(ck["state_dict"])
    model.eval().to(DEV)
    infer_pair("train", model)
    infer_pair("eval", model)
