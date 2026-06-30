"""
Live weather + rainfall-forecast service for FloodWatch Ghana.

Flooding in Accra is rainfall-driven: the Odaw basin and Korle Lagoon flood
when intense rain falls faster than the drainage can carry it away. Satellite
flood mapping (apps.satellite.processors) tells us where water *is now*;
this module tells us where heavy rain is *about to arrive*, which is the
single most actionable early-warning signal a community can get -- often
hours before any gauge rises.

Data source: Open-Meteo (https://open-meteo.com).
  * Free, no API key, no rate-limit registration required -- chosen
    deliberately so a missing/expired key can never silently disable
    flood early-warning in an emergency.
  * Global model coverage including Accra; hourly + daily forecasts.

Everything here is read-only and side-effect-free except for caching the
fetched forecast (so the dashboard's auto-refresh and many concurrent
viewers don't each hit Open-Meteo). Network failures degrade gracefully:
callers get a structured ``{"available": False, "error": ...}`` payload
rather than an exception, so the weather page can show a clear "forecast
temporarily unavailable" state instead of erroring the whole request.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone as dt_timezone
from typing import Any, Optional

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger("apps.satellite")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Cache the forecast for 15 minutes. Open-Meteo's model updates roughly
# hourly, so 15 min is fresh enough for flood early-warning while keeping
# us comfortably within fair-use even with many dashboard viewers.
FORECAST_CACHE_TTL_SECONDS = 15 * 60
FORECAST_CACHE_KEY = "floodwatch:weather:accra:v1"

# Rainfall intensity bands (mm in a rolling window) used to translate raw
# numbers into a flood-risk label a non-technical community officer can act
# on. Thresholds are tuned for Accra's flash-flood behaviour, where even
# ~30 mm in a few hours over the Odaw basin can overwhelm drainage.
RAIN_BANDS_3H = [
    (50.0, "extreme", "Severe flash-flood risk — move to higher ground"),
    (30.0, "high", "High flood risk — avoid low-lying areas and drains"),
    (15.0, "moderate", "Moderate risk — monitor local water levels"),
    (5.0, "low", "Light rain — minimal flood risk"),
    (0.0, "none", "No significant rain expected"),
]


def _accra_center() -> tuple[float, float]:
    """(lat, lon) centre of the configured Accra study bbox."""
    minlon, minlat, maxlon, maxlat = settings.ACCRA_BBOX
    return ((minlat + maxlat) / 2.0, (minlon + maxlon) / 2.0)


def _classify_rain_3h(rain_mm_3h: float) -> dict[str, str]:
    for threshold, level, advice in RAIN_BANDS_3H:
        if rain_mm_3h >= threshold:
            return {"level": level, "advice": advice}
    return {"level": "none", "advice": RAIN_BANDS_3H[-1][2]}


def _http_get_json(url: str, params: dict[str, Any], timeout: int = 12) -> Optional[dict]:
    """GET ``url?params`` and parse JSON, returning ``None`` on any failure.

    Uses only the standard library (urllib) so the weather feature adds no
    new third-party dependency to the project.
    """
    query = urllib.parse.urlencode(params, doseq=True)
    full_url = f"{url}?{query}"
    try:
        req = urllib.request.Request(full_url, headers={"User-Agent": "FloodWatch-Ghana/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                logger.warning("Open-Meteo returned HTTP %s", resp.status)
                return None
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        logger.warning("Open-Meteo request failed: %s", exc)
        return None
    except (ValueError, TimeoutError) as exc:
        logger.warning("Open-Meteo response could not be parsed: %s", exc)
        return None


def fetch_accra_forecast(force_refresh: bool = False) -> dict[str, Any]:
    """Fetch (and cache) the current weather + 7-day forecast for Accra.

    Returns a structured dict the weather API endpoint serialises directly:

    ``{"available": True, "current": {...}, "hourly": [...],
       "daily": [...], "rainfall_outlook": {...}, "fetched_at": iso}``

    On failure returns ``{"available": False, "error": str, "fetched_at": iso}``
    so the frontend can render a clear unavailable state.
    """
    if not force_refresh:
        cached = cache.get(FORECAST_CACHE_KEY)
        if cached is not None:
            return cached

    lat, lon = _accra_center()
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "timezone": "Africa/Accra",
        "current": ",".join([
            "temperature_2m", "relative_humidity_2m", "apparent_temperature",
            "precipitation", "rain", "weather_code", "wind_speed_10m",
            "wind_direction_10m", "surface_pressure", "cloud_cover",
        ]),
        "hourly": ",".join([
            "temperature_2m", "precipitation_probability", "precipitation",
            "rain", "weather_code", "relative_humidity_2m", "wind_speed_10m",
        ]),
        "daily": ",".join([
            "weather_code", "temperature_2m_max", "temperature_2m_min",
            "precipitation_sum", "rain_sum", "precipitation_probability_max",
            "precipitation_hours", "wind_speed_10m_max", "sunrise", "sunset",
        ]),
        "forecast_days": 7,
        "forecast_hours": 48,
    }

    raw = _http_get_json(OPEN_METEO_URL, params)
    if raw is None:
        payload = {
            "available": False,
            "error": "Weather service temporarily unavailable. Retrying shortly.",
            "fetched_at": timezone.now().isoformat(),
            "location": {"lat": round(lat, 4), "lon": round(lon, 4), "name": "Greater Accra"},
        }
        # Cache the failure briefly (1 min) so a transient outage doesn't
        # hammer Open-Meteo on every page load while it recovers.
        cache.set(FORECAST_CACHE_KEY, payload, 60)
        return payload

    payload = _shape_forecast(raw, lat, lon)
    cache.set(FORECAST_CACHE_KEY, payload, FORECAST_CACHE_TTL_SECONDS)
    return payload


def _shape_forecast(raw: dict[str, Any], lat: float, lon: float) -> dict[str, Any]:
    """Transform Open-Meteo's columnar response into the row-oriented,
    flood-annotated structure the frontend consumes."""
    current = raw.get("current", {}) or {}

    hourly_src = raw.get("hourly", {}) or {}
    hourly_times = hourly_src.get("time", []) or []
    hourly = []
    for i, t in enumerate(hourly_times):
        hourly.append({
            "time": t,
            "temperature_c": _at(hourly_src, "temperature_2m", i),
            "precipitation_mm": _at(hourly_src, "precipitation", i),
            "rain_mm": _at(hourly_src, "rain", i),
            "precipitation_probability_pct": _at(hourly_src, "precipitation_probability", i),
            "humidity_pct": _at(hourly_src, "relative_humidity_2m", i),
            "wind_speed_kmh": _at(hourly_src, "wind_speed_10m", i),
            "weather_code": _at(hourly_src, "weather_code", i),
        })

    daily_src = raw.get("daily", {}) or {}
    daily_times = daily_src.get("time", []) or []
    daily = []
    for i, d in enumerate(daily_times):
        daily.append({
            "date": d,
            "temp_max_c": _at(daily_src, "temperature_2m_max", i),
            "temp_min_c": _at(daily_src, "temperature_2m_min", i),
            "precipitation_sum_mm": _at(daily_src, "precipitation_sum", i),
            "rain_sum_mm": _at(daily_src, "rain_sum", i),
            "precipitation_probability_max_pct": _at(daily_src, "precipitation_probability_max", i),
            "precipitation_hours": _at(daily_src, "precipitation_hours", i),
            "wind_speed_max_kmh": _at(daily_src, "wind_speed_10m_max", i),
            "weather_code": _at(daily_src, "weather_code", i),
            "sunrise": _at(daily_src, "sunrise", i),
            "sunset": _at(daily_src, "sunset", i),
            "weather_label": weather_code_label(_at(daily_src, "weather_code", i)),
        })

    rainfall_outlook = _build_rainfall_outlook(hourly, daily)

    return {
        "available": True,
        "location": {"lat": round(lat, 4), "lon": round(lon, 4), "name": "Greater Accra"},
        "fetched_at": timezone.now().isoformat(),
        "current": {
            "temperature_c": current.get("temperature_2m"),
            "apparent_temperature_c": current.get("apparent_temperature"),
            "humidity_pct": current.get("relative_humidity_2m"),
            "precipitation_mm": current.get("precipitation"),
            "rain_mm": current.get("rain"),
            "wind_speed_kmh": current.get("wind_speed_10m"),
            "wind_direction_deg": current.get("wind_direction_10m"),
            "surface_pressure_hpa": current.get("surface_pressure"),
            "cloud_cover_pct": current.get("cloud_cover"),
            "weather_code": current.get("weather_code"),
            "weather_label": weather_code_label(current.get("weather_code")),
            "observed_at": current.get("time"),
        },
        "hourly": hourly,
        "daily": daily,
        "rainfall_outlook": rainfall_outlook,
    }


def _build_rainfall_outlook(hourly: list[dict], daily: list[dict]) -> dict[str, Any]:
    """Derive the flood-relevant headline numbers from the raw forecast:
    rolling 3h / 6h / 24h rainfall totals + a single risk classification,
    plus the peak rain hour in the next 48h so an officer knows *when* the
    worst is expected, not just that it's coming."""
    def _safe(v):
        return v if isinstance(v, (int, float)) else 0.0

    next_3h = sum(_safe(h["rain_mm"]) for h in hourly[:3])
    next_6h = sum(_safe(h["rain_mm"]) for h in hourly[:6])
    next_24h = sum(_safe(h["rain_mm"]) for h in hourly[:24])

    classification = _classify_rain_3h(next_3h)

    peak_hour = None
    peak_rain = -1.0
    for h in hourly[:48]:
        r = _safe(h["rain_mm"])
        if r > peak_rain:
            peak_rain = r
            peak_hour = h["time"]

    today_total = _safe(daily[0]["rain_sum_mm"]) if daily else 0.0

    return {
        "next_3h_rain_mm": round(next_3h, 1),
        "next_6h_rain_mm": round(next_6h, 1),
        "next_24h_rain_mm": round(next_24h, 1),
        "today_rain_total_mm": round(today_total, 1),
        "risk_level": classification["level"],
        "advice": classification["advice"],
        "peak_rain_hour": peak_hour,
        "peak_rain_mm": round(max(peak_rain, 0.0), 1),
    }


def _at(columnar: dict[str, list], key: str, index: int):
    """Safe positional access into one of Open-Meteo's parallel arrays."""
    arr = columnar.get(key)
    if isinstance(arr, list) and 0 <= index < len(arr):
        return arr[index]
    return None


# WMO weather interpretation codes -> human label.
# https://open-meteo.com/en/docs (WMO Weather interpretation codes)
_WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


def weather_code_label(code: Optional[int]) -> str:
    if code is None:
        return "Unknown"
    try:
        return _WMO_CODES.get(int(code), "Unknown")
    except (TypeError, ValueError):
        return "Unknown"


def fetch_zone_rainfall_forecasts() -> list[dict[str, Any]]:
    """Per-flood-zone 24h rainfall outlook, used to colour the weather page's
    zone table and to cross-reference rain forecast against each community's
    own ``rainfall_threshold_mm``.

    To stay within fair-use we query Open-Meteo once per zone centroid but
    cache the whole list together; for the handful of Accra zones this is a
    small, bounded number of requests refreshed every 15 minutes.
    """
    cache_key = "floodwatch:weather:zones:v1"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    from apps.satellite.models import FloodZone

    results = []
    for zone in FloodZone.objects.all():
        centroid = zone.geometry.centroid
        params = {
            "latitude": round(centroid.y, 4),
            "longitude": round(centroid.x, 4),
            "timezone": "Africa/Accra",
            "hourly": "rain,precipitation_probability",
            "forecast_hours": 24,
        }
        raw = _http_get_json(OPEN_METEO_URL, params)
        rain_24h = 0.0
        max_prob = 0.0
        available = raw is not None
        if available:
            hourly = raw.get("hourly", {}) or {}
            rains = [r for r in (hourly.get("rain") or []) if isinstance(r, (int, float))]
            probs = [p for p in (hourly.get("precipitation_probability") or []) if isinstance(p, (int, float))]
            rain_24h = round(sum(rains), 1)
            max_prob = max(probs) if probs else 0.0

        threshold = zone.rainfall_threshold_mm or 0.0
        exceeds = bool(threshold and rain_24h >= threshold)
        results.append({
            "zone_id": zone.id,
            "zone_name": zone.name,
            "rain_24h_mm": rain_24h,
            "max_precip_probability_pct": max_prob,
            "rainfall_threshold_mm": threshold,
            "exceeds_threshold": exceeds,
            "population_estimate": zone.population_estimate,
            "available": available,
        })

    results.sort(key=lambda r: r["rain_24h_mm"], reverse=True)
    cache.set(cache_key, results, FORECAST_CACHE_TTL_SECONDS)
    return results
