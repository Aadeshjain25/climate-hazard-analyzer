// "Warming stripes" (Ed Hawkins' visual) for the selected region: one stripe per year,
// coloured by that year's mean Tmax anomaly vs the period mean. It is the page's hero
// because it is the data itself, not decoration.

const COOL = [43, 108, 176]; // #2b6cb0
const NEUTRAL = [245, 241, 238];
const WARM = [127, 29, 29]; // #7f1d1d
const MID_WARM = [197, 48, 48]; // #c53030

function mix(a: number[], b: number[], t: number) {
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(",")})`;
}

export function stripeColor(anomaly: number, maxAbs: number) {
  const t = Math.max(-1, Math.min(1, anomaly / (maxAbs || 1)));
  if (t < 0) return mix(NEUTRAL, COOL, -t);
  return t < 0.6 ? mix(NEUTRAL, MID_WARM, t / 0.6) : mix(MID_WARM, WARM, (t - 0.6) / 0.4);
}

export default function Stripes({ stripes, height = 88 }: { stripes: { year: number; anomaly: number | null }[]; height?: number }) {
  if (!stripes.length) return null;
  const vals = stripes.map((s) => s.anomaly).filter((v): v is number => v !== null);
  const maxAbs = Math.max(0.3, ...vals.map(Math.abs));
  const w = 100 / stripes.length;
  return (
    <figure className="stripes" aria-label="Annual mean maximum temperature anomaly, one stripe per year">
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" role="img">
        {stripes.map((s, i) => (
          <rect key={s.year} x={i * w} y={0} width={w + 0.05} height={height}
            fill={s.anomaly === null ? "url(#missing)" : stripeColor(s.anomaly, maxAbs)}>
            <title>{s.anomaly === null ? `${s.year}: excluded (low data coverage)` : `${s.year}: ${s.anomaly >= 0 ? "+" : ""}${s.anomaly.toFixed(2)} °C vs period mean`}</title>
          </rect>
        ))}
        <defs>
          <pattern id="missing" width="2" height="2" patternUnits="userSpaceOnUse">
            <rect width="2" height="2" fill="#d5dce3" />
            <path d="M0 2 L2 0" stroke="#9aa5b1" strokeWidth="0.3" />
          </pattern>
        </defs>
      </svg>
      <figcaption>
        <span>{stripes[0].year}</span>
        <span className="legend">
          <i style={{ background: stripeColor(-maxAbs, maxAbs) }} /> −{maxAbs.toFixed(1)} °C
          <i style={{ background: stripeColor(0, maxAbs) }} /> annual mean Tmax vs period average
          <i style={{ background: stripeColor(maxAbs, maxAbs) }} /> +{maxAbs.toFixed(1)} °C
        </span>
        <span>{stripes[stripes.length - 1].year}</span>
      </figcaption>
    </figure>
  );
}
