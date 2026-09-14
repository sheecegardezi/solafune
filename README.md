# Rondônia Deforestation Change Monitor the story in simple steps

A satellite + AI demo that finds **new deforestation** in the Amazon and shows it on an
interactive map, scored against official government labels.

## 1. Why deforestation

Deforestation is one of the biggest environmental problems of our time it drives climate
change, biodiversity loss and land conflict. For governments it is very hard to track: the
affected areas are enormous, remote, and often inaccessible by road, so ground patrols can
never cover them. **Satellites are the best solution** they image every location on a
regular revisit, for free, regardless of terrain or borders.

## 2. Why the Amazon rainforest

I chose the Amazon because it is the **best-studied deforestation location on Earth**.
Brazil's space agency (INPE) has mapped Amazon deforestation officially for decades through
the **PRODES** program, which means there are trusted official labels to train a model on
and to score it against. My study area is a ~134 × 113 km AOI in **Rondônia, Brazil** a
known deforestation frontier.

## 3. Where I got the data

All imagery came from the **Microsoft Planetary Computer** (a free STAC catalog no
credentials, no cost):

- **Sentinel-2 L2A** the main sensor (10 m resolution, ~5-day revisit): **270 scenes**.
- **Landsat Collection 2 L2** 83 scenes, to demonstrate multi-source aggregation.
- **Sentinel-1 RTC radar** 80 scenes, all-weather data (downloaded, demo only).

I downloaded three epochs **2019, 2021 and 2024** always in the **dry season
(June–August)** so seasonal green-up never gets confused with real forest change.

## 4. Main preprocessing

1. **Clipped every scene to the AOI on download** never stored full tiles I don't need.
2. **Masked clouds and shadows** on each Sentinel-2 scene using its SCL (scene
   classification) band.
3. **Built one clean median composite per year** from all remaining scenes: 4 bands
   (red, green, blue, near-infrared) at 10 m, saved as cloud-optimized GeoTIFF **and**
   Zarr copies.
4. For the model: **stacked two yearly mosaics (before + after) into one 8-channel input**,
   z-score normalized it, and cut it into **256×256 px patches** with overlapping
   (stride-128) sampling so the rare deforestation patches got 4× more training examples.

## 5. Where I got the label data

Labels are the **official INPE PRODES v20260717 shapefiles**, downloaded from
TerraBrasilis (terrabrasilis.dpi.inpe.br) and clipped to my AOI.

- **Label rule:** a pixel is "new deforestation" if it falls inside a PRODES polygon dated
  *after* the before-mosaic and *up to* the after-mosaic year.
- **Ignore rule:** ambiguous polygons (cut in the before-year itself, or after the
  after-mosaic) are excluded from scoring rather than counted as errors.

## 6. The model I fine-tuned

A **U-Net** (from `segmentation-models-pytorch`) with an **ImageNet-pretrained encoder**,
adapted to the 8-channel two-epoch input fine-tuned, not trained from scratch.

- **Loss:** Dice + binary cross-entropy with 10× positive weight (only ~1% of pixels are
  deforestation, so the model had to be pushed to care about them).
- **Final model:** a **single U-Net** (resnet34 encoder) with a fixed 0.5
  decision threshold, plus a minimum-area filter matching PRODES' own 6.25 ha
  mapping rule.
- **Fair evaluation:** trained on the **2019→2021** pair only; scored on the **held-out
  2021→2024** pair that was never used for training or tuning.
- **Result:** **F1 0.4735 / IoU 0.3102** vs **0.2051** for a tuned NDVI-difference
  baseline more than double the F1, at 4× the precision.

## 7. Turning the result into a service

Inference runs **offline**; every model output is pre-computed into rasters. The runtime is
a small **Python backend FastAPI + rio-tiler** that serves those results as dynamic map
tiles and JSON. It is **CPU-only**: no GPU is needed to serve the app.

- `/tiles/...` RGB mosaic, NDVI and model-mask tiles rendered on request
- `/api/stats` deforested hectares inside the current map view
- `/api/evaluate` the held-out evaluation metrics
- `/api/prodes` official PRODES label polygons
- `/api/hotspots` ranked deforestation hotspots

## 8. Other layers worth showing (and how they were made)

- **NDVI** (vegetation greenness) computed on the fly from the mosaics' red/NIR bands and
  served as tiles; makes cleared land instantly visible.
- **PRODES polygons** the official labels clipped to the AOI, served as GeoJSON so the
  map can draw them over the imagery.
- **Hotspots** the model's change mask was polygonized and the clearings **ranked by
  size** (`etl/6_make_hotspots.py`), served as GeoJSON; each one is a clickable card on the
  map.
- **Hectares in view** the server does real raster statistics in the correct UTM
  projection for the visible bbox, so every area number on screen is a true measurement.

All of it loads through the same Python server the browser never touches a raw GeoTIFF.

## 9. The frontend

**React 19 + deck.gl 9**, built with Vite (tree-shaken production bundle) and served as
static files behind nginx.

- **All user state lives in one place** the app-level React state holds the selected
  epoch, layer toggles, map viewport, stats, metrics and selected hotspot, so every panel
  reacts immediately to every map interaction.
- **deck.gl** renders the raster tiles and vector polygons in the browser with WebGL —
  smooth pan/zoom over ~150-megapixel mosaics without loading them whole.
- Map-first UI: epoch picker (2019 baseline / 2021 train / 2024 eval), layer switches with
  per-layer explanations, a before/after **swipe**, hotspot cards, and live hectares +
  evaluation panels.

## 10. The point of it all

Show **all deforested areas over time** on one map, so a government official can see where
and how much forest was lost in each period, spot the **most-affected areas** through the
ranked hotspots, prioritize **surveillance** where it matters, and build an **action plan**
from evidence instead of guesswork.

---

## Run it

```bash
docker compose -f compose.gpu.yaml up           # API :8000 + frontend :5173
# open http://localhost:5173
```

The whole offline pipeline is numbered in `etl/` (1 ground truth → 2 training data →
3 train → 4 infer → 5 eval → 6 hotspots). Tests: `pytest
etl/tests` and `pytest server/tests`.

## Honest limits

- Single AOI and one training epoch pair no geographic or temporal generalization claim.
- The model **under-predicts total area ~1.6×** (recall 0.40) it finds real clearings but
  misses some.
