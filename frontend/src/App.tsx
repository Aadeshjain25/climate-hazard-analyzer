import { useCallback, useEffect, useRef, useState } from "react";
import { api, toQuery, type AnalysisRequest, type AnalysisResult, type HazardName, type Meta, type Region, type ThresholdMethod } from "./api";
import RegionPicker from "./components/RegionPicker";
import Stripes from "./components/Stripes";
import Insights from "./components/Insights";
import TrendChart from "./components/TrendChart";
import EventTimeline from "./components/EventTimeline";
import DataQuality from "./components/DataQuality";
import TopEvents from "./components/TopEvents";

const DEFAULT_REQUEST: AnalysisRequest = {
  hazard: "heatwave",
  region: { kind: "point", label: "Bengaluru", lat: 12.9716, lon: 77.5946 },
  startYear: 1990,
  endYear: 2020,
  percentile: 95,
  minDuration: 3,
  thresholdMethod: "fixed",
  baseline: null,
};

// Read a shareable analysis from the URL (?lat=..&lon=..&start_year=..). Anything
// missing or malformed falls back to the default; the server re-validates everything.
function fromUrl(): AnalysisRequest {
  const q = new URLSearchParams(window.location.search);
  if (![...q.keys()].length) return DEFAULT_REQUEST;
  const num = (k: string) => (q.get(k) !== null && q.get(k) !== "" && Number.isFinite(Number(q.get(k))) ? Number(q.get(k)) : undefined);
  const label = (q.get("label") ?? "").slice(0, 120);
  let region: Region = DEFAULT_REQUEST.region;
  const bbox = q.get("bbox")?.split(",").map(Number);
  if (bbox && bbox.length === 4 && bbox.every(Number.isFinite)) {
    region = { kind: "bbox", label, south: bbox[0], west: bbox[1], north: bbox[2], east: bbox[3] };
  } else if (num("lat") !== undefined && num("lon") !== undefined) {
    region = { kind: "point", label, lat: num("lat")!, lon: num("lon")! };
  }
  const hazard = (q.get("hazard") === "heavy_rain" ? "heavy_rain" : "heatwave") as HazardName;
  const bs = num("baseline_start"), be = num("baseline_end");
  return {
    hazard,
    region,
    startYear: num("start_year") ?? DEFAULT_REQUEST.startYear,
    endYear: num("end_year") ?? DEFAULT_REQUEST.endYear,
    percentile: num("percentile") ?? 95,
    minDuration: num("min_duration") ?? (hazard === "heatwave" ? 3 : 1),
    thresholdMethod: (q.get("threshold_method") === "calendar" ? "calendar" : "fixed") as ThresholdMethod,
    baseline: bs !== undefined && be !== undefined ? { start: bs, end: be } : null,
  };
}

function validate(r: AnalysisRequest, meta: Meta | null): string | null {
  const min = meta?.min_year ?? 1940;
  const max = meta?.max_year ?? new Date().getFullYear() - 1;
  if (r.startYear < min || r.endYear > max) return `Years must be between ${min} and ${max}.`;
  if (r.endYear - r.startYear + 1 < (meta?.min_span_years ?? 10)) return "Choose at least 10 years so a trend can be tested.";
  if (r.baseline && r.baseline.end - r.baseline.start + 1 < 10) return "The baseline needs at least 10 years.";
  return null;
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [req, setReq] = useState<AnalysisRequest>(fromUrl);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [resultReq, setResultReq] = useState<AnalysisRequest | null>(null); // exports must match what is shown
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ctrl = useRef<AbortController | null>(null);

  const run = useCallback(async (r: AnalysisRequest) => {
    ctrl.current?.abort();
    ctrl.current = new AbortController();
    setLoading(true);
    setError(null);
    try {
      const res = await api.analyze(r, ctrl.current.signal);
      setResult(res);
      setResultReq(r);
      window.history.replaceState(null, "", `?${toQuery(r)}`);
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null));
    run(req);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const update = (patch: Partial<AnalysisRequest>) => setReq((r) => ({ ...r, ...patch }));
  const setHazard = (hazard: HazardName) => {
    const d = meta?.hazards.find((h) => h.name === hazard)?.defaults;
    update({ hazard, percentile: d?.percentile ?? 95, minDuration: d?.min_duration ?? (hazard === "heatwave" ? 3 : 1), thresholdMethod: "fixed" });
  };

  const invalid = validate(req, meta);
  const maxYear = meta?.max_year ?? new Date().getFullYear() - 1;
  const minYear = meta?.min_year ?? 1940;
  const years = Array.from({ length: maxYear - minYear + 1 }, (_, i) => minYear + i);
  const showing = result && !loading;

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <span className="mark" aria-hidden="true" />
          <span>Climate Hazard Trend Analyzer</span>
        </div>
        <p className="source">
          Daily ERA5 reanalysis (Copernicus / ECMWF) via Open-Meteo, 1940 to {maxYear}
        </p>
      </header>

      {meta?.data_source === "synthetic" && (
        <div className="banner" role="alert">
          Demo mode: the server is using synthetic data, not real observations. Set DATA_SOURCE=open-meteo for real ERA5 data.
        </div>
      )}

      <div className="hero">
        {result ? (
          <Stripes stripes={result.stripes} />
        ) : (
          <div className="stripes placeholder" aria-hidden="true" />
        )}
        {result && (
          <p className="hero-place">
            {result.meta.region.label}, {result.meta.start_year}–{result.meta.end_year}
          </p>
        )}
      </div>

      <main className="layout">
        <aside className="controls" aria-label="Analysis settings">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!invalid) run(req);
            }}
          >
            <RegionPicker
              region={req.region}
              maxBoxDeg={meta?.max_bbox_deg ?? 10}
              cells={result?.meta.region.cells}
              onChange={(region) => update({ region })}
            />

            <fieldset>
              <legend>Hazard</legend>
              <div className="seg" role="radiogroup" aria-label="Hazard type">
                {([["heatwave", "Heatwave"], ["heavy_rain", "Heavy rainfall"]] as [HazardName, string][]).map(([k, label]) => (
                  <label key={k} className={req.hazard === k ? "on" : ""}>
                    <input type="radio" name="hazard" value={k} checked={req.hazard === k} onChange={() => setHazard(k)} />
                    {label}
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset>
              <legend>Time range</legend>
              <div className="grid-2">
                <label className="num-field">
                  <span>From</span>
                  <select value={req.startYear} onChange={(e) => update({ startYear: Number(e.target.value) })}>
                    {years.map((y) => <option key={y} value={y}>{y}</option>)}
                  </select>
                </label>
                <label className="num-field">
                  <span>To</span>
                  <select value={req.endYear} onChange={(e) => update({ endYear: Number(e.target.value) })}>
                    {years.map((y) => <option key={y} value={y}>{y}</option>)}
                  </select>
                </label>
              </div>
              <div className="presets">
                {[[1990, 2020], [1961, 2020], [1980, maxYear], [minYear, maxYear]].map(([a, b]) => (
                  <button type="button" key={`${a}-${b}`} className={req.startYear === a && req.endYear === b ? "chip on" : "chip"}
                    onClick={() => update({ startYear: a, endYear: b })}>
                    {a}–{b}
                  </button>
                ))}
              </div>
            </fieldset>

            <details className="advanced">
              <summary>Detection settings</summary>
              <label className="range-field">
                <span>Threshold percentile <b>P{req.percentile}</b></span>
                <input type="range" min={90} max={99} step={0.5} value={req.percentile} onChange={(e) => update({ percentile: Number(e.target.value) })} />
              </label>
              <label className="range-field">
                <span>Minimum event length <b>{req.minDuration} day{req.minDuration > 1 ? "s" : ""}</b></span>
                <input type="range" min={1} max={7} step={1} value={req.minDuration} onChange={(e) => update({ minDuration: Number(e.target.value) })} />
              </label>
              {req.hazard === "heatwave" && (
                <div className="radio-stack" role="radiogroup" aria-label="Threshold method">
                  <label>
                    <input type="radio" checked={req.thresholdMethod === "fixed"} onChange={() => update({ thresholdMethod: "fixed" })} />
                    <span><b>One threshold for the whole year.</b> Finds dangerous absolute heat (as in the brief).</span>
                  </label>
                  <label>
                    <input type="radio" checked={req.thresholdMethod === "calendar"} onChange={() => update({ thresholdMethod: "calendar" })} />
                    <span><b>Threshold for each calendar day.</b> Finds spells unusually hot for the season (ETCCDI style).</span>
                  </label>
                </div>
              )}
              <div className="baseline">
                <span>Baseline for the threshold</span>
                <div className="presets">
                  <button type="button" className={!req.baseline ? "chip on" : "chip"} onClick={() => update({ baseline: null })}>Same as range</button>
                  {[[1961, 1990], [1991, 2020]].map(([a, b]) => (
                    <button type="button" key={a} className={req.baseline?.start === a && req.baseline?.end === b ? "chip on" : "chip"}
                      onClick={() => update({ baseline: { start: a, end: b } })}>
                      {a}–{b}
                    </button>
                  ))}
                </div>
                <p className="hint">A fixed historical baseline avoids a warming climate raising its own bar.</p>
              </div>
            </details>

            {invalid && <p className="form-error">{invalid}</p>}
            <button className="primary" type="submit" disabled={!!invalid || loading}>
              {loading ? "Analysing…" : "Analyse trends"}
            </button>
          </form>

          {showing && resultReq && (
            <div className="exports">
              <span>Download</span>
              <a href={api.exportUrl(resultReq, "pdf")} download>PDF report</a>
              <a href={api.exportUrl(resultReq, "csv", "annual")} download>Annual CSV</a>
              <a href={api.exportUrl(resultReq, "csv", "events")} download>Events CSV</a>
            </div>
          )}
        </aside>

        <div className="results">
          {error && (
            <div className="error" role="alert">
              <p>{error}</p>
              <button type="button" onClick={() => run(req)}>Try again</button>
            </div>
          )}
          {loading && (
            <div className="loading" role="status">
              <div className="bar" />
              <p>Fetching and analysing daily data. A new place can take 10–30 seconds the first time; after that it's cached.</p>
            </div>
          )}
          {showing && (
            <>
              <Insights result={result} />
              <TrendChart key={`${result.meta.hazard}-${result.meta.generated_at}`} result={result} />
              <div className="two-col">
                <EventTimeline result={result} />
                <TopEvents result={result} />
              </div>
              <div className="two-col">
                <DataQuality result={result} />
                <section className="panel caveats" aria-labelledby="caveats-title">
                  <div className="panel-head"><h2 id="caveats-title">Read with care</h2></div>
                  <ul>
                    {result.insights.caveats.map((c) => <li key={c}>{c}</li>)}
                  </ul>
                </section>
              </div>
              <footer className="foot">
                {result.meta.source_detail}. Analysis v{result.meta.algo_version}
                {result.meta.cached ? ", served from the database cache" : ""}.
              </footer>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
