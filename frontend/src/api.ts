// Typed client for the FastAPI backend. One place builds query strings so the
// analyze call and the export links always send identical parameters.

const API = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

export type HazardName = "heatwave" | "heavy_rain";
export type ThresholdMethod = "fixed" | "calendar";

export type Region =
  | { kind: "point"; label: string; lat: number; lon: number }
  | { kind: "bbox"; label: string; south: number; west: number; north: number; east: number };

export interface AnalysisRequest {
  hazard: HazardName;
  region: Region;
  startYear: number;
  endYear: number;
  percentile: number;
  minDuration: number;
  thresholdMethod: ThresholdMethod;
  baseline: { start: number; end: number } | null;
}

export interface MetricDef {
  key: string;
  label: string;
  unit: string;
  description: string;
  higher_is_worse: boolean;
}

export interface HazardDef {
  name: HazardName;
  label: string;
  variable: string;
  defaults: { percentile: number; min_duration: number; threshold_method: ThresholdMethod };
  primary_metric: string;
  metrics: MetricDef[];
  definition: string;
}

export interface Meta {
  min_year: number;
  max_year: number;
  min_span_years: number;
  max_span_years: number;
  max_bbox_deg: number;
  max_grid_per_axis: number;
  data_source: string;
  hazards: HazardDef[];
}

export interface MannKendall {
  s: number;
  z: number;
  p_value: number;
  tau: number;
  trend: "increasing" | "decreasing" | "no trend";
  n: number;
}

export interface Trend {
  mann_kendall: MannKendall | null;
  sens_slope: { slope_per_year: number; slope_per_decade: number; intercept: number } | null;
  ols: { slope_per_year: number; slope_per_decade: number; intercept: number; r2: number; p_value: number } | null;
  lag1_autocorrelation: number | null;
  rolling_mean_5y: (number | null)[];
}

export interface HazardEvent {
  start: string;
  end: string;
  year: number;
  day_of_year: number;
  duration: number;
  peak: number;
  mean_excess: number;
  cumulative_excess: number;
}

export type AnnualRow = { year: number; valid: boolean } & Record<string, number | null | boolean>;

export interface Quality {
  total_days: number;
  missing_raw: Record<string, number>;
  unit_conversions: string[];
  out_of_range: Record<string, number>;
  negative_precip_zeroed: number;
  inconsistent_tmax_tmin: number;
  spikes_removed: number;
  interpolated: Record<string, number>;
  missing_after_cleaning: Record<string, number>;
  cells_used: number;
  excluded_years: number[];
  year_coverage: { year: number; coverage: number }[];
  fetch: { years_from_cache: number; years_fetched: number; upstream_requests: number };
}

export interface AnalysisResult {
  meta: {
    hazard: HazardName;
    hazard_label: string;
    region: {
      kind: "point" | "bbox";
      label: string;
      center: [number, number];
      cells: { lat: number; lon: number }[];
      bbox: { south: number; west: number; north: number; east: number } | null;
    };
    start_year: number;
    end_year: number;
    baseline: { start: number; end: number };
    params: { percentile: number; min_duration: number; threshold_method: ThresholdMethod };
    source: string;
    source_detail: string;
    algo_version: string;
    generated_at: string;
    cached: boolean;
  };
  metrics: MetricDef[];
  primary_metric: string;
  threshold: {
    method: ThresholdMethod;
    percentile: number;
    unit: string;
    value_c?: number;
    value_mm?: number;
    min_c?: number;
    max_c?: number;
    by_day_of_year?: (number | null)[];
  };
  annual: AnnualRow[];
  events: HazardEvent[];
  trends: Record<string, Trend>;
  insights: {
    headline: string;
    headline_short: string;
    qualifier: string;
    significance: "significant" | "weak" | "none" | "insufficient";
    confidence: "high" | "medium" | "low";
    decade_comparison: {
      first_period: string;
      last_period: string;
      first_mean: number;
      last_mean: number;
      abs_change: number;
      pct_change: number | null;
    } | null;
    bullets: string[];
    caveats: string[];
  };
  quality: Quality;
  stripes: { year: number; anomaly: number | null }[];
}

export interface GeocodeResult {
  label: string;
  lat: number;
  lon: number;
  kind: "place" | "area";
  type: string;
  bbox: { south: number; west: number; north: number; east: number } | null;
  bbox_too_large: boolean;
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { signal, headers: { Accept: "application/json" } });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError("Can't reach the analysis server. Check that the backend is running.", 0);
  }
  if (!res.ok) {
    let detail = `Request failed (HTTP ${res.status}).`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

export function toQuery(r: AnalysisRequest): URLSearchParams {
  const q = new URLSearchParams();
  q.set("hazard", r.hazard);
  if (r.region.kind === "point") {
    q.set("lat", r.region.lat.toFixed(4));
    q.set("lon", r.region.lon.toFixed(4));
  } else {
    const { south, west, north, east } = r.region;
    q.set("bbox", [south, west, north, east].map((v) => v.toFixed(4)).join(","));
  }
  if (r.region.label) q.set("label", r.region.label.slice(0, 200));
  q.set("start_year", String(r.startYear));
  q.set("end_year", String(r.endYear));
  q.set("percentile", String(r.percentile));
  q.set("min_duration", String(r.minDuration));
  if (r.hazard === "heatwave") q.set("threshold_method", r.thresholdMethod);
  if (r.baseline) {
    q.set("baseline_start", String(r.baseline.start));
    q.set("baseline_end", String(r.baseline.end));
  }
  return q;
}

export const api = {
  meta: (signal?: AbortSignal) => getJson<Meta>("/api/meta", signal),
  geocode: (q: string, signal?: AbortSignal) =>
    getJson<{ results: GeocodeResult[] }>(`/api/geocode?q=${encodeURIComponent(q)}`, signal),
  analyze: (r: AnalysisRequest, signal?: AbortSignal) =>
    getJson<AnalysisResult>(`/api/analyze?${toQuery(r)}`, signal),
  exportUrl: (r: AnalysisRequest, kind: "csv" | "pdf", table: "annual" | "events" = "annual") => {
    const q = toQuery(r);
    if (kind === "csv") q.set("table", table);
    return `${API}/api/export/${kind}?${q}`;
  },
};
