"""Turn numbers into honest, plain-English findings.

Rules we follow so the summary can't overclaim:
  1. Compare DECADE AVERAGES (first ~10 valid years vs last ~10), never first year vs
     last year - single years are dominated by noise (an El Niño year, etc.).
  2. A % change is only quoted when the baseline average is >= 1 day/yr. "From 0.1 to
     0.5 days" is "+400%", which is technically true and practically misleading, so we
     quote the absolute change instead.
  3. The word "increased"/"decreased" in the headline is paired with the Mann-Kendall
     verdict. If the trend isn't significant we say so explicitly.
  4. Caveats are part of the output, not an afterthought.
"""
from __future__ import annotations

from types import ModuleType

import numpy as np


def _fmt(v: float, nd: int = 1) -> str:
    return f"{v:.{nd}f}"


def _window(valid_rows: list[dict]) -> int:
    n = len(valid_rows)
    return max(3, min(10, n // 3))


def _decade_compare(rows: list[dict], key: str) -> dict | None:
    valid = [r for r in rows if r["valid"] and r.get(key) is not None]
    if len(valid) < 6:
        return None
    w = _window(valid)
    first, last = valid[:w], valid[-w:]
    a = float(np.mean([r[key] for r in first]))
    b = float(np.mean([r[key] for r in last]))
    return {
        "first_period": f"{first[0]['year']}–{first[-1]['year']}",
        "last_period": f"{last[0]['year']}–{last[-1]['year']}",
        "first_mean": round(a, 3),
        "last_mean": round(b, 3),
        "abs_change": round(b - a, 3),
        "pct_change": round(100 * (b - a) / a, 1) if a >= 1 else None,
        "window_years": w,
    }


def _significance_phrase(mk: dict | None) -> tuple[str, str]:
    if not mk:
        return "insufficient", "There are too few valid years to test for a trend."
    p = mk["p_value"]
    if p < 0.05:
        return "significant", f"statistically significant (Mann-Kendall p = {p:.3f})"
    if p < 0.10:
        return "weak", f"only weakly supported (Mann-Kendall p = {p:.3f}, above the usual 0.05 cut-off)"
    return "none", f"not statistically significant (Mann-Kendall p = {p:.2f}) - it may be natural variability"


def build(
    hazard: ModuleType,
    annual: list[dict],
    trends: dict[str, dict],
    events: list[dict],
    region: dict,
    params: dict,
    quality: dict,
    source: str,
    baseline_label: str,
) -> dict:
    metric_by_key = {m.key: m for m in hazard.METRICS}
    primary = hazard.PRIMARY_METRIC
    pm = metric_by_key[primary]
    region_name = region.get("label") or "this region"
    since = annual[0]["year"]

    comp = _decade_compare(annual, primary)
    mk = (trends.get(primary) or {}).get("mann_kendall")
    sen = (trends.get(primary) or {}).get("sens_slope")
    sig, sig_text = _significance_phrase(mk)

    noun = pm.label  # e.g. "Heatwave days"
    qualifier = ""
    if comp is None:
        headline = f"Not enough valid years to summarise {noun.lower()} for {region_name}."
        headline_short = headline
    else:
        a, b = comp["first_mean"], comp["last_mean"]
        direction = "increased" if b > a else "decreased" if b < a else "not changed"
        if direction == "not changed":
            change = "have not changed"
        elif comp["pct_change"] is not None:
            change = f"have {direction} by {abs(comp['pct_change']):.0f}%"
        else:
            change = f"have {direction} from {_fmt(a)} to {_fmt(b)} {pm.unit}"
        qualifier = {
            "significant": "",
            "weak": " The long-term trend is only weakly supported.",
            "none": " However, the long-term trend is not statistically significant.",
            "insufficient": "",
        }[sig]
        headline_short = f"{noun} {change} in {region_name} since {since}."
        headline = (
            f"{noun} {change} in {region_name} since {since} "
            f"({_fmt(a)} → {_fmt(b)} {pm.unit}, {comp['first_period']} vs {comp['last_period']}).{qualifier}"
        )

    trend_sentence = ""
    if mk and sen:
        s = sen["slope_per_decade"]
        trend_sentence = (
            f"The year-by-year trend is {sig_text}; Sen's slope ≈ {'+' if s >= 0 else ''}{_fmt(s, 2)} {pm.unit} per decade."
        )
        if comp and np.sign(comp["abs_change"]) != np.sign(s) and s != 0 and comp["abs_change"] != 0:
            trend_sentence += " Note: the decade comparison and the full-period trend point in different directions."

    bullets: list[str] = []
    if trend_sentence:
        bullets.append(trend_sentence)
    for key, t in trends.items():
        if key == primary:
            continue
        m = metric_by_key.get(key)
        mk_k = t.get("mann_kendall")
        sen_k = t.get("sens_slope")
        if not m or not mk_k or not sen_k:
            continue
        if mk_k["p_value"] < 0.05:
            s = sen_k["slope_per_decade"]
            bullets.append(
                f"{m.label}: significant {mk_k['trend']} trend, {'+' if s >= 0 else ''}{_fmt(s, 2)} {m.unit} per decade "
                f"(p = {mk_k['p_value']:.3f})."
            )
    if events:
        worst = max(events, key=lambda e: (e.get("cumulative_excess") or 0))
        unit = "°C" if hazard.VARIABLE == "tmax" else "mm"
        bullets.append(
            f"Most severe event: {worst['start']} → {worst['end']} ({worst['duration']} day"
            f"{'s' if worst['duration'] != 1 else ''}, peak {worst['peak']} {unit})."
        )
        valid_rows = [r for r in annual if r["valid"]]
        zero_years = sum(1 for r in valid_rows if (r.get("events") or 0) == 0)
        bullets.append(
            f"{len(events)} events detected across {len(valid_rows)} valid years; "
            f"{zero_years} year{'s' if zero_years != 1 else ''} had none."
        )

    caveats: list[str] = []
    if source == "synthetic":
        caveats.append("SYNTHETIC DEMO DATA - these numbers are not real observations.")
    caveats.append(
        "Data are ERA5 reanalysis on a ~28 km grid, not station observations; local extremes "
        "(especially urban heat and convective rain) are smoothed."
    )
    caveats.append(
        f"Thresholds are percentiles of the {baseline_label} baseline. If the baseline overlaps a "
        "warming period, the threshold rises with it and trends are partly absorbed."
    )
    ac = (trends.get(primary) or {}).get("lag1_autocorrelation")
    if ac is not None and ac > 0.3:
        caveats.append(
            f"The series is serially correlated (lag-1 r = {ac:.2f}); the Mann-Kendall p-value may be "
            "optimistic. A pre-whitened / Hamed-Rao test would be more conservative."
        )
    if quality.get("excluded_years"):
        caveats.append(
            f"{len(quality['excluded_years'])} year(s) excluded for <90% data coverage: "
            f"{', '.join(map(str, quality['excluded_years'][:10]))}."
        )
    if events and len(events) < 10:
        caveats.append("Fewer than 10 events in total - rare-event statistics are fragile.")
    if region.get("kind") == "bbox":
        caveats.append(
            f"Box regions use the area-mean of {len(region.get('cells', []))} grid cells; averaging dampens "
            "local extremes, so event counts are lower than for any single point inside the box."
        )
    if params.get("threshold_method") == "calendar":
        caveats.append(
            "Calendar-day thresholds flag spells that are unusual for the time of year, including "
            "winter warm spells that are not dangerous in absolute terms."
        )

    confidence = "low"
    if sig == "significant" and comp and len([r for r in annual if r["valid"]]) >= 30:
        confidence = "high"
    elif sig in ("significant", "weak"):
        confidence = "medium"

    return {
        "headline": headline,  # full sentence: used in exports
        "headline_short": headline_short,  # UI headline; the numbers are shown alongside
        "qualifier": qualifier.strip(),
        "significance": sig,
        "confidence": confidence,
        "decade_comparison": comp,
        "bullets": bullets,
        "caveats": caveats,
    }
