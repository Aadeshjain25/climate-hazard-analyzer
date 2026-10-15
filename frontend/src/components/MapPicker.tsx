import { useEffect, useRef, useState } from "react";
import { CircleMarker, MapContainer, Rectangle, TileLayer, useMap, useMapEvents } from "react-leaflet";
import type { LatLngBoundsExpression, LatLngTuple } from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Region } from "../api";

type Mode = "point" | "bbox";

interface Props {
  mode: Mode;
  region: Region | null;
  maxBoxDeg: number;
  cells?: { lat: number; lon: number }[];
  onChange: (r: Region) => void;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const round = (v: number) => Math.round(v * 1e4) / 1e4;

function boxFrom(a: LatLngTuple, b: LatLngTuple, maxDeg: number) {
  // Clamp the second corner so the box never exceeds the backend's size limit.
  const south = Math.min(a[0], b[0]);
  const north = Math.max(a[0], b[0]);
  const west = Math.min(a[1], b[1]);
  const east = Math.max(a[1], b[1]);
  return {
    south: round(clamp(south, -90, 90)),
    north: round(clamp(Math.min(north, south + maxDeg), -90, 90)),
    west: round(clamp(west, -180, 180)),
    east: round(clamp(Math.min(east, west + maxDeg), -180, 180)),
  };
}

function ClickHandler({ mode, maxBoxDeg, onChange, setPreview }: {
  mode: Mode;
  maxBoxDeg: number;
  onChange: (r: Region) => void;
  setPreview: (b: LatLngBoundsExpression | null) => void;
}) {
  const anchor = useRef<LatLngTuple | null>(null);
  useEffect(() => {
    anchor.current = null;
    setPreview(null);
  }, [mode, setPreview]);

  useMapEvents({
    click(e) {
      const p: LatLngTuple = [e.latlng.lat, e.latlng.wrap().lng];
      if (mode === "point") {
        onChange({ kind: "point", label: "", lat: round(p[0]), lon: round(p[1]) });
        return;
      }
      if (!anchor.current) {
        anchor.current = p;
        setPreview([p, p]);
      } else {
        const b = boxFrom(anchor.current, p, maxBoxDeg);
        anchor.current = null;
        setPreview(null);
        if (b.north - b.south > 0.05 && b.east - b.west > 0.05) onChange({ kind: "bbox", label: "", ...b });
      }
    },
    mousemove(e) {
      if (mode !== "bbox" || !anchor.current) return;
      const b = boxFrom(anchor.current, [e.latlng.lat, e.latlng.wrap().lng], maxBoxDeg);
      setPreview([[b.south, b.west], [b.north, b.east]]);
    },
  });
  return null;
}

function FitToRegion({ region }: { region: Region | null }) {
  const map = useMap();
  const key = region ? JSON.stringify(region) : "";
  useEffect(() => {
    if (!region) return;
    if (region.kind === "point") {
      map.flyTo([region.lat, region.lon], Math.max(map.getZoom(), 7), { duration: 0.6 });
    } else {
      map.flyToBounds([[region.south, region.west], [region.north, region.east]], { padding: [24, 24], duration: 0.6 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return null;
}

export default function MapPicker({ mode, region, maxBoxDeg, cells, onChange }: Props) {
  const [preview, setPreview] = useState<LatLngBoundsExpression | null>(null);
  const center: LatLngTuple = region
    ? region.kind === "point"
      ? [region.lat, region.lon]
      : [(region.south + region.north) / 2, (region.west + region.east) / 2]
    : [20.6, 78.9];

  return (
    <div className="map-wrap">
      <MapContainer center={center} zoom={region ? 6 : 4} worldCopyJump className="map" attributionControl>
        <TileLayer
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          maxZoom={12}
        />
        <ClickHandler mode={mode} maxBoxDeg={maxBoxDeg} onChange={onChange} setPreview={setPreview} />
        <FitToRegion region={region} />
        {region?.kind === "point" && (
          <CircleMarker center={[region.lat, region.lon]} radius={7} pathOptions={{ color: "#1b2430", weight: 2, fillColor: "#c53030", fillOpacity: 0.9 }} />
        )}
        {region?.kind === "bbox" && (
          <Rectangle bounds={[[region.south, region.west], [region.north, region.east]]} pathOptions={{ color: "#1b2430", weight: 2, fillOpacity: 0.06 }} />
        )}
        {preview && <Rectangle bounds={preview} pathOptions={{ color: "#c53030", weight: 1.5, dashArray: "4 4", fillOpacity: 0.05 }} />}
        {cells?.map((c) => (
          <Rectangle
            key={`${c.lat}:${c.lon}`}
            bounds={[[c.lat - 0.125, c.lon - 0.125], [c.lat + 0.125, c.lon + 0.125]]}
            pathOptions={{ color: "#2b6cb0", weight: 1, fillColor: "#2b6cb0", fillOpacity: 0.18 }}
          />
        ))}
      </MapContainer>
      <p className="map-hint">
        {mode === "point" ? "Click the map to drop a point." : "Click two opposite corners to draw a box."}
        {cells?.length ? ` Blue squares are the ${cells.length} ERA5 grid cell${cells.length > 1 ? "s" : ""} analysed.` : ""}
      </p>
    </div>
  );
}
