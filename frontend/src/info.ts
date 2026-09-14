// Content for the map UI: what each layer is, where it comes from, and how to
// read it. Every claim traces to the repo (MODEL_CARD.md) or the API contract.
// Keep the wording plain — one short idea per line, no jargon.

export interface LayerDoc {
  name: string;
  tag: string; // short instrument-rail label
  brief: string; // what am I looking at
  source: string;
  read: string; // how to read it
}

export const LAYER_DOCS: Record<string, LayerDoc> = {
  rgb: {
    name: "Satellite photo (RGB)",
    tag: "RGB",
    brief: "A normal satellite photo of the area, from the year you picked (2021 or 2024).",
    source: "Sentinel-2 satellite images, 10 m detail, averaged over Jun–Aug.",
    read: "New pale patches that used to be green forest are likely fresh clearing. The mask layer shows what the model found there.",
  },
  ndvi: {
    name: "Plant health (NDVI)",
    tag: "NDVI",
    brief: "A map of how much living vegetation each pixel has.",
    source: "Calculated from the red and infrared light in the selected satellite photo.",
    read: "Deep green = healthy forest. Yellow = grass or sparse plants. Brown = bare soil or fresh clearing.",
  },
  mask: {
    name: "NDVI-diff change mask",
    tag: "NDVI-DIFF",
    brief: "Red areas are where a simple before/after comparison thinks forest was cut down in the selected period.",
    source: "“NDVI-diff” compares plant health (NDVI) between the two years of the window (2019→2021 or 2021→2024). The AI model's take on the same period is the Hotspots layer.",
    read: "Red overlay = likely deforestation by NDVI change. Turn on PRODES to see where it agrees with the official survey — and where it is wrong.",
  },
  prodes: {
    name: "Official deforestation (PRODES)",
    tag: "PRODES",
    brief: "Confirmed deforestation mapped by Brazil's space agency (INPE). This is the official record the models are judged against.",
    source: "PRODES survey polygons, clipped to this region.",
    read: "Red outlines = officially confirmed clearings for the selected period. The 2021→2024 period was never used in training.",
  },
  hotspots: {
    name: "Detected clearings",
    tag: "HOTSPOTS",
    brief: "Each clearing the model found, drawn as a shape you can click. Listed biggest first.",
    source: "Made by grouping neighboring red pixels from the model result (clearings under 6.25 ha are ignored).",
    read: "Teal = also confirmed by PRODES. Orange = found by the model only. Click one to see its size and details.",
  },
};
