import { useMemo } from "react";
import { Bubble } from "react-chartjs-2";
import type { ChartData, ChartOptions } from "chart.js";
import "./charts";
import type { AnalysisResult } from "../api";

const MONTH_STARTS = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Each bubble is one event: x = year, y = when in the year it started, size = duration,
// darkness = intensity. Reveals seasonal shifts (e.g. heat arriving earlier) that
// annual totals hide.
export default function EventTimeline({ result }: { result: AnalysisResult }) {
  const isRain = result.meta.hazard === "heavy_rain";
  const unit = isRain ? "mm" : "°C";
  const events = result.events;

  const data = useMemo<ChartData<"bubble">>(() => {
    const maxExcess = Math.max(0.1, ...events.map((e) => e.mean_excess ?? 0));
    return {
      datasets: [
        {
          label: "Events",
          data: events.map((e) => ({ x: e.year, y: e.day_of_year, r: Math.min(18, 2.5 + Math.sqrt(e.duration) * 2.2) })),
          backgroundColor: events.map((e) => {
            const a = 0.25 + 0.65 * Math.min(1, (e.mean_excess ?? 0) / maxExcess);
            return isRain ? `rgba(43,108,176,${a})` : `rgba(197,48,48,${a})`;
          }),
          borderColor: isRain ? "#1e4e80" : "#7f1d1d",
          borderWidth: 0.6,
        },
      ],
    };
  }, [events, isRain]);

  const options = useMemo<ChartOptions<"bubble">>(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => {
              const e = events[item.dataIndex];
              return [
                `${e.start} → ${e.end} (${e.duration} day${e.duration > 1 ? "s" : ""})`,
                `Peak ${e.peak} ${unit}, mean ${isRain ? "" : "excess "}${e.mean_excess} ${unit}${isRain ? " above threshold" : ""}`,
              ];
            },
          },
        },
      },
      scales: {
        x: {
          min: result.meta.start_year - 0.5,
          max: result.meta.end_year + 0.5,
          grid: { display: false },
          afterBuildTicks: (axis) => {
            const { start_year: a, end_year: b } = result.meta;
            const step = b - a > 40 ? 10 : 5;
            const ticks = [];
            for (let y = Math.ceil(a / step) * step; y <= b; y += step) ticks.push({ value: y });
            axis.ticks = ticks;
          },
          ticks: { callback: (v) => String(v) },
        },
        y: {
          min: 1,
          max: 366,
          reverse: true,
          afterBuildTicks: (axis) => {
            axis.ticks = MONTH_STARTS.map((v) => ({ value: v }));
          },
          ticks: { callback: (v) => MONTHS[MONTH_STARTS.indexOf(Number(v))] ?? "" },
        },
      },
    }),
    [events, result.meta.start_year, result.meta.end_year, unit, isRain],
  );

  return (
    <section className="panel" aria-labelledby="timeline-title">
      <div className="panel-head">
        <h2 id="timeline-title">When each event happened</h2>
        <span className="count">{events.length} events</span>
      </div>
      <p className="metric-desc">Start date by year. Bigger bubbles lasted longer; darker ones were more intense.</p>
      <div className="chart-box short">
        {events.length ? <Bubble data={data} options={options} /> : <p className="empty">No events crossed the threshold in this period.</p>}
      </div>
    </section>
  );
}
