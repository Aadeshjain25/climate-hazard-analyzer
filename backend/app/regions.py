"""Turn a user-selected region (point or lat/lon box) into ERA5 grid cells.

Why snap to a 0.25° grid?
  ERA5 is a 0.25° (~28 km) gridded reanalysis. Two requests for (12.971, 77.594)
  and (12.98, 77.60) return the *same* grid cell, so snapping before caching turns
  near-duplicate requests into cache hits and keeps the cache key space bounded.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

GRID_RES = 0.25


def snap(value: float, res: float = GRID_RES) -> float:
    return round(round(value / res) * res, 4)


@dataclass(frozen=True)
class Cell:
    lat: float
    lon: float

    @property
    def key(self) -> str:
        return f"{self.lat:.2f}:{self.lon:.2f}"


@dataclass(frozen=True)
class Region:
    kind: str  # "point" | "bbox"
    label: str
    lat: float | None = None
    lon: float | None = None
    south: float | None = None
    west: float | None = None
    north: float | None = None
    east: float | None = None

    @property
    def center(self) -> tuple[float, float]:
        if self.kind == "point":
            return (self.lat, self.lon)  # type: ignore[return-value]
        return ((self.south + self.north) / 2, (self.west + self.east) / 2)  # type: ignore[operator]

    def cells(self, max_per_axis: int = 3) -> list[Cell]:
        """Grid cells used to represent the region.

        Point -> the single nearest cell.
        Box   -> an evenly spaced n x n sample (n <= max_per_axis) of cell centres
                 inside the box, deduplicated after snapping. Capping n bounds the
                 upstream cost: a 3x3 box is 9 locations, not hundreds.
        """
        if self.kind == "point":
            return [Cell(snap(self.lat), snap(self.lon))]  # type: ignore[arg-type]

        lat_span = self.north - self.south  # type: ignore[operator]
        lon_span = self.east - self.west  # type: ignore[operator]
        n_lat = max(1, min(max_per_axis, math.ceil(lat_span / GRID_RES)))
        n_lon = max(1, min(max_per_axis, math.ceil(lon_span / GRID_RES)))
        lats = [self.south + lat_span * (i + 0.5) / n_lat for i in range(n_lat)]  # type: ignore[operator]
        lons = [self.west + lon_span * (j + 0.5) / n_lon for j in range(n_lon)]  # type: ignore[operator]
        seen: dict[str, Cell] = {}
        for la in lats:
            for lo in lons:
                c = Cell(snap(la), snap(lo))
                seen.setdefault(c.key, c)
        return list(seen.values())

    def cache_key(self) -> str:
        if self.kind == "point":
            c = self.cells()[0]
            return f"pt:{c.key}"
        return f"bb:{self.south:.2f},{self.west:.2f},{self.north:.2f},{self.east:.2f}"

    def to_dict(self, max_per_axis: int = 3) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "lat": self.lat,
            "lon": self.lon,
            "bbox": None
            if self.kind == "point"
            else {"south": self.south, "west": self.west, "north": self.north, "east": self.east},
            "center": list(self.center),
            "cells": [{"lat": c.lat, "lon": c.lon} for c in self.cells(max_per_axis)],
        }
