import { useEffect, useMemo, useRef, useState } from "react";
import { DeckGL } from "@deck.gl/react";
import { WebMercatorViewport, type MapViewState } from "@deck.gl/core";
import { BASEMAP_STYLES, DEFAULT_DISPLAY, bboxOf, makeLayers, type Basemap, type DisplaySettings, type Epoch, type LayerToggles } from "./layers";
import {
  DEFAULT_BBOX, PAIR_YEARS, SLOT_TAG, SLOT_WINDOW, TIMESLOTS, fetchHealth, fetchHotspots, fetchStats,
  type Bbox, type HotspotFeature, type Timeslot, type ViewStats,
} from "./api";
import { LAYER_DOCS } from "./info";

const INITIAL_VIEW_STATE: MapViewState = { longitude: -62.1981, latitude: -10.5501, zoom: 9.8, pitch: 0, bearing: 0 };
const LAYER_ORDER: (keyof LayerToggles)[] = ["rgb", "ndvi", "mask", "prodes", "hotspots"];
const LAYER_CHIP: Record<keyof LayerToggles, { c: string; outline?: boolean }> = {
  rgb: { c: "#376d34" },
  ndvi: { c: "#a4561d" },
  mask: { c: "#c1272d" },
  hotspots: { c: "#187b71" },
  prodes: { c: "#c1272d", outline: true },
};
const fmt = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 0 });const S = {
  viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true,
} as const;
const IconInfo = () => (
  <svg {...S}><circle cx="12" cy="12" r="9" /><path d="M12 11.2v5" /><circle cx="12" cy="7.9" r=".7" fill="currentColor" stroke="none" /></svg>
);
const IconPlus = () => <svg {...S}><path d="M12 6v12M6 12h12" /></svg>;
const IconMinus = () => <svg {...S}><path d="M6 12h12" /></svg>;
const IconFrame = () => (
  <svg {...S}><path d="M4 9V5.5A1.5 1.5 0 0 1 5.5 4H9M15 4h3.5A1.5 1.5 0 0 1 20 5.5V9M20 15v3.5a1.5 1.5 0 0 1-1.5 1.5H15M9 20H5.5A1.5 1.5 0 0 1 4 18.5V15" /></svg>
);
const IconClose = () => <svg {...S}><path d="m6.5 6.5 11 11M17.5 6.5l-11 11" /></svg>;
const IconLayers = () => (
  <svg {...S}><path d="M12 3.5 20.5 8.25 12 13 3.5 8.25 12 3.5z" /><path d="m4.9 12.5 7.1 4 7.1-4" /><path d="m4.9 16.4 7.1 4 7.1-4" /></svg>
);
const IconChevron = () => <svg {...S} className="chev"><path d="m7 10 5 5 5-5" /></svg>;

export default function App() {
  const [slot, setSlot] = useState<Timeslot>(2024);
  const [toggles, setToggles] = useState<LayerToggles>({
    rgb: true, ndvi: false, mask: true, prodes: true, hotspots: true,
  });
  const [basemap, setBasemap] = useState<Basemap>("paper");
  const [display, setDisplay] = useState<DisplaySettings>(DEFAULT_DISPLAY);
  const [displayDraft, setDisplayDraft] = useState<DisplaySettings>(DEFAULT_DISPLAY);
  const [viewState, setViewState] = useState<MapViewState>(INITIAL_VIEW_STATE);
  const [bbox, setBbox] = useState<Bbox | null>(null);
  const [stats, setStats] = useState<ViewStats | null>(null);
  const [hotspots, setHotspots] = useState<HotspotFeature[]>([]);
  const [hotspot, setHotspot] = useState<HotspotFeature | null>(null);
  const [apiUp, setApiUp] = useState<boolean | null>(null);
  const [openDoc, setOpenDoc] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);

  const pair = SLOT_WINDOW[slot];
  const epoch = useMemo<Epoch>(() => ({ slot, pair }), [slot, pair]);

  // memoized so per-frame rerenders from controlled viewState stay cheap —
  // deck.gl only touches GPU resources when inputs actually change
  const layers = useMemo(
    () => makeLayers(epoch, toggles, hotspot, basemap, display),
    [epoch, toggles, hotspot, basemap, display]);

  // commit debounced — dragging a slider mustn't refetch tiles per pixel
  useEffect(() => {
    const t = setTimeout(() => setDisplay(displayDraft), 200);
    return () => clearTimeout(t);
  }, [displayDraft]);

  const handleViewStateChange = ({ viewState: v }: { viewState: unknown }) => {
    const next = v as MapViewState;
    setViewState(next);
    setBbox(bboxOf(next));
  };
  const zoomBy = (d: number) =>
    setViewState((v) => ({ ...v, zoom: Math.min(18, Math.max(3, v.zoom + d)), transitionDuration: 450 }) as MapViewState);
  const resetView = () => setViewState({ ...INITIAL_VIEW_STATE, transitionDuration: 600 } as MapViewState);
  const flyTo = (c: [number, number]) =>
    setViewState((v) => ({ ...v, longitude: c[0], latitude: c[1], zoom: Math.max(v.zoom, 12), transitionDuration: 600 }) as MapViewState);

  useEffect(() => {
    let alive = true;
    const beat = () => fetchHealth().then((ok) => alive && setApiUp(ok));
    beat();
    const t = setInterval(beat, 15000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  // debounced — fetching per navigation frame would spam the API
  useEffect(() => {
    const t = setTimeout(() => { fetchStats(pair, bbox ?? DEFAULT_BBOX).then(setStats); }, 300);
    return () => clearTimeout(t);
  }, [pair, bbox]);

  useEffect(() => {
    if (toggles.hotspots) fetchHotspots(pair).then(setHotspots);
    else { setHotspots([]); setHotspot(null); }
  }, [toggles.hotspots, pair]);

  const handleMapClick = (info: any) => {
    const f = info.object;
    setHotspot(info.layer?.id.startsWith("hotspots-") && f?.properties ? (f as HotspotFeature) : null);
  };

  const hotspotsOn = toggles.hotspots && hotspots.length > 0;

  // the detail card floats beside the selected clearing: project its centroid
  // through the live viewport and clamp the card inside the window — flipping
  // to the left of the point when the right hotspot rail is in the way.
  const cardPos = useMemo(() => {
    if (!hotspot) return null;
    const vp = new WebMercatorViewport({
      ...viewState,
      width: window.innerWidth,
      height: window.innerHeight,
    });
    const [x, y] = vp.project(hotspot.properties.centroid);
    const w = window.innerWidth, h = window.innerHeight;
    const rail = hotspotsOn ? 322 : 0; // rail width + right gutter
    let left = x + 18;
    if (left + 272 > w - rail) left = Math.max(x - 272 - 18, 12);
    return {
      left,
      top: Math.min(Math.max(y - 90, 12), h - 232),
    };
  }, [hotspot, viewState, hotspotsOn]);

  const dialogRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!openDoc) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpenDoc(null); };
    window.addEventListener("keydown", onKey);
    dialogRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [openDoc]);

  const toggleLayer = (k: keyof LayerToggles) =>
    setToggles((t) => ({ ...t, [k]: !t[k] }));

  const maxHa = stats ? Math.max(stats.unet_ha, stats.ndvidiff_ha, stats.prodes_ha, 1) : 1;

  const Slider = ({ k, label, min, max }: { k: keyof DisplaySettings; label: string; min: number; max: number }) => (
    <div className="field-row slider-row">
      <label htmlFor={`disp-${k}`}>{label}</label>
      <input
        id={`disp-${k}`} type="range" min={min} max={max} step={0.05}
        value={displayDraft[k]}
        onChange={(e) => setDisplayDraft((d) => ({ ...d, [k]: Number(e.target.value) }))}
      />
      <span className="val">{displayDraft[k].toFixed(2)}</span>
    </div>
  );

  return (
    <main className="map-app">
      <DeckGL
        viewState={viewState}
        controller
        onViewStateChange={handleViewStateChange}
        onClick={handleMapClick}
        layers={layers}
        style={{ position: "absolute", inset: "0" }}
      />

      <header className="masthead">
        <p className="eyebrow">Satellite change detection · 10 m</p>
        <h1>Rondônia<span>deforestation change monitor</span></h1>
      </header>

      <button
        className="sheet-toggle glass"
        aria-expanded={panelOpen}
        onClick={() => setPanelOpen((o) => !o)}
      ><IconLayers /> Instruments <IconChevron /></button>

      <aside className={`panel glass ${panelOpen ? "open" : ""}`} aria-label="Map instruments">
        <section className="section" aria-label="Epoch">
          <p className="eyebrow">Epoch</p>
          <div className="seg standalone" role="group" aria-label="Timeslot">
            {TIMESLOTS.map((s) => (
              <button
                key={s}
                aria-pressed={slot === s}
                onClick={() => setSlot(s)}
                title={`Change window ${PAIR_YEARS[SLOT_WINDOW[s]].join("→")} — mask, PRODES and hectares for it`}
              >
                {s} <span className="suffix">{SLOT_TAG[s]}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="section" aria-label="Layers">
          <p className="eyebrow">Layers</p>
          <div className="field-row">
            <label htmlFor="basemap">Basemap</label>
            <select
              id="basemap"
              value={basemap}
              onChange={(e) => setBasemap(e.target.value as Basemap)}
            >
              {(["off", ...BASEMAP_STYLES] as Basemap[]).map((b) => (
                <option key={b} value={b}>{b === "off" ? "None" : b[0].toUpperCase() + b.slice(1)}</option>
              ))}
            </select>
          </div>
          {LAYER_ORDER.map((k) => {
            const on = toggles[k];
            return (
              <div key={k} className="layer-block">
                <div className="layer-row">
                  <button
                    className="toggle"
                    role="switch"
                    aria-checked={toggles[k]}
                    onClick={() => toggleLayer(k)}
                    style={{ "--layer-color": LAYER_CHIP[k].c } as React.CSSProperties}
                  >
                    <span className={`chip ${LAYER_CHIP[k].outline ? "outline" : ""}`} />
                    {LAYER_DOCS[k].tag}
                    <span className="mini-switch" />
                  </button>
                  <button
                    className="info-btn"
                    aria-expanded={openDoc === k}
                    aria-label={`About ${LAYER_DOCS[k].name}`}
                    onClick={() => setOpenDoc((o) => (o === k ? null : k))}
                  ><IconInfo /></button>
                </div>
                {k === "rgb" && on && (
                  <>
                    <Slider k="brightness" label="Brightness" min={0.25} max={2} />
                    <Slider k="contrast" label="Contrast" min={0.25} max={2} />
                    <Slider k="saturation" label="Saturation" min={0} max={2} />
                  </>
                )}
                {k === "ndvi" && on && <Slider k="ndviOpacity" label="NDVI opacity" min={0.1} max={1} />}
                {k === "mask" && on && <Slider k="maskOpacity" label="Mask opacity" min={0.1} max={1} />}
              </div>
            );
          })}
          <button className="btn ghost-reset" onClick={() => { setDisplayDraft(DEFAULT_DISPLAY); setDisplay(DEFAULT_DISPLAY); }}>
            Reset display
          </button>
        </section>

        <section className="section" aria-label="Telemetry">
          <p className="eyebrow">Deforested in view{pair ? ` · ${PAIR_YEARS[pair].join("→")}` : ""}</p>
          {stats ? (
            <div className="telemetry">
              <div className="row">
                <span>U-Net</span>
                <span className="bar"><i style={{ width: `${(stats.unet_ha / maxHa) * 100}%`, "--series": "var(--data-unet)" } as React.CSSProperties} /></span>
                <span className="val">{fmt(stats.unet_ha)} <small>ha</small></span>
              </div>
              <div className="row">
                <span>NDVI-diff</span>
                <span className="bar"><i style={{ width: `${(stats.ndvidiff_ha / maxHa) * 100}%`, "--series": "var(--data-ndvidiff)" } as React.CSSProperties} /></span>
                <span className="val">{fmt(stats.ndvidiff_ha)} <small>ha</small></span>
              </div>
              <div className="row">
                <span>PRODES</span>
                <span className="bar"><i style={{ width: `${(stats.prodes_ha / maxHa) * 100}%`, "--series": "var(--data-prodes)" } as React.CSSProperties} /></span>
                <span className="val">{fmt(stats.prodes_ha)} <small>ha</small></span>
              </div>
            </div>
          ) : (
            <p className="note">
              {apiUp === false
                ? "API offline — start the backend to see telemetry."
                : "Loading statistics…"}
            </p>
          )}
        </section>

        <p className="data-status" title="API heartbeat, polled every 15 s">
          <span className={`dot ${apiUp === null ? "" : apiUp ? "on" : "off"}`} />
          API {apiUp === null ? "connecting…" : apiUp ? "online — tiles and stats live" : "offline — start the backend"}
        </p>
      </aside>

      {hotspotsOn && (
        <aside className="hotspot-panel glass" aria-label="Deforestation hotspots">
          <header className="hotspot-head">
            <p className="eyebrow">Top clearings{pair ? ` · ${PAIR_YEARS[pair].join("→")}` : ""}</p>
            <p className="hotspot-count">{hotspots.length}</p>
          </header>
          <ul className="hotspot-list">
            {hotspots.map((f, i) => (
              <li key={f.properties.id}>
                <button
                  className="linklike"
                  aria-current={hotspot?.properties.id === f.properties.id}
                  onClick={() => { setHotspot(f); flyTo(f.properties.centroid); }}
                >
                  <span className="rank">{i + 1}</span>
                  <b>{fmt(f.properties.area_ha)} ha</b>
                  <span className={`badge ${f.properties.status}`}>{f.properties.status === "prodes_match" ? "PRODES" : "model-only"}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="hotspot-foot">Ranked by cleared area · click a row to fly there</p>
        </aside>
      )}

      <nav className="zoom-nav glass" aria-label="Map navigation">
        <button onClick={() => zoomBy(1)} aria-label="Zoom in"><IconPlus /></button>
        <button onClick={() => zoomBy(-1)} aria-label="Zoom out"><IconMinus /></button>
        <button onClick={resetView} aria-label="Reset view"><IconFrame /></button>
      </nav>

      {hotspot && cardPos && (
        <aside
          className="hotspot-card glass"
          role="status"
          aria-label="Hotspot details"
          style={{ left: cardPos.left, top: cardPos.top }}
        >
          <p className="eyebrow">Hotspot #{hotspot.properties.id + 1} · {hotspot.properties.pair === "eval" ? "2021→2024" : "2019→2021"}</p>
          <h3>{fmt(hotspot.properties.area_ha)} ha <span className={`badge ${hotspot.properties.status}`}>{hotspot.properties.status === "prodes_match" ? "matches PRODES" : "model-only"}</span></h3>
          <dl>
            <div><dt>PRODES overlap</dt><dd>{(hotspot.properties.prodes_frac * 100).toFixed(0)}%</dd></div>
          </dl>
          <button className="btn" onClick={() => flyTo(hotspot.properties.centroid)}>Zoom to clearing</button>
          <button className="info-btn card-close" onClick={() => setHotspot(null)} aria-label="Close hotspot details"><IconClose /></button>
        </aside>
      )}

      <footer className="map-footer">
        <p className="provenance">Sentinel-2 × PRODES × U-Net · 10 m / px</p>
        <p className="coords" aria-live="off">
          {viewState.latitude.toFixed(4)}, {viewState.longitude.toFixed(4)} · z {viewState.zoom.toFixed(1)}
        </p>
      </footer>

      {openDoc && (
        <div
          className="scrim"
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-label={LAYER_DOCS[openDoc].name}
          onClick={(e) => { if (e.target === e.currentTarget) setOpenDoc(null); }}
        >
          <div className="dialog glass doc-dialog">
            <h2>{LAYER_DOCS[openDoc].name}<button onClick={() => setOpenDoc(null)} aria-label="Close"><IconClose /></button></h2>
            <div className="layer-doc">
              <p><span className="k">What it is</span>{LAYER_DOCS[openDoc].brief}</p>
              <p><span className="k">Where it comes from</span>{LAYER_DOCS[openDoc].source}</p>
              <p><span className="k">How to read it</span>{LAYER_DOCS[openDoc].read}</p>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
