"""Regenerate AOI-clipped PRODES ground truth from the official TerraBrasilis
shapefiles (release v20260717) downloaded into
data/ground_truth/official_v20260717/.

Outputs (EPSG:4326, GeoJSON + GeoPackage), clipped to the union of the
documented AOI bbox and the mosaic extent:
  prodes_yearly_deforestation_v20260717.*      main annual layer
  prodes_accumulated_2007_v20260717.*          pre-2008 accumulated clearing
  prodes_yearly_small_1_625ha_v20260717.*      1-6.25 ha polygons (optional)
  rondonia_aoi.geojson                         clip footprint (provenance)
"""
import geopandas as gpd
import rasterio
from rasterio.warp import transform_bounds
from shapely.geometry import box

OFFICIAL = "data/ground_truth/official_v20260717"
OUT = "data/ground_truth"
DOC_BBOX = (-62.80, -11.05, -61.60, -10.05)  # from rondonia_download_plan.md

LAYERS = {
    "prodes_yearly_deforestation_v20260717": f"{OFFICIAL}/yearly_deforestation_biome_amazonia_v20260717.shp",
    "prodes_accumulated_2007_v20260717": f"{OFFICIAL}/accumulated_deforestation_2007_biome_amazonia_v20260717.shp",
    "prodes_yearly_small_1_625ha_v20260717": f"{OFFICIAL}/yearly_deforestation_smaller_than_625ha_biome_amazonia_v20260717.shp",
}

# clip footprint = documented AOI bbox ∪ mosaic extent
with rasterio.open("data/mosaics/mosaic_2021.tif") as src:
    mb = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
clip_box = box(min(DOC_BBOX[0], mb[0]), min(DOC_BBOX[1], mb[1]),
               max(DOC_BBOX[2], mb[2]), max(DOC_BBOX[3], mb[3]))
gpd.GeoDataFrame(
    {"name": ["rondonia_aoi"]}, geometry=[clip_box], crs="EPSG:4326"
).to_file(f"{OUT}/rondonia_aoi.geojson", driver="GeoJSON")
print(f"clip footprint: {clip_box.bounds}")

for name, shp in LAYERS.items():
    gdf = gpd.read_file(shp, bbox=clip_box.bounds).clip(clip_box)
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
    gdf.to_file(f"{OUT}/{name}.gpkg", driver="GPKG")
    gdf.to_file(f"{OUT}/{name}.geojson", driver="GeoJSON")
    if "year" in gdf.columns:
        print(f"{name}: {len(gdf)} polygons | by year: {gdf['year'].value_counts().sort_index().to_dict()}")
    else:
        print(f"{name}: {len(gdf)} polygons")
