import { useMemo, useState } from "react";
import { Bar } from "react-chartjs-2";
import type { ChartData, ChartOptions } from "chart.js";
import "./charts";
import { COLORS } from "./charts";
import type { AnalysisResult } from "../api";

const fmtP = (p: number) => (p < 0.001 ? "< 0.001" : p.toFixed(3));
const signed = (v: number, d = 2) => `${v >= 0 ? "+" : ""}${v.toFixed(d)}`;

export default function TrendChart({ result }: { result: AnalysisResult }) {
  const [metricKey, setMetricKey] = useState(result.primary_metric);
  const metric = result.metrics.find((m) => m.key === metricKey) ?? result.metrics[0];
  const trend = result.trends[metric.key];
  const isRain = result.meta.hazard === "heavy_rain";

  const data = useMemo<ChartData<"bar" | "line", (number | null)[], string>>(() => {
    const years = result.annual.map((r) => r.year);
    const values = result.annual.map((r) => (r.valid ? (r[metric.key] as number | null) : null));
    const sen = trend.sens_slope;
    const ols = trend.ols;
    return {
      labels: years.map(String),
      datasets: [
        {
          type: "bar" as const,
          label: metric.label,
          data: values,
          backgroundColor: isRain ? COLORS.rainSoft : COLORS.heatSoft,
          borderRadius: 1,
          barPercentage: 0.9,
          categoryPercentage: 0.95,
          order: 3,
        },
        {
          type: "line" as const,
          label: "5-year rolling mean",
          data: trend.rolling_mean_5y,
          borderColor: COLORS.ink,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.35,
          spanGaps: false,
          order: 1,
        },
        ...(sen
          ? [{
              type: "line" as const,
              label: "Sen's slope (trend)",
              data: years.map((y) => Math.round((sen.intercept + sen.slope_per_year * y) * 100) / 100),
              borderColor: isRain ? COLORS.heat : COLORS.trend,
              borderWidth: 1.5,
              borderDash: [6, 4],
              pointRadius: 0,
              order: 2,
            }]
          : []),
        ...(ols
          ? [{
              type: "line" as const,
              label: "OLS regression",
              data: years.map((y) => Math.round((ols.intercept + ols.slope_per_year * y) * 100) / 100),
              borderColor: COLORS.muted,
              borderWidth: 1,
              borderDash: [2, 3],
              pointRadius: 0,
              hidden: true,
              order: 2,
            }]
          : []),
      ],
    };
  }, [result, metric.key, metric.label, trend, isRain]);

  const options = useMemo<ChartOptions<"bar">>(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 350 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "bottom", align: "start" },
        tooltip: {
          callbacks: {
            title: (items) => {
              const row = result.annual[items[0].dataIndex];
              return row.valid ? String(row.year) : `${row.year} (excluded: low data coverage)`;
            },
            label: (item) => (item.raw === null || item.raw === undefined ? "" : `${item.dataset.label}: ${item.formattedValue} ${metric.unit}`),
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 14 } },
        // Counts and totals can't be negative; clip the trend line at 0 rather than drawing below the axis.
        y: metric.unit.includes("°C") && !metric.unit.includes("above")
          ? { title: { display: true, text: metric.unit } }
          : { min: 0, title: { display: true, text: metric.unit } },
      },
    }),
    [result.annual, metric],
  );

  const mk = trend.mann_kendall;
  return (
    <section className="panel chart-panel" aria-labelledby="trend-title">
      <div className="panel-head">
        <h2 id="trend-title">How {metric.label.toLowerCase()} changed, year by year</h2>
        <label className="metric-select">
          <span className="sr-only">Metric</span>
          <select value={metric.key} onChange={(e) => setMetricKey(e.target.value)}>
            {result.metrics.map((m) => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </select>
        </label>
      </div>
      <p className="metric-desc">{metric.description}</p>
      <div className="chart-box">
        <Bar data={data as ChartData<"bar">} options={options} />
      </div>
      <dl className="stat-row">
        <div>
          <dt>Mann-Kendall</dt>
          <dd>{mk ? (mk.trend === "no trend" ? "no significant trend" : `${mk.trend}`) : "n/a"}</dd>
        </div>
        <div>
          <dt>p-value</dt>
          <dd>{mk ? fmtP(mk.p_value) : "n/a"}</dd>
        </div>
        <div>
          <dt>Kendall's τ</dt>
          <dd>{mk ? mk.tau.toFixed(2) : "n/a"}</dd>
        </div>
        <div>
          <dt>Sen's slope</dt>
          <dd>{trend.sens_slope ? `${signed(trend.sens_slope.slope_per_decade)} / decade` : "n/a"}</dd>
        </div>
        <div>
          <dt>OLS slope (R²)</dt>
          <dd>{trend.ols ? `${signed(trend.ols.slope_per_decade)} (${trend.ols.r2.toFixed(2)})` : "n/a"}</dd>
        </div>
      </dl>
    </section>
  );
}
