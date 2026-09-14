export type Pair = "train" | "eval";
export const PAIR_YEARS: Record<Pair, [number, number]> = { train: [2019, 2021], eval: [2021, 2024] };

// Each slot maps to the change window that ENDS at it. The 2019 baseline epoch
// has no window of its own, so it is not a pickable slot.
export const TIMESLOTS = [2021, 2024] as const;
export type Timeslot = (typeof TIMESLOTS)[number];
export const SLOT_WINDOW: Record<Timeslot, Pair> = { 2021: "train", 2024: "eval" };
export const SLOT_TAG: Record<Timeslot, string> = { 2021: "TRAIN", 2024: "EVAL" };
export const API: string = import.meta.env.VITE_API ?? "";
export const DEFAULT_BBOX: Bbox = [-62.81, -11.07, -61.59, -10.03];

export type Bbox = [number, number, number, number];

export interface ViewStats {
  unet_ha: number;
  ndvidiff_ha: number;
  prodes_ha: number;
}

// Every fetch degrades to null instead of throwing: the UI renders an offline
// state rather than crashing when the API or the network is unreachable.
async function getJson(url: string): Promise<any | null> {
  try {
    const r = await fetch(url);
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

export async function fetchHealth(): Promise<boolean> {
  return (await getJson(`${API}/api/health`))?.status === "ok";
}

export async function fetchStats(pair: Pair, bbox: Bbox): Promise<ViewStats | null> {
  return getJson(`${API}/api/stats?pair=${pair}&bbox=${bbox.join(",")}`);
}

export interface Hotspot {
  id: number;
  pair: string;
  area_ha: number;
  prodes_frac: number;
  status: "prodes_match" | "model_only";
  centroid: [number, number];
}

// Full GeoJSON features (not just properties): the selected one is re-painted
// with an outline on the map, so its geometry must survive the fetch.
export interface HotspotFeature {
  type: "Feature";
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
  properties: Hotspot;
}

export async function fetchHotspots(pair: Pair): Promise<HotspotFeature[]> {
  const j = await getJson(`${API}/api/hotspots?pair=${pair}`);
  return (j?.features ?? []) as HotspotFeature[];
}
