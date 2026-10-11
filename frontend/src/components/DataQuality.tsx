import type { AnalysisResult } from "../api";

export default function DataQuality({ result }: { result: AnalysisResult }) {
  const q = result.quality;
  const v = result.meta.hazard === "heavy_rain" ? "precip" : "tmax";
  const cells = q.cells_used;
  const rows: [string, string | number][] = [
    ["Daily values requested", `${q.total_days.toLocaleString()} days × ${cells} cell${cells > 1 ? "s" : ""}`],
    ["Missing in source", q.missing_raw[v] ?? 0],
    ["Outside physical limits", q.out_of_range[v] ?? 0],
    ["Isolated spikes removed", q.spikes_removed],
    ["Max below min (dropped)", q.inconsistent_tmax_tmin],
    ["Gaps ≤2 days interpolated", v === "precip" ? "not interpolated" : q.interpolated[v] ?? 0],
    ["Still missing after cleaning", q.missing_after_cleaning[v] ?? 0],
    ["Unit conversions", q.unit_conversions.length ? q.unit_conversions.join(", ") : "none needed"],
    ["Years excluded (<90% coverage)", q.excluded_years.length ? q.excluded_years.join(", ") : "none"],
  ];
  const minCov = q.year_coverage.length ? Math.min(...q.year_coverage.map((c) => c.coverage)) : 1;

  return (
    <section className="panel" aria-labelledby="dq-title">
      <div className="panel-head">
        <h2 id="dq-title">Data quality</h2>
        <span className="count">{result.meta.cached ? "served from cache" : `${q.fetch.upstream_requests} upstream request${q.fetch.upstream_requests === 1 ? "" : "s"}`}</span>
      </div>
      <table className="dq">
        <tbody>
          {rows.map(([k, val]) => (
            <tr key={k}>
              <th scope="row">{k}</th>
              <td>{val}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="coverage" aria-label={`Lowest yearly coverage ${(minCov * 100).toFixed(1)}%`}>
        {q.year_coverage.map((c) => (
          <span key={c.year} title={`${c.year}: ${(c.coverage * 100).toFixed(1)}% of days valid`}
            className={c.coverage < 0.9 ? "bad" : c.coverage < 0.999 ? "partial" : ""} />
        ))}
      </div>
      <p className="hint">Yearly coverage: each tick is a year; amber = some days missing, red = excluded.</p>
    </section>
  );
}
