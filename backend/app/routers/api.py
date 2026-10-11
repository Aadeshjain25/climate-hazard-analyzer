"""HTTP API. All endpoints are GET + query params: analyses are pure functions of their
inputs, so they are cacheable by browsers/CDNs and shareable as URLs."""
from __future__ import annotations

import asyncio
import re
from typing import Literal

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from .. import hazards
from ..config import settings
from ..ratelimit import limiter
from ..regions import Region
from ..services.analysis import AnalysisParams
from ..services.export import to_csv, to_pdf

router = APIRouter(prefix="/api")

HazardName = Literal["heatwave", "heavy_rain"]
_label_bad = re.compile(r"[\x00-\x1f\x7f<>]")
_bbox_re = re.compile(r"^-?\d{1,3}(\.\d{1,6})?(,-?\d{1,3}(\.\d{1,6})?){3}$")


def _region(lat: float | None, lon: float | None, bbox: str | None, label: str | None) -> Region:
    clean_label = _label_bad.sub("", label or "").strip()[:120]
    if bbox:
        if lat is not None or lon is not None:
            raise HTTPException(422, "Give either lat/lon or bbox, not both.")
        if not _bbox_re.match(bbox):
            raise HTTPException(422, "bbox must be 'south,west,north,east' in decimal degrees.")
        s, w, n, e = (float(v) for v in bbox.split(","))
        if not (-90 <= s < n <= 90):
            raise HTTPException(422, "bbox latitudes must satisfy -90 <= south < north <= 90.")
        if not (-180 <= w < e <= 180):
            raise HTTPException(422, "bbox longitudes must satisfy -180 <= west < east <= 180 (boxes crossing the antimeridian are not supported).")
        if n - s > settings.max_bbox_deg or e - w > settings.max_bbox_deg:
            raise HTTPException(422, f"bbox may span at most {settings.max_bbox_deg}° in each direction.")
        return Region("bbox", clean_label or f"Box {s:.2f},{w:.2f} – {n:.2f},{e:.2f}", south=s, west=w, north=n, east=e)
    if lat is None or lon is None:
        raise HTTPException(422, "Provide lat and lon, or bbox.")
    return Region("point", clean_label or f"{lat:.3f}, {lon:.3f}", lat=lat, lon=lon)


def _params(
    hazard: str,
    lat: float | None,
    lon: float | None,
    bbox: str | None,
    label: str | None,
    start_year: int,
    end_year: int,
    percentile: float | None,
    min_duration: int | None,
    threshold_method: str | None,
    baseline_start: int | None,
    baseline_end: int | None,
) -> AnalysisParams:
    max_year = settings.max_year
    for name, y in (("start_year", start_year), ("end_year", end_year)):
        if not settings.min_year <= y <= max_year:
            raise HTTPException(422, f"{name} must be between {settings.min_year} and {max_year} (last complete year).")
    span = end_year - start_year + 1
    if span < settings.min_span_years:
        raise HTTPException(422, f"Choose at least {settings.min_span_years} years; trends on shorter periods are not meaningful.")
    if span > settings.max_span_years:
        raise HTTPException(422, f"Choose at most {settings.max_span_years} years.")
    if (baseline_start is None) != (baseline_end is None):
        raise HTTPException(422, "Provide both baseline_start and baseline_end, or neither.")
    if baseline_start is not None and baseline_end is not None:
        if not (settings.min_year <= baseline_start < baseline_end <= max_year):
            raise HTTPException(422, "Baseline must lie within the available years with start < end.")
        if baseline_end - baseline_start + 1 < 10:
            raise HTTPException(422, "Baseline must cover at least 10 years.")
    defaults = hazards.get(hazard).DEFAULTS
    method = threshold_method or defaults["threshold_method"]
    if hazard == "heavy_rain" and method != "fixed":
        raise HTTPException(422, "Heavy rainfall supports only the 'fixed' threshold method.")
    return AnalysisParams(
        hazard=hazard,
        region=_region(lat, lon, bbox, label),
        start_year=start_year,
        end_year=end_year,
        percentile=percentile if percentile is not None else defaults["percentile"],
        min_duration=min_duration if min_duration is not None else defaults["min_duration"],
        threshold_method=method,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
    )


class AnalysisQuery(BaseModel):
    """Query-string schema shared by /analyze and /export/* so they can never drift apart.
    `extra=forbid` rejects unknown parameters instead of silently ignoring typos."""

    model_config = {"extra": "forbid"}
    hazard: HazardName = "heatwave"
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    bbox: str | None = Field(None, max_length=80, description="south,west,north,east")
    label: str | None = Field(None, max_length=200)
    start_year: int = 1990
    end_year: int = 2020
    percentile: float | None = Field(None, ge=80, le=99.9)
    min_duration: int | None = Field(None, ge=1, le=14)
    threshold_method: Literal["fixed", "calendar"] | None = None
    baseline_start: int | None = None
    baseline_end: int | None = None

    def to_params(self) -> AnalysisParams:
        return _params(self.hazard, self.lat, self.lon, self.bbox, self.label, self.start_year, self.end_year,
                       self.percentile, self.min_duration, self.threshold_method, self.baseline_start, self.baseline_end)


class CsvQuery(AnalysisQuery):
    table: Literal["annual", "events"] = "annual"


async def _run(request: Request, p: AnalysisParams) -> dict:
    svc = request.app.state.analysis
    try:
        return await asyncio.wait_for(svc.run(p), timeout=settings.analysis_timeout_s)
    except asyncio.TimeoutError:
        raise HTTPException(504, "Analysis took too long. Try a shorter period or a smaller box; partial data has been cached, so retrying will be faster.")


@router.get("/health")
async def health(request: Request, response: Response):
    try:
        await request.app.state.db.command("ping")
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "db": db_ok, "data_source": request.app.state.source_name}


@router.get("/meta")
async def meta(request: Request, response: Response):
    response.headers["Cache-Control"] = "public, max-age=3600"
    return {
        "min_year": settings.min_year,
        "max_year": settings.max_year,
        "min_span_years": settings.min_span_years,
        "max_span_years": settings.max_span_years,
        "max_bbox_deg": settings.max_bbox_deg,
        "max_grid_per_axis": settings.max_grid_per_axis,
        "data_source": request.app.state.source_name,
        "hazards": hazards.describe(),
    }


@router.get("/geocode")
@limiter.limit(settings.rate_limit_geocode)
async def geocode(request: Request, response: Response, q: str = Query(..., min_length=2, max_length=100)):
    q = _label_bad.sub("", q).strip()
    if len(q) < 2:
        raise HTTPException(422, "Query too short.")
    results = await request.app.state.geocoder.search(q)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return {"query": q, "results": results}


@router.get("/analyze")
@limiter.limit(settings.rate_limit_analyze)
async def analyze(request: Request, response: Response, q: Annotated[AnalysisQuery, Query()]):
    p = q.to_params()
    result = await _run(request, p)
    response.headers["Cache-Control"] = "public, max-age=3600"
    return result


@router.get("/export/csv")
@limiter.limit(settings.rate_limit_export)
async def export_csv(request: Request, response: Response, q: Annotated[CsvQuery, Query()]):
    p, table = q.to_params(), q.table
    result = await _run(request, p)
    fname = f"{p.hazard}_{p.start_year}-{p.end_year}_{table}.csv"
    return Response(
        to_csv(result, table),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/export/pdf")
@limiter.limit(settings.rate_limit_export)
async def export_pdf(request: Request, response: Response, q: Annotated[AnalysisQuery, Query()]):
    p = q.to_params()
    result = await _run(request, p)
    pdf = await asyncio.to_thread(to_pdf, result)  # CPU-bound: keep the event loop free
    fname = f"{p.hazard}_{p.start_year}-{p.end_year}_report.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})
