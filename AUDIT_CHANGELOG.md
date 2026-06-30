# FloodWatch Ghana — Audit & Enhancement Change Log

Date: 2026-06-30
Scope: Full project audit + fixes + new features (weather forecasting,
satellite/historical analytics pages).

Test status: **76 passing** (was 57). Django system check: clean.
All dashboard pages render HTTP 200.

---

## 1. The reported `302 → /accounts/login/` — NOT a bug

Reproduced precisely: the redirect fires **only** on `/dashboard/settings/`,
which is deliberately staff-only (`@login_required` + `is_staff` check in
`apps.dashboard.views.settings_view`). Every other page returns 200 to
anonymous users. The Django Debug Toolbar simply made that intentional
access-control redirect visible. No change was required or made.

---

## 2. Bugs fixed

### 2.1 Missing dependency blocked startup (CRITICAL)
`jazzmin` was listed first in `INSTALLED_APPS` (settings/base.py) but absent
from `requirements.txt`, so a clean `pip install -r requirements.txt`
followed by `manage.py check` failed with `ModuleNotFoundError: jazzmin`.

- **Fix:** added `django-jazzmin==3.0.1` to `requirements.txt`.
- Verified this was the *only* missing dependency (every other top-level
  import maps to a pinned requirement).

### 2.2 PyGeoVision integration: wrong result key (would KeyError at runtime)
`apps/satellite/processors.py` read the preprocessed band stack via
`result["array"]` after `client.prepare_for_ai(...)`. The PyGeoVision
notebook (`nb_sar_02_disaster_management.ipynb`) shows `prepare_for_ai`
returns a small metadata dict (e.g. `r['shape']`) and the band stack is read
back from the written GeoTIFF — there is no `"array"` key. Against the real
package this would raise `KeyError` and fail every Sentinel-2 flood
detection.

- **Fix:** after `prepare_for_ai` writes `output_path`, the processor now
  reads the band stack back from that GeoTIFF with rasterio (exactly as the
  notebook does). Also added an explicit check that the output file was
  actually written. This is both authoritative and resilient to the return
  dict's shape changing across PyGeoVision versions.

### 2.3 PyGeoVision search kwarg inconsistency
The notebook uses both `satellite=['Sentinel-1']` (cell 3) and
`satellites=[...]` (cell 9). The project hard-coded `satellites=`.

- **Fix:** `sync_scenes` now tries `satellites=` first and falls back to
  `satellite=` on `TypeError`, so it works against either PyGeoVision build.

### 2.4 Robustness: heavy client built for DB-only task
`SatelliteProcessor.__init__` eagerly imported PyGeoVision and constructed a
client. The hourly `update_flood_risk_zones` Celery beat task only touches
the database but still paid that cost and *required* PyGeoVision to be
installed.

- **Fix:** the PyGeoVision client is now a lazy `@property`. Constructing a
  `SatelliteProcessor` is cheap; the import happens only on first
  search/download/preprocess use. The hourly risk-zone task now runs even on
  a node without PyGeoVision installed.

---

## 3. New feature: Live Weather & Rainfall Forecast page

Rainfall is the leading indicator of Accra flash flooding — this page is the
forward-looking counterpart to the satellite flood maps (which show standing
water *now*).

**Backend** — `src/apps/satellite/weather.py` (new)
- Data source: **Open-Meteo** (free, no API key — chosen so a missing/expired
  key can never silently disable flood early-warning). Standard-library
  `urllib` only; adds no new dependency.
- `fetch_accra_forecast()` — current conditions + 48h hourly + 7-day daily,
  with a flood-focused **rainfall outlook** (rolling 3h/6h/24h rain totals,
  peak-rain hour, and a 5-band flood-risk classification tuned for Accra:
  none/low/moderate/high/extreme).
- `fetch_zone_rainfall_forecasts()` — per-FloodZone 24h rainfall outlook
  cross-referenced against each zone's own `rainfall_threshold_mm`, flagging
  exactly which communities are forecast to exceed their flood trigger.
- 15-minute server-side caching (so many viewers don't each hit upstream);
  graceful degradation — on any upstream failure callers get a structured
  `{"available": False, "error": ...}` payload, never an exception.

**API** — `apps/dashboard/api_views.py` + `api_urls.py`
- `GET /api/dashboard/weather/forecast/`
- `GET /api/dashboard/weather/zone-rainfall/`

**Page** — `src/templates/dashboard/weather.html` (new), view + URL +
nav link wired in (`/dashboard/weather/`). Detailed current-conditions hero,
flood rainfall-outlook KPIs with risk pill, 48h hourly rain/temp combo chart,
24h rain-probability area chart, 7-day forecast cards, per-zone rainfall
table vs thresholds, and a live RainViewer precipitation-radar map.
Auto-refreshes every 10 minutes.

---

## 4. Enriched satellite analytics pages

Both were previously thin shells. Backed by 4 new aggregation endpoints:
- `GET /api/dashboard/stats/satellite/overview/`
- `GET /api/dashboard/stats/satellite/flood-area-trend/`
- `GET /api/dashboard/stats/satellite/area-by-zone/`
- `GET /api/dashboard/stats/historical-flood-trend/`

**`src/templates/satellite/flood_maps.html`** — rebuilt with KPI cards
(maps generated, total flooded area, IoT-confirmed share, scenes ingested),
flood-extent-over-time trend chart, scene-pipeline-health donut, flooded-area-
by-community bar chart, a latest-flood-extent Leaflet map, and the existing
server-rendered card grid (kept as a no-JS fallback).

**`src/templates/satellite/timeseries.html`** — rebuilt with KPI cards
(events, casualties, displaced, worst year), casualties/displacement trend,
events-per-year bars, and a rainfall-vs-human-impact bubble chart. Now loads
from the API (auto-refreshable) instead of baking data into the template.

---

## 5. Tests added

- `tests/test_weather.py` — 12 tests: weather-code labels, rain-band
  classification, graceful upstream failure, payload shaping, caching,
  per-zone threshold flagging, both API endpoints, page render.
- `tests/test_dashboard_analytics.py` — 7 tests: satellite overview (incl.
  empty-deployment case), flood-area trend, area-by-zone, historical trend
  aggregation, and both page renders.

---

## 6. Files NOT changed by this audit (pre-existing in your upload)

`README.md`, `scripts/seed_demo_data.py`, and
`src/templates/dashboard/map.html` already had uncommitted modifications in
the working tree you uploaded. Those are your in-progress changes; they were
left untouched.

---

## Verifying locally

```bash
pip install -r requirements.txt           # now includes django-jazzmin
# Real stack (PostGIS): use docker-compose, then:
docker compose exec web pytest             # full suite

# The satellite flood pipeline activates once PyGeoVision is installed:
#   pip install -e /path/to/pygeovision   (or the 2.0.8 wheel)
# Until then the rest of the system — including all 76 tests — runs without it.
```

Note on running the suite outside Docker: the project's `conftest.py` targets
PostGIS (correct for production, since several geospatial lookups are
PostGIS-specific). During this audit the suite was additionally validated
against a SpatiaLite configuration to run in a sandbox; that audit-only
settings file was not added to the project.
