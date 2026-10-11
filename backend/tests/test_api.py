import bson

BASE = {"lat": 12.97, "lon": 77.59, "label": "Bengaluru", "start_year": 1990, "end_year": 2020}


def test_analyze_returns_full_summary(client, fake_api):
    r = client.get("/api/analyze", params=BASE)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["meta"]["hazard"] == "heatwave" and j["meta"]["cached"] is False
    assert len(j["annual"]) == 31
    assert j["threshold"]["method"] == "fixed" and j["threshold"]["value_c"] > 20
    assert "since 1990" in j["insights"]["headline"]
    assert set(j["trends"]["days"]) >= {"mann_kendall", "sens_slope", "ols", "rolling_mean_5y"}
    assert j["quality"]["out_of_range"]["tmax"] >= 1  # synthetic upstream injects a 71 °C value
    bson.encode(j)  # result must be storable in MongoDB as-is (no numpy types, string keys)
    # 31 years > 20-year chunk -> 2 upstream requests
    assert fake_api.archive_calls() == 2


def test_second_request_served_from_db_cache(client, fake_api):
    client.get("/api/analyze", params=BASE)
    n = fake_api.archive_calls()
    r = client.get("/api/analyze", params=BASE)
    assert r.json()["meta"]["cached"] is True
    assert fake_api.archive_calls() == n


def test_overlapping_range_only_fetches_missing_years(client, fake_api):
    client.get("/api/analyze", params=BASE)  # 1990-2020
    n = fake_api.archive_calls()
    r = client.get("/api/analyze", params={**BASE, "start_year": 1980, "end_year": 2010})
    assert r.status_code == 200
    assert fake_api.archive_calls() == n + 1  # only 1980-1989
    assert r.json()["quality"]["fetch"]["years_fetched"] == 10


def test_nearby_points_share_grid_cell_cache(client, fake_api):
    client.get("/api/analyze", params=BASE)
    n = fake_api.archive_calls()
    client.get("/api/analyze", params={**BASE, "lat": 12.99, "lon": 77.61})  # same 0.25° cell
    assert fake_api.archive_calls() == n


def test_bbox_uses_multiple_cells_in_one_request(client, fake_api):
    r = client.get("/api/analyze", params={"bbox": "12,77,13.5,78.5", "start_year": 2000, "end_year": 2015})
    assert r.status_code == 200, r.text
    j = r.json()
    assert len(j["meta"]["region"]["cells"]) == 9
    assert fake_api.archive_calls() == 1
    assert any("area-mean" in c for c in j["insights"]["caveats"])


def test_heavy_rain_hazard(client):
    r = client.get("/api/analyze", params={**BASE, "hazard": "heavy_rain"})
    assert r.status_code == 200
    assert r.json()["threshold"]["value_mm"] > 1


def test_validation_errors(client):
    cases = [
        {**BASE, "start_year": 1800},
        {**BASE, "end_year": 2999},
        {**BASE, "start_year": 2015, "end_year": 2018},  # < 10 years
        {**BASE, "percentile": 50},
        {"bbox": "0,0,20,20", "start_year": 1990, "end_year": 2020},  # too large
        {"bbox": "10,10,5,20", "start_year": 1990, "end_year": 2020},  # south > north
        {"bbox": "1;DROP", "start_year": 1990, "end_year": 2020},
        {"start_year": 1990, "end_year": 2020},  # no region
        {**BASE, "hazard": "volcano"},
        {**BASE, "unexpected": "x"},
        {**BASE, "hazard": "heavy_rain", "threshold_method": "calendar"},
    ]
    for params in cases:
        r = client.get("/api/analyze", params=params)
        assert r.status_code == 422, (params, r.status_code, r.text)
        assert "detail" in r.json()


def test_upstream_failure_retries_then_503(client, fake_api):
    fake_api.fail_next = 100
    r = client.get("/api/analyze", params=BASE)
    assert r.status_code == 503
    assert "unavailable" in r.json()["detail"]
    assert "boom" not in r.text  # upstream body never leaked


def test_upstream_transient_failure_recovers(client, fake_api):
    fake_api.fail_next = 2  # two 500s, then success (max_retries=3)
    r = client.get("/api/analyze", params=BASE)
    assert r.status_code == 200


def test_rate_limit(client):
    statuses = [client.get("/api/analyze", params=BASE).status_code for _ in range(25)]
    assert statuses[0] == 200 and 429 in statuses


def test_csv_export_and_formula_injection(client):
    r = client.get("/api/export/csv", params={**BASE, "label": "=HYPERLINK(evil)"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "'=HYPERLINK" in r.text
    assert "year,valid,days" in r.text
    r2 = client.get("/api/export/csv", params={**BASE, "table": "events"})
    assert r2.text.splitlines()[9].startswith("start,end")


def test_pdf_export(client):
    r = client.get("/api/export/pdf", params=BASE)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_security_headers_and_cors(client):
    r = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    r2 = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r2.headers


def test_meta(client):
    j = client.get("/api/meta").json()
    assert {h["name"] for h in j["hazards"]} == {"heatwave", "heavy_rain"}
