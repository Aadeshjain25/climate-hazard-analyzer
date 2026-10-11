import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { api, type GeocodeResult, type Region } from "../api";

const MapPicker = lazy(() => import("./MapPicker"));

type Tab = "search" | "point" | "bbox";

interface Props {
  region: Region | null;
  maxBoxDeg: number;
  cells?: { lat: number; lon: number }[];
  onChange: (r: Region) => void;
}

function NumberField({ label, value, min, max, onCommit }: {
  label: string;
  value: number | undefined;
  min: number;
  max: number;
  onCommit: (v: number) => void;
}) {
  const [text, setText] = useState(value?.toString() ?? "");
  useEffect(() => setText(value?.toString() ?? ""), [value]);
  const commit = () => {
    const v = Number(text);
    if (text.trim() !== "" && Number.isFinite(v) && v >= min && v <= max) onCommit(Math.round(v * 1e4) / 1e4);
    else setText(value?.toString() ?? "");
  };
  return (
    <label className="num-field">
      <span>{label}</span>
      <input
        inputMode="decimal"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && commit()}
      />
    </label>
  );
}

export default function RegionPicker({ region, maxBoxDeg, cells, onChange }: Props) {
  const [tab, setTab] = useState<Tab>("search");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GeocodeResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const ctrl = useRef<AbortController | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setResults([]);
      setSearchError(null);
      return;
    }
    // Debounce: the geocoder is rate-limited, so don't fire on every keystroke.
    const t = setTimeout(async () => {
      ctrl.current?.abort();
      ctrl.current = new AbortController();
      setSearching(true);
      setSearchError(null);
      try {
        const { results } = await api.geocode(q, ctrl.current.signal);
        setResults(results);
        if (!results.length) setSearchError("No places found. Try a nearby city or draw a box on the map.");
      } catch (e) {
        if ((e as Error).name !== "AbortError") setSearchError((e as Error).message);
      } finally {
        setSearching(false);
      }
    }, 450);
    return () => clearTimeout(t);
  }, [query]);

  const pick = (r: GeocodeResult, asBox: boolean) => {
    const short = r.label.split(",").slice(0, 2).join(",").trim();
    if (asBox && r.bbox) {
      const b = r.bbox;
      const south = b.south, west = b.west;
      onChange({
        kind: "bbox",
        label: short,
        south,
        west,
        north: Math.min(b.north, south + maxBoxDeg),
        east: Math.min(b.east, west + maxBoxDeg),
      });
    } else {
      onChange({ kind: "point", label: short, lat: r.lat, lon: r.lon });
    }
    setResults([]);
    setQuery(short);
  };

  const mapMode = tab === "bbox" || (tab === "search" && region?.kind === "bbox") ? "bbox" : "point";

  return (
    <fieldset className="region">
      <legend>Region</legend>
      <div className="tabs" role="tablist" aria-label="How to choose the region">
        {([["search", "Search"], ["point", "Point"], ["bbox", "Box"]] as [Tab, string][]).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "tab on" : "tab"} onClick={() => setTab(k)} type="button">
            {label}
          </button>
        ))}
      </div>

      {tab === "search" && (
        <div className="search">
          <input
            type="search"
            placeholder="City or state, e.g. Bengaluru or Rajasthan"
            value={query}
            maxLength={100}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search for a city or state"
          />
          {searching && <p className="hint">Searching…</p>}
          {searchError && <p className="hint warn">{searchError}</p>}
          {results.length > 0 && (
            <ul className="results">
              {results.map((r, i) => (
                <li key={`${r.label}-${i}`}>
                  <button type="button" onClick={() => pick(r, r.kind === "area" && !!r.bbox)}>
                    <span className="r-label">{r.label}</span>
                    <span className="r-kind">
                      {r.kind === "area" && r.bbox ? (r.bbox_too_large ? "area · box trimmed to limit" : "area · analysed as box") : "point"}
                    </span>
                  </button>
                  {r.kind === "area" && r.bbox && (
                    <button type="button" className="link" onClick={() => pick(r, false)}>
                      use centre point
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {tab === "point" && (
        <div className="grid-2">
          <NumberField label="Latitude" min={-90} max={90} value={region?.kind === "point" ? region.lat : undefined}
            onCommit={(lat) => onChange({ kind: "point", label: "", lat, lon: region?.kind === "point" ? region.lon : 77.59 })} />
          <NumberField label="Longitude" min={-180} max={180} value={region?.kind === "point" ? region.lon : undefined}
            onCommit={(lon) => onChange({ kind: "point", label: "", lon, lat: region?.kind === "point" ? region.lat : 12.97 })} />
        </div>
      )}

      {tab === "bbox" && (
        <div className="grid-2">
          {(["south", "north", "west", "east"] as const).map((side) => (
            <NumberField
              key={side}
              label={side[0].toUpperCase() + side.slice(1)}
              min={side === "south" || side === "north" ? -90 : -180}
              max={side === "south" || side === "north" ? 90 : 180}
              value={region?.kind === "bbox" ? region[side] : undefined}
              onCommit={(v) => {
                const base = region?.kind === "bbox" ? region : { kind: "bbox" as const, label: "", south: 12, west: 77, north: 13.5, east: 78.5 };
                onChange({ ...base, label: "", [side]: v });
              }}
            />
          ))}
          <p className="hint span-2">Up to {maxBoxDeg}° per side. Boxes are sampled on a grid of up to 3×3 cells and averaged.</p>
        </div>
      )}

      <Suspense fallback={<div className="map-wrap map-loading">Loading map…</div>}>
        <MapPicker mode={mapMode} region={region} maxBoxDeg={maxBoxDeg} cells={cells} onChange={(r) => {
          if (r.kind === "bbox") setTab("bbox");
          else if (tab === "bbox") setTab("point");
          onChange(r);
        }} />
      </Suspense>

      {region && (
        <p className="selected">
          {region.label || (region.kind === "point" ? "Custom point" : "Custom box")}{" "}
          <span className="coords">
            {region.kind === "point"
              ? `${region.lat.toFixed(2)}°, ${region.lon.toFixed(2)}°`
              : `lat ${region.south.toFixed(2)} to ${region.north.toFixed(2)}, lon ${region.west.toFixed(2)} to ${region.east.toFixed(2)}`}
          </span>
        </p>
      )}
    </fieldset>
  );
}
