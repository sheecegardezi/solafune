import { BitmapLayer, GeoJsonLayer } from "@deck.gl/layers";
import { TileLayer } from "@deck.gl/geo-layers";
import { API, type Bbox, type HotspotFeature, type Pair, type Timeslot } from "./api";

// Basemap styles served by our own GCP tile server (PNG raster tiles,
// OpenMapTiles schema). paper = positron, terra = terrain.
export const BASEMAP_STYLES = ["paper", "terra"] as const;
export type Basemap = (typeof BASEMAP_STYLES)[number] | "off";
export const TILES_ORIGIN =
  import.meta.env.VITE_TILES_ORIGIN ?? "https://tiles.geocanvas.dev";

export interface DisplaySettings {
  brightness: number;   // 0.25..4, 1 = untouched
  contrast: number;
  saturation: number;
  maskOpacity: number;  // 0..1
  ndviOpacity: number;  // 0..1
}
export const DEFAULT_DISPLAY: DisplaySettings = {
  brightness: 1, contrast: 1, saturation: 1, maskOpacity: 0.65, ndviOpacity: 0.8,
};
export function imageryQuery(d: DisplaySettings): string {
  // defaults omitted: bit-identical tiles hit the browser cache they already warmed
  const p = new URLSearchParams();
  if (d.brightness !== 1) p.set("brightness", String(d.brightness));
  if (d.contrast !== 1) p.set("contrast", String(d.contrast));
  if (d.saturation !== 1) p.set("saturation", String(d.saturation));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export interface LayerToggles {
  rgb: boolean;
  ndvi: boolean;
  mask: boolean;
  prodes: boolean;
  hotspots: boolean;
}

export interface Epoch {
  slot: Timeslot;
  pair: Pair;
}

// Mosaic is a Jun–Aug median composite at 10 m (EPSG:32720): native detail ends
// around z12–13, so tile fetches cap at z13 (deck.gl reuses z13 tiles when zoomed
// further in). The minZoom/extent pair is what keeps the map alive when zooming
// out: with minZoom alone (no extent) deck.gl returns an EMPTY tileset below it
// and every layer vanishes (z<6 bug); with extent set, zoom-out below minZoom
// clamps to minZoom tiles and scales them down instead. minZoom 5 is as low as
// the backend can safely serve — the UTM→WebMercator WarpedVRT read gets
// exponentially slower at z≤3 (z3≈2 s, z2≈25 s, z1≈52 s, z0 minutes), while
// z5 is ~0.1 s. Dropping minZoom entirely would fire those requests because of
// maxRequests 0 (disables deck.gl's throttled request queue on purpose: a tile still
// queued when it loses its selected/visible flags is cancelled by priority
// (getRequestPriority → -1 → null token) and Tileset2D never re-requests it —
// _getTile reloads only on create or needsReload, and loadData() already cleared
// needsReload. Switching timeslots or zooming mid-load then freezes the layer on
// stale imagery for good (verified empirically; it also hit pan/zoom and the old
// pair selector). The browser's own per-host queue is enough for the ~80 tiles a
// view needs, and the abort logic already discards stale-year responses).
// Mosaic footprint in lng/lat (rio-tiler bounds of mosaic_2021.tif, rounded out).
export const MOSAIC_EXTENT: [number, number, number, number] = [-62.82, -11.07, -61.58, -10.03];
const TILE_OPTS = { minZoom: 5, maxZoom: 13, tileSize: 256, maxRequests: 0 } as const;

// Pure function of (epoch, toggles, basemap, display, selected) —
// callers memoize with useMemo so deck.gl only rebuilds GPU resources when
// inputs actually change.
export function makeLayers(
  epoch: Epoch,
  layers: LayerToggles,
  selected: HotspotFeature | null,
  basemap: Basemap = "off",
  display: DisplaySettings = DEFAULT_DISPLAY,
) {
  const { slot, pair } = epoch;
  const q = imageryQuery(display);
  const L: any[] = [];
  // imagery: clamp to the mosaic footprint (minZoom+extent → zoom-out reuses
  // minZoom tiles). basemap: worldwide, renders at every zoom (no minZoom).
  const tile = (id: string, url: string, opacity = 1, imagery = true) =>
    new TileLayer({
      id,
      data: url,
      ...(imagery ? { ...TILE_OPTS, extent: MOSAIC_EXTENT } : { maxZoom: TILE_OPTS.maxZoom, tileSize: TILE_OPTS.tileSize, maxRequests: TILE_OPTS.maxRequests }),
      opacity,
      renderSubLayers: (p: any) => {
        // canonical deck.gl 9 TileLayer→BitmapLayer pattern: tile image goes in
        // `image`, geographic extent in `bounds` (passing props raw breaks:
        // BitmapLayer reads `data` as an attribute container)
        const [[w, s], [e, n]] = p.tile.boundingBox;
        return new BitmapLayer(p, { data: undefined, image: p.data, bounds: [w, s, e, n] });
      },
    });
  // basemap fills the space around the mosaic extent, at the bottom of the stack
  if (basemap !== "off")
    L.push(tile("basemap", `${TILES_ORIGIN}/styles/${basemap}/{z}/{x}/{y}.png`, 1, false));
  if (layers.rgb) L.push(tile(`rgb-${slot}`, `${API}/tiles/rgb/${slot}/{z}/{x}/{y}.png${q}`));
  if (layers.ndvi) L.push(tile(`ndvi-${slot}`, `${API}/tiles/ndvi/${slot}/{z}/{x}/{y}.png`, display.ndviOpacity));
  if (layers.mask)
    L.push(tile("mask-ndvidiff", `${API}/tiles/mask/ndvidiff/${pair}/{z}/{x}/{y}.png`, display.maskOpacity));
  if (layers.prodes)
    L.push(new GeoJsonLayer({
      id: "prodes",
      data: `${API}/api/prodes?pair=${pair}`,
      stroked: true,
      filled: true,
      getFillColor: [193, 39, 45, 35],
      getLineColor: [193, 39, 45, 230],
      lineWidthMinPixels: 1,
    }));
  if (layers.hotspots)
    L.push(new GeoJsonLayer({
      id: `hotspots-${pair}`,
      data: `${API}/api/hotspots?pair=${pair}`,
      pickable: true,
      stroked: true,
      filled: true,
      getFillColor: (f: any) => f.properties.status === "prodes_match" ? [24, 123, 113, 90] : [245, 130, 32, 90],
      getLineColor: (f: any) => f.properties.status === "prodes_match" ? [24, 123, 113, 230] : [245, 130, 32, 230],
      lineWidthMinPixels: 1.5,
    }));
  // outline the selected hotspot so the detail card and the map agree on which
  // clearing is open — ink stroke over a paper halo, readable on any fill
  if (selected) {
    L.push(new GeoJsonLayer({
      id: "hotspot-selected",
      data: { type: "FeatureCollection", features: [selected] },
      stroked: true,
      filled: false,
      getLineColor: [255, 253, 245, 255],
      getLineWidth: 5,
      lineWidthMinPixels: 5,
    }));
    L.push(new GeoJsonLayer({
      id: "hotspot-selected-ink",
      data: { type: "FeatureCollection", features: [selected] },
      stroked: true,
      filled: false,
      getLineColor: [38, 79, 73, 255],
      getLineWidth: 2,
      lineWidthMinPixels: 2,
    }));
  }
  return L;
}

export function bboxOf(v: { longitude: number; latitude: number; zoom: number }): Bbox {
  const span = 360 / 2 ** v.zoom;
  return [v.longitude - span / 2, v.latitude - span / 3, v.longitude + span / 2, v.latitude + span / 3];
}
