# FloodWatch Ghana — API Overview

Full interactive documentation: `GET /api/docs/` (Swagger UI, via drf-spectacular).
Raw OpenAPI schema: `GET /api/schema/`.

## Authentication

JWT (via `djangorestframework-simplejwt`) for authenticated endpoints, plus
Django session auth for browser-based dashboard requests. Public endpoints
(marked below) require no authentication at all.

```bash
# Obtain a token pair (not yet wired to a dedicated endpoint in this build --
# add path("api/token/", TokenObtainPairView.as_view()) to a future urls.py
# update, or authenticate via the Django session for now: log in at
# /accounts/login/ and the session cookie authenticates subsequent API calls)
```

## Sensors (`apps.sensors`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/sensors/` | Public | All stations, GeoJSON FeatureCollection |
| GET | `/api/sensors/{id}/` | Public | Single station detail |
| GET | `/api/sensors/{id}/readings/?hours=24` | Public | Time-series readings |
| POST | `/api/sensors/` | Admin | Register a new station |
| GET | `/api/sensor-readings/` | Public | Raw reading list (paginated; prefer the per-station endpoint above) |

## Satellite (`apps.satellite`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/flood-zones/` | Public | All flood risk zones, GeoJSON |
| GET | `/api/flood-zones/{id}/risk/` | Public | Current risk level only |
| GET | `/api/flood-maps/` | Public | All generated flood maps |
| GET | `/api/flood-maps/latest/?zone=<id>` | Public | Most recent flood map |
| GET | `/api/satellite-scenes/` | Public | Discovered/processed scene metadata |
| POST | `/api/admin/satellite/run/` | Admin | Trigger a monitoring cycle now (returns Celery task id) |

## Alerts (`apps.alerts`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/flood-events/` | Public | Flood event timeline |
| GET | `/api/alerts/` | Own / Admin | Alert delivery history (own alerts, or all if staff) |
| POST | `/api/alerts/subscribe/` | Public | Self-service phone-number subscription |
| GET/POST | `/api/community-reports/` | Public | List / submit a community flood report |
| POST | `/api/community-reports/{uuid}/verify/` | Authenticated | Mark a report verified |
| POST | `/api/admin/alerts/broadcast/` | Admin | Send a manual broadcast message |
| PUT | `/api/admin/thresholds/` | Admin | Update a zone's water-level/rainfall thresholds |
| POST | `/api/webhooks/twilio/status/` | None (Twilio) | Delivery-status webhook callback |

## WebSockets

| Path | Purpose |
|---|---|
| `ws://<host>:8001/ws/sensors/` | Live `SensorReading` broadcasts as they're ingested |
| `ws://<host>:8001/ws/alerts/` | Live `Alert` broadcasts as they're dispatched |

Both run on Daphne (port 8001), separate from the Gunicorn HTTP port —
see `docker-compose.yml`'s `websocket` service.

## Rate limiting

Global defaults (see `REST_FRAMEWORK.DEFAULT_THROTTLE_RATES` in
`settings/base.py`): 60 requests/minute for anonymous callers, 300/minute
for authenticated users. Community-facing endpoints (`/api/alerts/subscribe/`,
`/api/community-reports/`) rely on these global limits rather than a
stricter per-endpoint override — tighten further here if abuse is observed
in production.
