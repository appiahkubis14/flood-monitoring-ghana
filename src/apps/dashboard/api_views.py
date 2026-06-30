"""
Aggregate statistics endpoints that power the dashboard's charts.

Deliberately kept separate from ``apps.dashboard.views`` (which renders the
HTML page shells) -- these are pure JSON aggregation endpoints, each one
backing exactly one chart widget, so a chart can be refreshed/re-fetched on
an interval without re-rendering the whole page, and so the same aggregate
queries could later be reused by a mobile client or a CSV export without
duplicating the SQL.

All endpoints are read-only and public (same trust level as the existing
``/api/flood-zones/`` etc.) -- none of this exposes anything more sensitive
than what's already visible on the public dashboard pages themselves.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncDate, TruncHour
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def overview_stats(request):
    """GET /api/dashboard/stats/overview/ -- the KPI numbers + the two
    donut charts (zone risk distribution, station status distribution) on
    the dashboard landing page.
    """
    from apps.alerts.models import Alert, CommunityReport, FloodEvent
    from apps.satellite.models import FloodZone
    from apps.sensors.models import SensorStation

    zone_risk = dict(
        FloodZone.objects.values_list("current_risk_level").annotate(n=Count("id")).order_by()
    )
    station_status = dict(
        SensorStation.objects.values_list("status").annotate(n=Count("id")).order_by()
    )
    report_severity = dict(
        CommunityReport.objects.values_list("severity").annotate(n=Count("id")).order_by()
    )
    alert_delivery_status = dict(
        Alert.objects.values_list("delivery_status").annotate(n=Count("id")).order_by()
    )

    return Response({
        "zone_risk_distribution": {
            "green": zone_risk.get("green", 0), "yellow": zone_risk.get("yellow", 0),
            "orange": zone_risk.get("orange", 0), "red": zone_risk.get("red", 0),
        },
        "station_status_distribution": {
            "online": station_status.get("online", 0), "offline": station_status.get("offline", 0),
            "maintenance": station_status.get("maintenance", 0), "faulty": station_status.get("faulty", 0),
        },
        "report_severity_distribution": {
            "minor": report_severity.get("minor", 0), "moderate": report_severity.get("moderate", 0),
            "severe": report_severity.get("severe", 0),
        },
        "alert_delivery_distribution": {
            "delivered": alert_delivery_status.get("delivered", 0),
            "sent": alert_delivery_status.get("sent", 0),
            "failed": alert_delivery_status.get("failed", 0),
            "suppressed": alert_delivery_status.get("suppressed", 0),
            "pending": alert_delivery_status.get("pending", 0),
        },
        "totals": {
            "active_events": FloodEvent.objects.filter(ended_at__isnull=True).count(),
            "total_zones": FloodZone.objects.count(),
            "total_stations": SensorStation.objects.count(),
            "total_alerts_24h": Alert.objects.filter(created_at__gte=timezone.now() - timedelta(hours=24)).count(),
            "total_reports_24h": CommunityReport.objects.filter(created_at__gte=timezone.now() - timedelta(hours=24)).count(),
        },
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def water_level_trend(request):
    """GET /api/dashboard/stats/water-level-trend/?hours=24 -- average
    water level across all stations, bucketed hourly, for the dashboard's
    main trend chart. Optionally scoped to one zone via ``?zone=<id>``.
    """
    from apps.sensors.models import SensorReading

    hours = int(request.query_params.get("hours", 24))
    zone_id = request.query_params.get("zone")
    since = timezone.now() - timedelta(hours=hours)

    qs = SensorReading.objects.filter(timestamp__gte=since)
    if zone_id:
        qs = qs.filter(station__flood_zone_id=zone_id)

    buckets = (
        qs.annotate(bucket=TruncHour("timestamp"))
          .values("bucket")
          .annotate(avg_water_level=Avg("water_level_cm"), avg_rainfall=Avg("rainfall_mm"), n=Count("id"))
          .order_by("bucket")
    )

    return Response({
        "buckets": [
            {
                "timestamp": b["bucket"].isoformat(),
                "avg_water_level_cm": round(b["avg_water_level"] or 0, 2),
                "avg_rainfall_mm": round(b["avg_rainfall"] or 0, 2),
                "reading_count": b["n"],
            }
            for b in buckets
        ]
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def alerts_trend(request):
    """GET /api/dashboard/stats/alerts-trend/?days=30 -- alerts sent per
    day, broken down by severity, for the stacked bar chart on the alerts
    page (and a condensed version on the dashboard landing page).
    """
    from apps.alerts.models import Alert

    days = int(request.query_params.get("days", 30))
    since = timezone.now() - timedelta(days=days)

    rows = (
        Alert.objects.filter(created_at__gte=since)
        .annotate(day=TruncDate("created_at"))
        .values("day", "severity")
        .annotate(n=Count("id"))
        .order_by("day")
    )

    by_day: dict[str, dict[str, int]] = {}
    for row in rows:
        day_key = row["day"].isoformat()
        by_day.setdefault(day_key, {"green": 0, "yellow": 0, "orange": 0, "red": 0})
        by_day[day_key][row["severity"]] = row["n"]

    return Response({
        "days": sorted(by_day.keys()),
        "series": {
            "yellow": [by_day[d]["yellow"] for d in sorted(by_day.keys())],
            "orange": [by_day[d]["orange"] for d in sorted(by_day.keys())],
            "red": [by_day[d]["red"] for d in sorted(by_day.keys())],
        },
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def rainfall_trend(request):
    """GET /api/dashboard/stats/rainfall-trend/?days=7 -- total rainfall
    per day, summed across all stations (or one zone via ``?zone=<id>``).
    """
    from apps.sensors.models import SensorReading

    days = int(request.query_params.get("days", 7))
    zone_id = request.query_params.get("zone")
    since = timezone.now() - timedelta(days=days)

    qs = SensorReading.objects.filter(timestamp__gte=since)
    if zone_id:
        qs = qs.filter(station__flood_zone_id=zone_id)

    rows = (
        qs.annotate(day=TruncDate("timestamp"))
          .values("day")
          .annotate(total_rainfall=Sum("rainfall_mm"))
          .order_by("day")
    )

    return Response({
        "days": [r["day"].isoformat() for r in rows],
        "total_rainfall_mm": [round(r["total_rainfall"] or 0, 1) for r in rows],
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def flood_events_by_zone(request):
    """GET /api/dashboard/stats/flood-events-by-zone/ -- total historical
    flood event count per zone, for the horizontal bar chart comparing
    which communities are most frequently affected.
    """
    from apps.alerts.models import FloodEvent

    rows = (
        FloodEvent.objects.values("flood_zone__name")
        .annotate(n=Count("id"))
        .order_by("-n")[:10]
    )
    return Response({
        "zones": [r["flood_zone__name"] for r in rows],
        "event_counts": [r["n"] for r in rows],
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def station_battery_levels(request):
    """GET /api/dashboard/stats/station-battery/ -- current battery level
    per station, for the horizontal bar chart on the sensors page flagging
    stations that need a field visit soon.
    """
    from apps.sensors.models import SensorStation

    stations = SensorStation.objects.order_by("battery_level").values("name", "battery_level", "status")[:20]
    return Response({
        "stations": [s["name"] for s in stations],
        "battery_levels": [s["battery_level"] for s in stations],
        "statuses": [s["status"] for s in stations],
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def map_heatmap_points(request):
    """GET /api/dashboard/stats/map-heatmap/ -- weighted points for the
    Leaflet.heat risk-intensity layer on the live map.

    Weight is a **normalised risk ratio** (current water level ÷ that
    station's zone threshold), not the raw water-level value -- two
    stations with very different baseline water levels (a wide river gauge
    vs a narrow drain gauge) are not comparable in absolute cm, but "how
    close is this station to its own flood threshold" is comparable across
    the whole network and is what actually communicates risk on the map.

    Stations with no recent reading or no assigned zone are excluded
    (there's nothing meaningful to show a risk ratio for).
    """
    from apps.sensors.models import SensorStation

    stations = (
        SensorStation.objects.filter(flood_zone__isnull=False)
        .select_related("flood_zone")
        .prefetch_related("readings")
    )

    points = []
    for station in stations:
        reading = station.latest_reading()
        if reading is None or not station.flood_zone.water_level_threshold_cm:
            continue
        ratio = reading.water_level_cm / station.flood_zone.water_level_threshold_cm
        # Clamp to [0, 2] -- beyond 2x threshold doesn't need to weight the
        # heatmap any hotter, it would just wash out the colour scale for
        # everything else on the map.
        intensity = round(min(max(ratio, 0.0), 2.0), 3)
        points.append({
            "lat": station.location.y,
            "lon": station.location.x,
            "intensity": intensity,
            "station_name": station.name,
            "water_level_cm": reading.water_level_cm,
            "threshold_cm": station.flood_zone.water_level_threshold_cm,
        })

    return Response({"points": points, "max_intensity": 2.0})


@api_view(["GET"])
@permission_classes([AllowAny])
def station_detail_stats(request, station_id):
    """GET /api/dashboard/stats/station/<id>/detail/ -- rich popup data for
    one sensor station: current reading, 24h min/max/avg, trend direction,
    and time since last report -- everything the map popup needs in one
    call instead of the client stitching together 3 separate requests.
    """
    from django.db.models import Avg, Max, Min

    from apps.sensors.models import SensorReading, SensorStation

    try:
        station = SensorStation.objects.select_related("flood_zone").get(pk=station_id)
    except SensorStation.DoesNotExist:
        return Response({"detail": "Station not found"}, status=404)

    since = timezone.now() - timedelta(hours=24)
    readings_24h = SensorReading.objects.filter(station=station, timestamp__gte=since)
    agg = readings_24h.aggregate(
        avg_water=Avg("water_level_cm"), max_water=Max("water_level_cm"), min_water=Min("water_level_cm"),
        total_rainfall=Sum("rainfall_mm"),
    )
    latest = station.latest_reading()

    # Trend: compare latest reading to the 24h average -- "rising" /
    # "falling" / "steady" is far easier for a non-technical user reading
    # a map popup to act on than a raw number on its own.
    trend = "steady"
    if latest and agg["avg_water"]:
        delta = latest.water_level_cm - agg["avg_water"]
        if delta > 5:
            trend = "rising"
        elif delta < -5:
            trend = "falling"

    risk_ratio = None
    if latest and station.flood_zone and station.flood_zone.water_level_threshold_cm:
        risk_ratio = round(latest.water_level_cm / station.flood_zone.water_level_threshold_cm, 2)

    return Response({
        "station": {
            "id": station.id, "name": station.name, "community": station.community,
            "status": station.status, "battery_level": station.battery_level,
            "zone_name": station.flood_zone.name if station.flood_zone else None,
            "last_reading_at": station.last_reading_at.isoformat() if station.last_reading_at else None,
        },
        "current": {
            "water_level_cm": latest.water_level_cm if latest else None,
            "rainfall_mm": latest.rainfall_mm if latest else None,
            "temperature_c": latest.temperature_c if latest else None,
            "timestamp": latest.timestamp.isoformat() if latest else None,
        },
        "last_24h": {
            "avg_water_level_cm": round(agg["avg_water"] or 0, 1),
            "max_water_level_cm": round(agg["max_water"] or 0, 1),
            "min_water_level_cm": round(agg["min_water"] or 0, 1),
            "total_rainfall_mm": round(agg["total_rainfall"] or 0, 1),
            "reading_count": readings_24h.count(),
        },
        "trend": trend,
        "risk_ratio": risk_ratio,  # >1.0 means currently above the zone's alert threshold
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def zone_risk_scores(request):
    """GET /api/dashboard/stats/zone-risk-scores/ -- a single composite
    0-100 risk score per zone, combining (a) how close the zone's online
    stations are to their threshold, (b) whether there's an active flood
    event, and (c) recent severe community reports -- so the map's
    choropleth colouring (and a sortable "most at risk now" list) reflects
    more than just the static ``current_risk_level`` field, which only
    updates on the hourly ``update_flood_risk_zones`` Celery beat task.
    """
    from apps.alerts.models import CommunityReport, FloodEvent
    from apps.satellite.models import FloodZone

    since_recent = timezone.now() - timedelta(hours=6)
    scores = []

    for zone in FloodZone.objects.all():
        # (a) Sensor proximity to threshold -- average ratio across the
        # zone's online stations with a recent reading.
        sensor_component = 0.0
        station_count = 0
        for station in zone.stations.filter(status="online"):
            reading = station.latest_reading()
            if reading and zone.water_level_threshold_cm:
                ratio = reading.water_level_cm / zone.water_level_threshold_cm
                sensor_component += min(ratio, 2.0)
                station_count += 1
        sensor_component = (sensor_component / station_count) if station_count else 0.0

        # (b) Active flood event severity adds a flat bump.
        active_event = FloodEvent.objects.filter(flood_zone=zone, ended_at__isnull=True).first()
        event_bump = {"yellow": 15, "orange": 30, "red": 50}.get(
            active_event.severity if active_event else None, 0
        )

        # (c) Recent severe community reports add a smaller bump.
        severe_reports = CommunityReport.objects.filter(
            flood_zone=zone, severity="severe", created_at__gte=since_recent
        ).count()
        report_bump = min(severe_reports * 10, 20)

        score = min(round(sensor_component * 30 + event_bump + report_bump), 100)
        scores.append({
            "zone_id": zone.id, "zone_name": zone.name, "risk_score": score,
            "current_risk_level": zone.current_risk_level,
            "active_event": active_event.severity if active_event else None,
            "station_count": station_count,
        })

    scores.sort(key=lambda s: s["risk_score"], reverse=True)
    return Response({"zones": scores})
