# FloodWatch Ghana — Deployment Guide

## Local development

```bash
cp .env.example .env          # fill in DB password at minimum for local dev
docker compose up --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
docker compose exec web python scripts/init_database.py
docker compose exec web python scripts/setup_satellite_monitoring.py
```

The `nginx` service has `profiles: ["production"]` and does **not** start
with a plain `docker compose up` — in local development you talk to
Gunicorn directly on `:8000` and Daphne directly on `:8001`. Nginx (with
real Let's Encrypt certificates) only makes sense once you have a real
domain pointed at the server.

## Production deployment

1. **Provision a server** (Ubuntu 22.04+ recommended, with Docker + Docker
   Compose plugin installed) and point your domain's A record at it.

2. **Copy the project** and create a production `.env`:
   ```bash
   cp .env.example .env
   ```
   Fill in, at minimum: `DJANGO_SECRET_KEY` (generate a real random 50-char
   value — never reuse the example), `DJANGO_ALLOWED_HOSTS=floodwatch.gh,www.floodwatch.gh`,
   `DB_PASSWORD`, `TWILIO_*` credentials, `DJANGO_SETTINGS_MODULE=floodwatch.settings.production`.

   Production settings (`src/floodwatch/settings/production.py`) **refuse to
   start** if `DJANGO_SECRET_KEY`, `DB_PASSWORD`, or `DJANGO_ALLOWED_HOSTS`
   are missing — this is intentional; it's far better to fail loudly at
   startup than to silently run with an insecure default secret key.

3. **Obtain SSL certificates** before starting the `nginx` profile:
   ```bash
   docker run -it --rm -v /etc/letsencrypt:/etc/letsencrypt \
     -v /var/www/certbot:/var/www/certbot \
     certbot/certbot certonly --webroot -w /var/www/certbot \
     -d floodwatch.gh -d www.floodwatch.gh
   ```

4. **Start the full stack including Nginx:**
   ```bash
   docker compose --profile production up -d --build
   docker compose exec web python manage.py migrate
   docker compose exec web python manage.py collectstatic --noinput
   docker compose exec web python manage.py createsuperuser
   docker compose exec web python scripts/init_database.py
   ```

5. **Install PyGeoVision** (not on public PyPI — see the note in
   `requirements.txt`) inside the `web`, `celery_worker`, and `mqtt_bridge`
   containers, or bake it into a custom image layer if you maintain your
   own registry. Then verify with:
   ```bash
   docker compose exec web python scripts/setup_satellite_monitoring.py
   ```

6. **Set up SSL renewal** (certbot's systemd timer handles this on the host
   if certbot was installed there; if running certbot only via the
   container above, add a cron job that re-runs the certonly command
   monthly and reloads nginx).

## Service architecture in production

| Service | Process | Purpose |
|---|---|---|
| `nginx` | Nginx | TLS termination, static/media serving, WS upgrade proxy |
| `web` | Gunicorn | Django views + REST API (HTTP only) |
| `websocket` | Daphne | Live sensor/alert WebSocket streams |
| `celery_worker` | Celery | Async tasks: ingestion, alerts, satellite processing |
| `celery_beat` | Celery beat | Schedules the periodic tasks (see `CELERY_BEAT_SCHEDULE`) |
| `mqtt_bridge` | `run_mqtt_bridge` mgmt command | Long-lived MQTT subscriber, feeds Celery |
| `mosquitto` | Mosquitto | MQTT broker for ESP32 sensor stations |
| `db` | PostGIS | All persistent data |
| `redis` | Redis | Celery broker/result backend, Channels layer, Django cache |

## Scaling notes

- `celery_worker` can be scaled horizontally (`docker compose up --scale celery_worker=3`)
  — task bodies are idempotent enough for this (e.g. `ingest_sensor_reading`
  rejects on unknown station rather than crashing, `create_and_send_alerts`
  is cooldown-gated so duplicate dispatches from a race are rare and
  harmless even when they do occur).
- `web` (Gunicorn) workers are already sized via `(2 × CPU) + 1` in
  `deployment/gunicorn/gunicorn.conf.py` — increase `GUNICORN_WORKERS` env
  var rather than editing the file for a specific deployment's CPU count.
- `mqtt_bridge` must run as exactly **one** instance — Mosquitto delivers
  each message once per *subscribed client*, so running two bridge
  instances would double-ingest every sensor reading.
