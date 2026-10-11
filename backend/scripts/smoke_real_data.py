"""Run one real analysis end-to-end against live Open-Meteo (needs internet).

    cd backend
    python scripts/smoke_real_data.py            # Bengaluru 1990-2020
    python scripts/smoke_real_data.py 28.61 77.21 Delhi

Uses the in-memory DB, so it touches nothing persistent. Prints the headline,
threshold, data-quality summary and timing for a cold and a warm (cached) run.
"""
import os
import sys
import time

os.environ.setdefault("MONGODB_URI", "memory://")
os.environ["DATA_SOURCE"] = "open-meteo"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

lat, lon, label = (float(sys.argv[1]), float(sys.argv[2]), sys.argv[3]) if len(sys.argv) > 3 else (12.97, 77.59, "Bengaluru")
params = {"lat": lat, "lon": lon, "label": label, "start_year": 1990, "end_year": 2020}

with TestClient(app) as c:
    for run in ("cold", "warm"):
        t = time.perf_counter()
        r = c.get("/api/analyze", params=params)
        dt = time.perf_counter() - t
        if r.status_code != 200:
            print(run, r.status_code, r.json())
            sys.exit(1)
        j = r.json()
        print(f"[{run}] {dt:.2f}s cached={j['meta']['cached']}")
    print("Headline :", j["insights"]["headline"])
    print("Threshold:", j["threshold"])
    q = j["quality"]
    print("Quality  :", {k: q[k] for k in ("missing_raw", "out_of_range", "spikes_removed", "interpolated", "excluded_years")})
    print("Events   :", len(j["events"]))
