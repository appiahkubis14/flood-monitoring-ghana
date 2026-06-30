"""
Tests for the live weather + rainfall-forecast feature.

The upstream Open-Meteo HTTP call is always mocked here -- tests must never
depend on network access or on a third-party service being up, and a
flood-warning system's test suite especially must be deterministic. We test
the parts we own: response shaping, flood-risk classification of rainfall,
graceful degradation on upstream failure, caching, and the API endpoints.
"""
from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Polygon
from django.core.cache import cache
from django.urls import reverse

from apps.satellite import weather


@pytest.fixture(autouse=True)
def _clear_weather_cache():
    cache.delete(weather.FORECAST_CACHE_KEY)
    cache.delete("floodwatch:weather:zones:v1")
    yield
    cache.delete(weather.FORECAST_CACHE_KEY)
    cache.delete("floodwatch:weather:zones:v1")


def _fake_openmeteo():
    return {
        "current": {
            "time": "2026-06-30T12:00", "temperature_2m": 27.5,
            "apparent_temperature": 30.1, "relative_humidity_2m": 82,
            "precipitation": 0.4, "rain": 0.4, "wind_speed_10m": 14,
            "wind_direction_10m": 200, "surface_pressure": 1009,
            "cloud_cover": 75, "weather_code": 63,
        },
        "hourly": {
            "time": ["2026-06-30T12:00", "2026-06-30T13:00", "2026-06-30T14:00"],
            "temperature_2m": [27, 28, 29], "precipitation": [10, 25, 20],
            "rain": [10, 25, 20], "precipitation_probability": [80, 90, 85],
            "relative_humidity_2m": [80, 78, 75], "wind_speed_10m": [12, 14, 15],
            "weather_code": [63, 65, 63],
        },
        "daily": {
            "time": ["2026-06-30", "2026-07-01"],
            "temperature_2m_max": [30, 31], "temperature_2m_min": [24, 25],
            "precipitation_sum": [55, 12], "rain_sum": [55, 12],
            "precipitation_probability_max": [95, 60], "precipitation_hours": [8, 3],
            "wind_speed_10m_max": [20, 18], "weather_code": [65, 63],
            "sunrise": ["2026-06-30T05:50"], "sunset": ["2026-06-30T18:10"],
        },
    }


def test_weather_code_label():
    assert weather.weather_code_label(0) == "Clear sky"
    assert weather.weather_code_label(65) == "Heavy rain"
    assert weather.weather_code_label(None) == "Unknown"
    assert weather.weather_code_label(99999) == "Unknown"


@pytest.mark.parametrize("rain_3h,expected", [
    (0.0, "none"), (6.0, "low"), (20.0, "moderate"), (35.0, "high"), (60.0, "extreme"),
])
def test_rain_classification_bands(rain_3h, expected):
    assert weather._classify_rain_3h(rain_3h)["level"] == expected


def test_fetch_forecast_graceful_failure_returns_structured_payload():
    with patch.object(weather, "_http_get_json", return_value=None):
        result = weather.fetch_accra_forecast(force_refresh=True)
    assert result["available"] is False
    assert "error" in result
    assert "location" in result


def test_fetch_forecast_shapes_payload_and_classifies_flood_risk():
    with patch.object(weather, "_http_get_json", return_value=_fake_openmeteo()):
        result = weather.fetch_accra_forecast(force_refresh=True)

    assert result["available"] is True
    assert result["current"]["temperature_c"] == 27.5
    assert result["current"]["weather_label"] == "Moderate rain"
    assert len(result["hourly"]) == 3
    assert len(result["daily"]) == 2
    assert result["daily"][0]["weather_label"] == "Heavy rain"

    outlook = result["rainfall_outlook"]
    assert outlook["next_3h_rain_mm"] == 55.0   # 10+25+20
    assert outlook["risk_level"] == "extreme"   # >=50mm/3h
    assert outlook["peak_rain_mm"] == 25.0


def test_fetch_forecast_is_cached():
    with patch.object(weather, "_http_get_json", return_value=_fake_openmeteo()) as mocked:
        weather.fetch_accra_forecast(force_refresh=True)
        weather.fetch_accra_forecast()  # should hit cache, not the network
    assert mocked.call_count == 1


@pytest.mark.django_db
def test_zone_rainfall_flags_threshold_exceedance():
    from apps.satellite.models import FloodZone

    FloodZone.objects.create(
        name="Test Basin",
        geometry=Polygon(((-0.22, 5.55), (-0.20, 5.55), (-0.20, 5.58), (-0.22, 5.58), (-0.22, 5.55)), srid=4326),
        rainfall_threshold_mm=30,
        population_estimate=85000,
        current_risk_level="green",
    )
    # 40mm forecast over 24h, threshold 30mm -> must flag exceedance.
    fake = {"hourly": {"rain": [40.0] + [0.0] * 23, "precipitation_probability": [90] + [10] * 23}}
    with patch.object(weather, "_http_get_json", return_value=fake):
        zones = weather.fetch_zone_rainfall_forecasts()

    assert len(zones) == 1
    assert zones[0]["rain_24h_mm"] == 40.0
    assert zones[0]["exceeds_threshold"] is True
    assert zones[0]["max_precip_probability_pct"] == 90


@pytest.mark.django_db
def test_weather_forecast_api_endpoint(client):
    with patch.object(weather, "_http_get_json", return_value=_fake_openmeteo()):
        resp = client.get("/api/dashboard/weather/forecast/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["rainfall_outlook"]["risk_level"] == "extreme"


@pytest.mark.django_db
def test_weather_page_renders(client):
    resp = client.get(reverse("dashboard:weather"))
    assert resp.status_code == 200
    assert b"Live Weather" in resp.content
    assert b"Flood Rainfall Outlook" in resp.content
