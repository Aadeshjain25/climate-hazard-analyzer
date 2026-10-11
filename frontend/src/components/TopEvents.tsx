import type { AnalysisResult } from "../api";

export default function TopEvents({ result }: { result: AnalysisResult }) {
  const isRain = result.meta.hazard === "heavy_rain";
  const top = [...result.events].sort((a, b) => (b.cumulative_excess ?? 0) - (a.cumulative_excess ?? 0)).slice(0, 8);
  if (!top.length) return null;
  return (
    <section className="panel" aria-labelledby="top-title">
      <div className="panel-head">
        <h2 id="top-title">Most severe events</h2>
      </div>
      <p className="metric-desc">
        Ranked by {isRain ? "total rain during the event" : "cumulative heat: degrees above threshold summed over the event's days"}.
      </p>
      <table className="events">
        <thead>
          <tr>
            <th scope="col">Dates</th>
            <th scope="col" className="n">Days</th>
            <th scope="col" className="n">Peak</th>
            <th scope="col" className="n">{isRain ? "Total" : "Heat load"}</th>
          </tr>
        </thead>
        <tbody>
          {top.map((e) => (
            <tr key={e.start}>
              <td>{e.start === e.end ? e.start : `${e.start} – ${e.end.slice(5)}`}</td>
              <td className="n">{e.duration}</td>
              <td className="n">{e.peak} {isRain ? "mm" : "°C"}</td>
              <td className="n">{e.cumulative_excess} {isRain ? "mm" : "°C·d"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
