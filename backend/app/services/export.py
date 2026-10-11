"""CSV and PDF exports of an analysis result (bonus feature).

Both are rendered server-side from the SAME cached JSON the UI uses, so an export
never triggers a new upstream download and always matches what the user saw.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(v):
    """Neutralise spreadsheet formula injection (a place name like '=HYPERLINK(...)')."""
    if isinstance(v, str) and v.startswith(_FORMULA_PREFIXES):
        return "'" + v
    return v


def to_csv(result: dict, table: str = "annual") -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    meta = result["meta"]
    thr = result["threshold"]
    w.writerow(["# Climate Hazard Trend Analyzer export"])
    w.writerow(["# hazard", meta["hazard_label"]])
    w.writerow(["# region", _csv_safe(meta["region"]["label"])])
    w.writerow(["# period", f"{meta['start_year']}-{meta['end_year']}"])
    w.writerow(["# baseline", f"{meta['baseline']['start']}-{meta['baseline']['end']}"])
    w.writerow(["# threshold", _csv_safe(_threshold_text(thr))])
    w.writerow(["# source", meta["source_detail"]])
    w.writerow(["# headline", _csv_safe(result["insights"]["headline"])])
    w.writerow([])
    if table == "events":
        cols = ["start", "end", "year", "duration", "peak", "mean_excess", "cumulative_excess"]
        w.writerow(cols)
        for e in result["events"]:
            w.writerow([e.get(c) for c in cols])
    else:
        keys = [m["key"] for m in result["metrics"]]
        primary = result["primary_metric"]
        w.writerow(["year", "valid", *keys, f"{primary}_rolling5y"])
        rolling = result["trends"][primary]["rolling_mean_5y"]
        for row, rm in zip(result["annual"], rolling):
            w.writerow([row["year"], row["valid"], *[row.get(k) for k in keys], rm])
    # UTF-8 BOM so Excel on Windows shows °C correctly instead of mojibake.
    return "\ufeff" + buf.getvalue()


def _threshold_text(thr: dict) -> str:
    if thr.get("method") == "calendar":
        return f"calendar-day P{thr['percentile']:g} of Tmax ({thr['min_c']}–{thr['max_c']} °C)"
    if "value_mm" in thr:
        return f"P{thr['percentile']:g} of wet-day precipitation = {thr['value_mm']} mm"
    return f"P{thr['percentile']:g} of daily Tmax = {thr['value_c']} °C"


def _kv(d: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in d.items())


def _pdf_text(s: str) -> str:
    # Built-in PDF fonts are Latin-1; swap the few non-Latin-1 glyphs we use.
    s = s.replace("→", "->").replace("≈", "~").replace("−", "-").replace("–", "-").replace("·", "-").replace("²", "2")
    return escape(s)


def _bar_chart(result: dict, width: float, height: float) -> Drawing:
    primary = result["primary_metric"]
    rows = result["annual"]
    vals = [r[primary] if r["valid"] else None for r in rows]
    rolling = result["trends"][primary]["rolling_mean_5y"]
    sen = result["trends"][primary].get("sens_slope")
    numeric = [v for v in vals if v is not None] + [v for v in rolling if v is not None]
    vmax = max(numeric + [1.0]) * 1.1
    d = Drawing(width, height)
    left, bottom, plot_w, plot_h = 30, 18, width - 40, height - 30
    n = len(rows)
    bw = plot_w / max(n, 1)

    def y_of(v):
        return bottom + plot_h * (v / vmax)

    d.add(Line(left, bottom, left + plot_w, bottom, strokeColor=colors.grey, strokeWidth=0.5))
    for frac in (0.5, 1.0):
        yv = vmax * frac / 1.1
        d.add(Line(left, y_of(yv), left + plot_w, y_of(yv), strokeColor=colors.HexColor("#e5e5e5"), strokeWidth=0.4))
        d.add(String(2, y_of(yv) - 3, f"{yv:.0f}", fontSize=6, fillColor=colors.grey))
    for i, v in enumerate(vals):
        x = left + i * bw
        if v is None:
            d.add(Rect(x + bw * 0.15, bottom, bw * 0.7, 3, fillColor=colors.HexColor("#d4d4d4"), strokeColor=None))
        elif v > 0:
            d.add(Rect(x + bw * 0.15, bottom, bw * 0.7, y_of(v) - bottom, fillColor=colors.HexColor("#e4572e"), strokeColor=None))
        if n <= 40 and (rows[i]["year"] % 5 == 0) or (n > 40 and rows[i]["year"] % 10 == 0):
            d.add(String(x, 4, str(rows[i]["year"]), fontSize=6, fillColor=colors.grey))
    prev = None
    for i, v in enumerate(rolling):
        if v is None:
            prev = None
            continue
        pt = (left + i * bw + bw / 2, y_of(v))
        if prev:
            d.add(Line(prev[0], prev[1], pt[0], pt[1], strokeColor=colors.HexColor("#1f2937"), strokeWidth=1.2))
        prev = pt
    if sen:
        y0 = sen["intercept"] + sen["slope_per_year"] * rows[0]["year"]
        y1 = sen["intercept"] + sen["slope_per_year"] * rows[-1]["year"]
        d.add(
            Line(left + bw / 2, y_of(max(y0, 0)), left + plot_w - bw / 2, y_of(max(y1, 0)),
                 strokeColor=colors.HexColor("#2563eb"), strokeWidth=1, strokeDashArray=[3, 2])
        )
    return d


def to_pdf(result: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title="Climate Hazard Report", author="Climate Hazard Trend Analyzer")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=17, alignment=0, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["Normal"], fontSize=9, textColor=colors.HexColor("#555555"))
    head = ParagraphStyle("head", parent=ss["Normal"], fontSize=12, leading=16, fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=ss["Heading3"], spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=9.5, leading=13)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10.5, textColor=colors.HexColor("#444444"))

    meta, ins, thr = result["meta"], result["insights"], result["threshold"]
    story = [
        Paragraph(f"{_pdf_text(meta['hazard_label'])} trend report", h1),
        Paragraph(
            _pdf_text(f"{meta['region']['label']}  |  {meta['start_year']}-{meta['end_year']}  |  baseline "
                      f"{meta['baseline']['start']}-{meta['baseline']['end']}  |  {meta['source_detail']}"),
            sub,
        ),
        Paragraph(_pdf_text(ins["headline"]), head),
        ListFlowable([ListItem(Paragraph(_pdf_text(b), body), leftIndent=10) for b in ins["bullets"]], bulletType="bullet", start="•"),
        Spacer(1, 6),
        Paragraph(_pdf_text(f"Annual {next(m['label'] for m in result['metrics'] if m['key'] == result['primary_metric']).lower()} (bars), 5-yr rolling mean (black), Sen's slope (blue dashed); grey = excluded year"), small),
        _bar_chart(result, 174 * mm, 62 * mm),
        Paragraph("Trend statistics", h2),
    ]

    rows = [["Metric", "Unit", "MK trend", "MK p", "Sen slope / decade", "OLS slope / decade", "OLS R2"]]
    for m in result["metrics"]:
        t = result["trends"][m["key"]]
        mk, sen, o = t.get("mann_kendall") or {}, t.get("sens_slope") or {}, t.get("ols") or {}
        rows.append([
            _pdf_text(m["label"]), _pdf_text(m["unit"]), mk.get("trend", "n/a"),
            f"{mk['p_value']:.3f}" if mk else "n/a",
            f"{sen['slope_per_decade']:+.2f}" if sen else "n/a",
            f"{o['slope_per_decade']:+.2f}" if o else "n/a",
            f"{o['r2']:.2f}" if o else "n/a",
        ])
    tbl = Table(rows, repeatRows=1, hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f4")]),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(tbl)

    q = result["quality"]
    story += [
        Paragraph("Method", h2),
        Paragraph(_pdf_text(
            f"Threshold: {_threshold_text(thr)}. Events: >= {meta['params']['min_duration']} consecutive days above "
            f"the threshold; missing days break events. Trend: Mann-Kendall (two-sided, tie-corrected, alpha 0.05) with "
            f"Theil-Sen slope; OLS shown for comparison. Grid cells used: {q.get('cells_used', 1)}."), body),
        Paragraph("Data quality", h2),
        Paragraph(_pdf_text(
            f"Days analysed: {q['total_days']} per cell. Raw missing: {_kv(q['missing_raw'])}. Out of physical range: {_kv(q['out_of_range'])}. "
            f"Tmax<Tmin: {q['inconsistent_tmax_tmin']}. Spikes removed: {q['spikes_removed']}. Interpolated (<=2-day gaps): "
            f"{_kv(q['interpolated'])}. Unit conversions: {', '.join(q['unit_conversions']) or 'none'}. "
            f"Excluded years: {', '.join(map(str, q['excluded_years'])) or 'none'}."), body),
        Paragraph("Caveats", h2),
        ListFlowable([ListItem(Paragraph(_pdf_text(c), small), leftIndent=10) for c in ins["caveats"]], bulletType="bullet", start="•"),
        Spacer(1, 10),
        Paragraph(_pdf_text(f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} - algorithm v{meta['algo_version']}"), small),
    ]
    doc.build(story)
    return buf.getvalue()
