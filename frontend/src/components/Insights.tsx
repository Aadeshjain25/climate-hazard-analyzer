import type { AnalysisResult } from "../api";

const VERDICT: Record<AnalysisResult["insights"]["significance"], string> = {
  significant: "Statistically significant trend",
  weak: "Weak evidence of a trend",
  none: "No significant trend",
  insufficient: "Too little data to test",
};

export default function Insights({ result }: { result: AnalysisResult }) {
  const { insights, threshold, meta } = result;
  const comp = insights.decade_comparison;
  const unit = result.metrics.find((m) => m.key === result.primary_metric)?.unit ?? "";
  const thrText =
    threshold.method === "calendar"
      ? `Calendar-day P${threshold.percentile} of daily max temperature (${threshold.min_c}–${threshold.max_c} °C across the year)`
      : threshold.value_mm !== undefined
        ? `P${threshold.percentile} of wet-day rainfall: ${threshold.value_mm} mm in a day`
        : `P${threshold.percentile} of daily max temperature: ${threshold.value_c} °C`;

  return (
    <section className="insight" aria-live="polite">
      <p className={`verdict v-${insights.significance}`}>
        <span className="dot" aria-hidden="true" />
        {VERDICT[insights.significance]}, {insights.confidence} confidence
      </p>
      <h1 className="headline">{insights.headline_short}</h1>
      {insights.qualifier && <p className="qualifier">{insights.qualifier}</p>}

      {comp && (
        <div className="compare" role="group" aria-label="Decade comparison">
          <div>
            <span className="big">{comp.first_mean.toFixed(1)}</span>
            <span className="cap">{unit}, {comp.first_period}</span>
          </div>
          <svg viewBox="0 0 40 12" className="arrow" aria-hidden="true">
            <path d="M0 6 H34 M28 1 L35 6 L28 11" fill="none" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          <div>
            <span className="big">{comp.last_mean.toFixed(1)}</span>
            <span className="cap">{unit}, {comp.last_period}</span>
          </div>
          <div className="delta">
            <span className="big">
              {comp.pct_change !== null ? `${comp.pct_change >= 0 ? "+" : ""}${comp.pct_change.toFixed(0)}%` : `${comp.abs_change >= 0 ? "+" : ""}${comp.abs_change.toFixed(1)}`}
            </span>
            <span className="cap">{comp.pct_change !== null ? "change in decade average" : `${unit} change (base too small for %)`}</span>
          </div>
        </div>
      )}

      <ul className="bullets">
        {insights.bullets.map((b) => (
          <li key={b}>{b}</li>
        ))}
      </ul>

      <p className="definition">
        <strong>Definition used.</strong> {thrText}, computed over the {meta.baseline.start}–{meta.baseline.end} baseline. An event is{" "}
        {meta.params.min_duration > 1 ? `${meta.params.min_duration} or more consecutive days` : "one or more consecutive days"} above it.
      </p>
    </section>
  );
}
