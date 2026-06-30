# FloodWatch Ghana

Hybrid IoT + satellite flood monitoring system for Accra, Ghana — covering
the Odaw River basin, Korle Lagoon, and surrounding low-lying communities.
Combines ESP32 water-level/rain-gauge sensors, PyGeoVision satellite flood
detection (Sentinel-1 SAR + Sentinel-2 optical), and WhatsApp/SMS community
alerts on a Django + PostGIS backend.

## Project status: All 5 phases complete

| Phase | Scope | Status |
|---|---|---|
| 1 | Django+PostGIS foundation, all 10 data models, admin, base API | ✅ Done |
| 2 | MQTT ingestion, WebSocket live updates, sensor threshold checks | ✅ Done |
| 3 | PyGeoVision satellite pipeline, flood detection, Celery scheduling | ✅ Done |
| 4 | Twilio WhatsApp/SMS alerts, community reports, alert rules engine | ✅ Done |
| 5 | Dashboard UI (Larkon theme integration), deployment hardening | ✅ Done |

## What's working

**Data layer (Phase 1):** 10 PostGIS-backed models, custom User model,
settings split (base/dev/production with fail-loud secret validation),
22 tests.

**IoT pipeline (Phase 2):** MQTT bridge (`apps.sensors.mqtt_client`, paho-mqtt
2.x `CallbackAPIVersion.VERSION2`) ingests ESP32 readings via Celery
(`ingest_sensor_reading`), validates payload ranges, broadcasts live over
WebSocket (`/ws/sensors/`), and runs both an immediate per-reading threshold
check and a 5-minute periodic safety-net sweep
(`apps.sensors.tasks.check_sensor_thresholds`).

**Satellite pipeline (Phase 3):** `apps.satellite.processors.SatelliteProcessor`
implements search → download → `prepare_for_ai()` → MNDWI flood detection →
per-zone area calculation (raster-space, CRS-correct) → `FloodMap` storage →
alert dispatch, orchestrated by 3 Celery tasks matching the beat schedule.

**Alerts (Phase 4):** `AlertRules` engine (4-tier severity, combined-source
escalation, cooldown suppression) + Twilio notification module with
automatic WhatsApp→SMS fallback + delivery-status webhook handling +
community report submission/verification workflow. 35 tests covering rules,
ingestion validation, and mocked Twilio delivery.

**Dashboard (Phase 5):** Full Larkon Bootstrap theme integration — live
Leaflet.js map (sensors + flood zones + flood extent + verified reports),
ApexCharts sensor time-series, alert feed with WebSocket live updates,
community report submission with geolocation, threshold management UI,
manual satellite-run trigger — all wired to the real REST API, not mocked
data.

## Dashboard statistics & charts (latest update)

The dashboard now has a dedicated stats API (`apps.dashboard.api_views`,
mounted under `/api/dashboard/stats/`) backing 6 chart endpoints, with
ApexCharts widgets wired across 4 pages:

| Page | Charts |
|---|---|
| Dashboard (`/dashboard/`) | 4 live KPI cards, water-level+rainfall combo trend (selectable 24h/3d/7d range), flood-risk-by-zone donut, station-status donut, 30-day alerts stacked bar, most-affected-zones horizontal bar |
| Sensors (`/dashboard/sensors/`) | Battery-level horizontal bar (colour-coded by station status, flags stations needing a field visit), network status donut, per-station 24h water-level sparkline (existing, kept) |
| Alerts (`/dashboard/alerts/`) | 7-day rainfall bar chart correlated with the alert timeline below it |
| Reports (`/dashboard/reports/`) | Severity distribution donut + verified/unverified counter cards (computed server-side, not approximated client-side) |

All charts auto-refresh: KPI cards and donuts poll every 60s and also
re-fetch immediately on any live `floodwatch:sensor-reading` or
`floodwatch:alert` WebSocket event (see `static/js/floodwatch-realtime.js`),
so the dashboard updates without a manual page reload as new sensor data or
alerts arrive.

## Comprehensive demo/test seed data

For development and demoing, `scripts/seed_demo_data.py` populates roughly
10 records across **every** model in the system (not just the 3 zones from
`init_database.py`):

```bash
docker compose exec web python manage.py migrate
docker compose exec web python scripts/seed_demo_data.py
# or, to wipe and reseed:
docker compose exec web python scripts/seed_demo_data.py --clear
```

Creates: 10 flood zones (across real Accra communities), 10 users (mixed
admin/field-officer/community roles), 10 sensor stations each with a full
**48-hour, 30-minute-interval reading history** (96 readings/station, with
a simulated storm bump so the trend charts show something realistic rather
than flat noise), 10 satellite scenes, 10 flood maps, 10 flood events (3
left active), 10 alert recipients, 10 alerts spanning every delivery
status, 10 community reports (mixed verified/unverified), and 10 historical
flood records spanning 2019–2024.

After seeding, every chart on `/dashboard/` has real, varied data to show
immediately — no need to wait for live sensors or a satellite cycle to
populate the dashboard for a demo.

Demo login: any seeded username (printed by the script, e.g. `ama.owusu0`)
with password `demo-password-not-for-production`.

**A bug caught while building this:** `MultiPolygon([child_polygon])`
(Django's GEOS wrapper) does **not** inherit the SRID from its child
geometry — it comes back `srid=None`, which PostGIS would reject for a
field declared `srid=4326`. The production satellite pipeline
(`apps.satellite.processors`) was already setting SRID explicitly via
`GEOSGeometry(geojson, srid=4326)`, so it was unaffected — but the seed
script's `FloodMap.extent_geometry` construction had this exact bug on
first pass. Fixed by setting `.srid = 4326` explicitly after construction.

## Advanced interactive map (latest update)

`/dashboard/map/` is now a full risk-communication tool, not just a marker
viewer:

- **Risk-intensity heatmap** (Leaflet.heat) — weighted by *current water
  level ÷ that station's zone threshold* (capped at 2×), not raw cm values,
  so stations with very different baselines are genuinely comparable on
  one colour scale.
- **Rich sensor popups** — current reading, rising/falling/steady trend
  vs the 24h average, 24h min/max/avg, total rainfall, battery, and a
  visual risk-ratio bar — all from one new endpoint
  (`/api/dashboard/stats/station/<id>/detail/`) instead of the client
  stitching together several requests.
- **Composite zone risk scores** (`/api/dashboard/stats/zone-risk-scores/`)
  — 0-100, combining sensor proximity to threshold + active event severity
  + recent severe community reports — shown as a sortable ranked list in
  the map's sidebar panel, with zone fill opacity scaled to the score.
- **Marker clustering** for sensors and community reports (Leaflet.markercluster)
  so the map stays readable as the network grows past a handful of stations.
- **Click-to-inspect sidebar** — clicking any sensor or zone updates a
  persistent detail panel (not just a popup that disappears), with a
  legend explaining exactly what the heatmap and risk colours mean.

### A real bug caught while building this

`GeoFeatureModelSerializer` (djangorestframework-gis) does **not** put the
model's `id` inside `properties` — it pulls it to the GeoJSON Feature's
top-level `feature.id` instead, since `id_field` defaults to the model's
primary key name whenever `id` is in the serializer's `fields` list. My
first pass at `map.html` referenced `f.properties.id` everywhere a click
handler needed to fetch station/zone detail data — all silently `undefined`.
Fixed by using `f.id` (verified against the actual
`GeoFeatureModelSerializer.to_representation()` source, not just an assumption).

## A few real bugs caught and fixed during this build

1. **`celery/` directory name collision** (Phase 1) — shadowed the real
   `celery` PyPI package. Renamed to `celery_tasks/`.
2. **CRS mismatch in flood area calculation** (Phase 3) — vectorised flood
   masks were in the raster's native UTM CRS but compared against WGS84
   zone geometries without reprojection. Fixed with explicit
   `rasterio.warp.transform_geom` calls and a raster-space zonal area
   calculation that never round-trips through degree/metre approximations.
3. **`get_or_create()` with an `__isnull` lookup** (Phase 4) — would crash
   on creation since `ended_at__isnull=True` isn't a valid model
   constructor kwarg. Replaced with explicit filter + create.
4. **`@api_view` decorator on a ViewSet method** (Phase 4) — incompatible
   with DRF's router-based URL generation. Replaced with `@action`.
5. **Unconditional Redis call in a global context processor** (Phase 5) —
   `flood_status` (injected into every page render) would have taken down
   the entire site on a Redis blip. Now degrades gracefully to "compute
   fresh, skip caching" on any cache backend error.
6. **paho-mqtt API version mismatch** (Phase 2) — `requirements.txt`
   pinned the deprecated 1.6.1 callback signature; code now targets 2.x's
   explicit `CallbackAPIVersion.VERSION2`, matching the actually-pinned version.
7. **Dockerfile path bug** (Phase 5) — `deployment/` was never copied into
   the image, and the gunicorn config path was relative to the wrong
   `WORKDIR` at `CMD` time, which would have crashed every container start.

## Getting started

```bash
git clone <repo> floodwatch_ghana && cd floodwatch_ghana
cp .env.example .env          # fill in DB password, Twilio keys, etc.
docker compose up --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
docker compose exec web python scripts/init_database.py
docker compose exec web python scripts/setup_satellite_monitoring.py
```

Then visit:
- `http://localhost:8000/dashboard/` — the live dashboard
- `http://localhost:8000/admin/` — Django admin (manage zones, stations, alerts)
- `http://localhost:8000/api/docs/` — Swagger API documentation
- `ws://localhost:8001/ws/sensors/` — live sensor WebSocket stream

See `docs/deployment/deployment_guide.md` for production deployment
(Nginx + SSL + scaling notes) and `docs/user_guide/user_guide.md` for how
to use the system day-to-day.

### Running tests

```bash
docker compose exec web pytest -v          # 57 tests across all 5 phases
```

Tests run against real PostGIS — no SQLite/SpatiaLite shortcut, since
GeoDjango's spatial lookups are PostGIS-specific.

### Manually testing the IoT pipeline without real ESP32 hardware

```bash
docker compose exec web python manage.py shell -c "
from apps.sensors.mqtt_client import publish_test_reading
publish_test_reading('ESP32-ALJ-001', water_level_cm=65.0, rainfall_mm=12.0)
"
```

## Project structure

```
floodwatch_ghana/
├── manage.py               -> src/manage.py
├── requirements.txt
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── src/
│   ├── floodwatch/          settings/, urls.py, wsgi.py, asgi.py, celery.py
│   └── apps/
│       ├── core/            Shared abstract models (TimeStampedModel, SeverityLevel)
│       ├── users/           Custom User model (phone, role, alert prefs)
│       ├── sensors/         Models, MQTT bridge, Celery ingestion tasks, API, WS routing
│       ├── satellite/       PyGeoVision pipeline (processors.py), indices, Celery tasks, API
│       ├── alerts/          Rules engine, Twilio notification, Celery tasks, community reports API
│       └── dashboard/       Server-rendered views + Larkon-theme templates
├── celery_tasks/             Documented placeholder (real tasks live in each app's tasks.py)
├── scripts/                  init_database.py, deploy_sensors.py, setup_satellite_monitoring.py
├── tests/                    57 tests across all 5 phases
├── docs/
│   ├── api/api_overview.md
│   ├── deployment/deployment_guide.md
│   └── user_guide/user_guide.md
└── deployment/
    ├── nginx/floodwatch.conf
    ├── gunicorn/gunicorn.conf.py
    └── docker/mosquitto.conf
```

## Honest gaps

- **No live PostGIS in this build environment** — every check that
  doesn't require a live DB connection (model definitions, migrations,
  URL resolution, template rendering, Celery task registration, pure-logic
  unit tests run directly) has been run and passes. Full `migrate` and the
  full `pytest` run against real data happen via `docker compose up` on
  your machine.
- **PyGeoVision is not on public PyPI** — install it from your own
  source/wheel (see the note in `requirements.txt`); the satellite pipeline
  imports it lazily specifically so the rest of the project works before
  it's installed.
- **JWT token-obtain endpoint not yet wired** — `djangorestframework-simplejwt`
  is configured as the primary auth backend, but `/api/token/` isn't routed
  yet; session auth (log in via `/accounts/login/`) works for all current
  endpoints. Add `path("api/token/", TokenObtainPairView.as_view())` when a
  mobile client needs token-based auth.
- **SAR (Sentinel-1) flood detection is metadata-only** — the pipeline
  downloads and catalogues SAR scenes but only runs MNDWI flood detection
  on Sentinel-2 optical; a backscatter-threshold SAR detector is a natural
  next addition for cloud-covered periods when optical isn't available.
