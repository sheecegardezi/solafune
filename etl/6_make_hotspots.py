"""Polygonize the change mask into clickable hotspot GeoJSON.

Each connected component >= 6.25 ha becomes a feature with area, centroid and
PRODES overlap. Outputs models/hotspots_{train,eval}.geojson (EPSG:4326,
<= max_features by area).
"""
import json

import rasterio
from rasterio.features import shapes
from rasterio.warp import transform_geom
from shapely.geometry import shape, mapping


def polygonize(mask_path, labels_path, pair, min_area_ha=6.25, max_features=200):
    with rasterio.open(mask_path) as msrc, rasterio.open(labels_path) as lsrc:
        mask, labels = msrc.read(1), lsrc.read(1)
        assert msrc.shape == lsrc.shape and msrc.transform == lsrc.transform, \
            "mask and labels grids must match"
        px_ha = abs(msrc.transform.a * msrc.transform.e) / 10_000
        feats = []
        for geom, val in shapes(mask, mask=(mask == 1), transform=msrc.transform):
            if val != 1:
                continue
            poly = shape(geom)
            area_ha = round(poly.area / abs(msrc.transform.a * msrc.transform.e) * px_ha, 2)
            if area_ha < min_area_ha:
                continue
            rows, cols = rasterio.features.rasterize(
                [(geom, 1)], out_shape=mask.shape, transform=msrc.transform).nonzero()
            prodes_frac = round(float((labels[rows, cols] == 1).mean()), 3)
            c = shape(transform_geom(msrc.crs, "EPSG:4326", mapping(poly.centroid)))
            feats.append({
                "type": "Feature",
                "geometry": transform_geom(msrc.crs, "EPSG:4326", geom),
                "properties": {
                    "pair": pair, "area_ha": area_ha,
                    "prodes_frac": prodes_frac,
                    "status": "prodes_match" if prodes_frac >= 0.5 else "model_only",
                    "centroid": [round(c.x, 6), round(c.y, 6)],
                },
            })
    feats.sort(key=lambda f: -f["properties"]["area_ha"])
    for i, f in enumerate(feats):
        f["properties"]["id"] = i
    return {"type": "FeatureCollection", "features": feats[:max_features]}


if __name__ == "__main__":
    for pair in ("train", "eval"):
        gj = polygonize(f"models/mask_unet_{pair}.tif",
                        f"models/labels/change_{pair}.tif", pair)
        out = f"models/hotspots_{pair}.geojson"
        json.dump(gj, open(out, "w"))
        tot = sum(f["properties"]["area_ha"] for f in gj["features"])
        print(f"{pair}: {len(gj['features'])} hotspots, {tot:,.0f} ha -> {out}", flush=True)
