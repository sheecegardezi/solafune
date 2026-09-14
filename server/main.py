import base64
import json
import os

import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from rio_tiler.io import Reader
from rio_tiler.models import ImageData
from rio_tiler.errors import TileOutsideBounds

DATA_DIR = os.environ.get("DATA_DIR", "/data")
MODELS_DIR = os.environ.get("MODELS_DIR", "/models")
YEARS = (2019, 2021, 2024)
PAIRS = ("train", "eval")


def _ramp(anchors, positions):
    # rio-tiler 9.x needs a dict colormap {0..255: rgba}
    a = np.asarray(anchors, float)
    pos = np.asarray(positions, float)
    return {i: tuple(int(np.interp(i, pos, a[:, c])) for c in range(3)) + (255,)
            for i in range(256)}


# anchors at real NDVI values (byte pos = v/0.95*255, matching the rescale below)
NDVI_CMAP = _ramp([[120, 70, 30], [185, 135, 65], [240, 205, 90], [150, 210, 90],
                   [60, 180, 80], [10, 140, 60], [0, 100, 45]],
                  [v / 0.95 * 255 for v in (0, 0.15, 0.30, 0.50, 0.65, 0.80, 0.95)])
MASK_CMAP = {0: (0, 0, 0, 0), 1: (255, 0, 64, 255)}  # nodata 255 → transparent via mask

app = FastAPI(title="Rondônia Deforestation Change Monitor API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# transparent tile outside the mosaic so deck.gl sees empty data, not a fetch error
_EMPTY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII="
)


def _empty() -> Response:
    return Response(_EMPTY_PNG, media_type="image/png")


def _adjust(img: ImageData, brightness: float, contrast: float, saturation: float) -> ImageData:
    if (brightness, contrast, saturation) == (1.0, 1.0, 1.0):
        return img
    # write in place: reassigning img.array collapses the (3,h,w) mask and render() 500s
    a = img.array.data.astype(np.float32) * brightness
    a = (a - 127.5) * contrast + 127.5
    if saturation != 1.0:
        gray = a.mean(axis=0, keepdims=True)
        a = gray + (a - gray) * saturation
    img.array.data[...] = np.clip(a, 0, 255).astype("uint8")
    return img


@app.get("/api/health")
def healthz():
    return {"status": "ok"}


@app.get("/tiles/{product}/{year}/{z}/{x}/{y}.png")
def tile(product: str, year: int, z: int, x: int, y: int,
         brightness: float = Query(1.0, ge=0.25, le=4.0),
         contrast: float = Query(1.0, ge=0.25, le=4.0),
         saturation: float = Query(1.0, ge=0.25, le=4.0)):
    if product not in ("rgb", "ndvi") or year not in YEARS:
        raise HTTPException(404, "unknown product/year")
    try:
        with Reader(f"{DATA_DIR}/mosaics/mosaic_{year}.tif") as src:
            if product == "rgb":
                img = src.tile(x, y, z, indexes=(1, 2, 3))
                img.rescale(in_range=[[0, 0.3]] * 3, out_range=[[0, 255]] * 3)  # reflectance p99.5≈0.18
                _adjust(img, brightness, contrast, saturation)
                png = img.render(img_format="PNG")
            else:
                img = src.tile(x, y, z, indexes=(1, 4))  # red, nir
                with np.errstate(invalid="ignore", divide="ignore"):
                    ndvi = ((img.array[1] - img.array[0]) / (img.array[1] + img.array[0])).astype("float32")
                out = ImageData(ndvi[None], bounds=img.bounds, crs=img.crs)
                out.rescale(in_range=[[0, 0.95]], out_range=[[0, 255]])
                png = out.render(img_format="PNG", colormap=NDVI_CMAP)
    except TileOutsideBounds:
        return _empty()
    return Response(png, media_type="image/png")


@app.get("/tiles/mask/{model}/{pair}/{z}/{x}/{y}.png")
def mask_tile(model: str, pair: str, z: int, x: int, y: int):
    if pair not in PAIRS:
        raise HTTPException(404, "unknown pair")
    path = f"{MODELS_DIR}/mask_{model}_{pair}.tif"
    if not os.path.exists(path):
        raise HTTPException(404, "mask not computed yet")
    try:
        with Reader(path) as src:
            img = src.tile(x, y, z)
    except TileOutsideBounds:
        return _empty()
    return Response(img.render(img_format="PNG", colormap=MASK_CMAP), media_type="image/png")


@app.get("/api/evaluate")
def evaluate():
    p = f"{MODELS_DIR}/metrics_eval.json"
    if not os.path.exists(p):
        raise HTTPException(404, "eval not run yet")
    return JSONResponse(json.load(open(p)))


def _ha_in_bbox(path, bbox):
    w, s, e, n = map(float, bbox.split(","))
    bw, bs, be, bn = transform_bounds("EPSG:4326", "EPSG:32720", w, s, e, n, densify_pts=21)
    with rasterio.open(path) as src:
        win = from_bounds(bw, bs, be, bn, src.transform)
        oh = max(1, min(1024, int(win.height)))
        ow = max(1, min(1024, int(win.width)))
        a = src.read(1, window=win, out_shape=(oh, ow))
        px_ha = (abs(be - bw) / ow) * (abs(bn - bs) / oh) / 10_000
    return round(float((a == 1).sum()) * px_ha, 1)  # ==1: mask nodata border is 255


@app.get("/api/stats")
def stats(pair: str, bbox: str):
    if pair not in PAIRS:
        raise HTTPException(404, "unknown pair")
    out = {}
    for name, sub in (("unet_ha", f"mask_unet_{pair}.tif"),
                      ("ndvidiff_ha", f"mask_ndvidiff_{pair}.tif"),
                      ("prodes_ha", f"labels/change_{pair}.tif")):
        p = f"{MODELS_DIR}/{sub}"
        out[name] = _ha_in_bbox(p, bbox) if os.path.exists(p) else 0.0
    return out


def _geojson(path):
    if not os.path.exists(path):
        raise HTTPException(404, "not computed yet")
    return FileResponse(path, media_type="application/geo+json")


@app.get("/api/prodes")
def prodes(pair: str):
    if pair not in PAIRS:
        raise HTTPException(404, "unknown pair")
    return _geojson(f"{DATA_DIR}/ground_truth/pairs/prodes_{pair}.geojson")


@app.get("/api/hotspots")
def hotspots(pair: str):
    if pair not in PAIRS:
        raise HTTPException(404, "unknown pair")
    return _geojson(f"{MODELS_DIR}/hotspots_{pair}.geojson")
