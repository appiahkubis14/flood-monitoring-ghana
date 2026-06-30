#!/usr/bin/env python3
"""
Comprehensive demo/test seed data for FloodWatch Ghana.

Creates ~10 realistic records across every model in the system -- not just
the 3 flood zones + 3 stations from ``init_database.py``, but a full
working dataset: users, alert recipients, sensor stations with dense
24h-of-readings history (so every dashboard chart has real data to show),
flood events at every severity level, alerts across every delivery status,
satellite scenes + flood maps, community reports (verified and not), and
historical flood records spanning several past years.

This is explicitly **test/demo data** -- phone numbers are obviously fake
(+233200000XXX range), satellite scene IDs are synthetic, and historical
casualty/displacement numbers are illustrative, not sourced from any real
event. Safe to run against a fresh database; NOT safe to run twice without
clearing first (it does not use get_or_create -- re-running creates
duplicate rows, unlike the idempotent ``init_database.py``).

Usage:
    docker compose exec web python scripts/seed_demo_data.py
    docker compose exec web python scripts/seed_demo_data.py --clear   # wipe demo data first
"""
from __future__ import annotations

import os
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "floodwatch.settings.development")

import django  # noqa: E402

django.setup()

from django.contrib.gis.geos import MultiPolygon, Point, Polygon  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.alerts.models import (  # noqa: E402
    Alert,
    AlertChannel,
    AlertDeliveryStatus,
    AlertRecipient,
    CommunityReport,
    FloodEvent,
    HistoricalFloodRecord,
)
from apps.core.models import SeverityLevel  # noqa: E402
from apps.satellite.models import (  # noqa: E402
    FloodMap,
    FloodZone,
    SatelliteScene,
    SatelliteSource,
    SceneStatus,
)
from apps.sensors.models import SensorReading, SensorStation, StationStatus  # noqa: E402
from apps.users.models import User, UserRole  # noqa: E402

random.seed(42)  # reproducible demo data across runs

# ── Reference geography: small polygons across real Accra communities ────────
ZONE_DEFINITIONS = [
    ("Odaw River Basin — Alajo",        -0.2250, 5.5950, -0.2050, 5.6150, 45.0, 35.0, 38000),
    ("Korle Lagoon — Agbogbloshie",     -0.2200, 5.5400, -0.2000, 5.5600, 50.0, 40.0, 52000),
    ("Odaw River Basin — Avenor/Kaneshie", -0.2400, 5.5650, -0.2200, 5.5850, 40.0, 30.0, 29000),
    ("Nima-Kotobabi Drain",             -0.1950, 5.5850, -0.1750, 5.6050, 42.0, 32.0, 41000),
    ("Adabraka Low-Lying Belt",         -0.2150, 5.5550, -0.1950, 5.5750, 38.0, 28.0, 22000),
    ("Tema Station Catchment",          -0.2050, 5.5450, -0.1850, 5.5650, 48.0, 38.0, 31000),
    ("Sabon Zongo Floodplain",          -0.2350, 5.5500, -0.2150, 5.5700, 44.0, 34.0, 26000),
    ("North Industrial Area",           -0.2300, 5.5950, -0.2100, 5.6150, 36.0, 26.0, 15000),
    ("Lavender Hill Outlet",            -0.2150, 5.5250, -0.1950, 5.5450, 55.0, 42.0, 19000),
    ("Abossey Okai Junction",           -0.2280, 5.5550, -0.2080, 5.5750, 41.0, 31.0, 24000),
]

COMMUNITIES = [
    "Alajo", "Agbogbloshie", "Kaneshie", "Nima", "Adabraka",
    "Tema Station", "Sabon Zongo", "North Industrial", "Lavender Hill", "Abossey Okai",
]

SEVERITIES = [SeverityLevel.GREEN, SeverityLevel.YELLOW, SeverityLevel.ORANGE, SeverityLevel.RED]
TRIGGER_SOURCES = ["sensor", "satellite", "combined", "community", "manual"]
ALERT_CHANNELS = [AlertChannel.WHATSAPP, AlertChannel.SMS, AlertChannel.EMAIL, AlertChannel.DASHBOARD]
DELIVERY_STATUSES = [
    AlertDeliveryStatus.DELIVERED, AlertDeliveryStatus.SENT,
    AlertDeliveryStatus.FAILED, AlertDeliveryStatus.SUPPRESSED, AlertDeliveryStatus.PENDING,
]


def clear_demo_data() -> None:
    print("Clearing existing demo data...")
    Alert.objects.all().delete()
    CommunityReport.objects.all().delete()
    FloodEvent.objects.all().delete()
    HistoricalFloodRecord.objects.all().delete()
    AlertRecipient.objects.all().delete()
    FloodMap.objects.all().delete()
    SatelliteScene.objects.all().delete()
    SensorReading.objects.all().delete()
    SensorStation.objects.all().delete()
    FloodZone.objects.all().delete()
    User.objects.filter(is_superuser=False).delete()
    print("  Done.\n")


def seed_flood_zones() -> list[FloodZone]:
    zones = []
    for name, minlon, minlat, maxlon, maxlat, water_t, rain_t, pop in ZONE_DEFINITIONS:
        poly = Polygon((
            (minlon, minlat), (maxlon, minlat), (maxlon, maxlat), (minlon, maxlat), (minlon, minlat),
        ), srid=4326)
        zone = FloodZone.objects.create(
            name=name, geometry=poly,
            description=f"Flood risk zone covering the {name.split('—')[-1].strip()} catchment.",
            current_risk_level=random.choice(SEVERITIES),
            water_level_threshold_cm=water_t, rainfall_threshold_mm=rain_t,
            population_estimate=pop,
            last_assessed_at=timezone.now() - timedelta(hours=random.randint(0, 12)),
        )
        zones.append(zone)
        print(f"  FloodZone: {zone.name} [{zone.current_risk_level}]")
    return zones


def seed_users() -> list[User]:
    users = []
    roles = [UserRole.ADMIN, UserRole.FIELD_OFFICER] + [UserRole.COMMUNITY] * 8
    first_names = ["Ama", "Kwame", "Akosua", "Kofi", "Abena", "Yaw", "Efua", "Kwabena", "Adwoa", "Kojo"]
    last_names = ["Owusu", "Asante", "Mensah", "Boateng", "Agyemang", "Darko", "Appiah", "Osei", "Adjei", "Sarpong"]

    for i in range(10):
        username = f"{first_names[i].lower()}.{last_names[i].lower()}{i}"
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="demo-password-not-for-production",
            first_name=first_names[i], last_name=last_names[i],
            role=roles[i],
            phone_number=f"+233200000{100+i}",
            preferred_language=random.choice(["en", "tw"]),
            receives_whatsapp_alerts=True,
            receives_sms_alerts=random.choice([True, False]),
            organization="NADMO" if roles[i] == UserRole.FIELD_OFFICER else "",
        )
        users.append(user)
        print(f"  User: {user.username} [{user.role}]")
    return users


def seed_sensor_stations(zones: list[FloodZone]) -> list[SensorStation]:
    stations = []
    for i in range(10):
        zone = zones[i % len(zones)]
        # Place the station roughly inside its assigned zone's bbox.
        bbox = zone.geometry.extent  # (minx, miny, maxx, maxy)
        lon = random.uniform(bbox[0] + 0.005, bbox[2] - 0.005)
        lat = random.uniform(bbox[1] + 0.005, bbox[3] - 0.005)

        status = random.choices(
            [StationStatus.ONLINE, StationStatus.OFFLINE, StationStatus.MAINTENANCE, StationStatus.FAULTY],
            weights=[6, 2, 1, 1],
        )[0]
        station = SensorStation.objects.create(
            name=f"{COMMUNITIES[i]} Gauge {i+1:02d}",
            location=Point(lon, lat, srid=4326),
            community=COMMUNITIES[i],
            status=status,
            battery_level=round(random.uniform(15.0, 100.0), 1),
            serial_number=f"ESP32-{COMMUNITIES[i][:3].upper()}-{i+1:03d}",
            flood_zone=zone,
            last_reading_at=timezone.now() - timedelta(minutes=random.randint(1, 90))
                if status == StationStatus.ONLINE else timezone.now() - timedelta(hours=random.randint(6, 48)),
        )
        stations.append(station)
        print(f"  SensorStation: {station.name} [{station.status}] battery={station.battery_level}%")
    return stations


def seed_sensor_readings(stations: list[SensorStation]) -> int:
    """Dense 48h history per station, one reading every 30 minutes (96
    readings/station) -- enough for every trend chart on the dashboard to
    show a real, varying curve rather than 2-3 flat data points.
    """
    count = 0
    now = timezone.now()
    for station in stations:
        # Each station gets its own baseline + a touch of "weather" so
        # the dashboard-wide aggregate trend looks like a real storm
        # passing through rather than uniform noise across every station.
        baseline_water = random.uniform(10, 35)
        storm_peak_offset = random.randint(0, 95)  # which reading index gets the peak

        for j in range(96):  # 96 * 30min = 48h of history
            ts = now - timedelta(minutes=30 * (95 - j))
            # Gaussian-ish bump around storm_peak_offset to simulate a rain event
            distance = abs(j - storm_peak_offset)
            storm_factor = max(0, 1 - distance / 20.0)
            water_level = baseline_water + storm_factor * random.uniform(20, 60)
            rainfall = storm_factor * random.uniform(0, 25) + random.uniform(0, 2)

            SensorReading.objects.create(
                station=station,
                water_level_cm=round(water_level, 1),
                rainfall_mm=round(rainfall, 1),
                temperature_c=round(random.uniform(24, 32), 1),
                battery_voltage=round(random.uniform(3.5, 4.2), 2),
                signal_strength=random.randint(-90, -50),
                timestamp=ts,
                is_verified=True,
            )
            count += 1
    print(f"  SensorReading: {count} readings across {len(stations)} stations (48h history each)")
    return count


def seed_satellite_scenes() -> list[SatelliteScene]:
    scenes = []
    sources = [SatelliteSource.SENTINEL2] * 7 + [SatelliteSource.SENTINEL1] * 3
    statuses = [SceneStatus.PROCESSED] * 6 + [SceneStatus.DOWNLOADED, SceneStatus.PROCESSING,
                                                SceneStatus.DISCOVERED, SceneStatus.FAILED]
    for i in range(10):
        acq_date = timezone.now() - timedelta(days=random.randint(0, 30))
        scene = SatelliteScene.objects.create(
            scene_id=f"DEMO_{sources[i]}_{acq_date.strftime('%Y%m%dT%H%M%S')}_{i:03d}",
            source=sources[i],
            provider="planetary_computer",
            acquisition_date=acq_date,
            cloud_cover_pct=round(random.uniform(0, 35), 1) if sources[i] == SatelliteSource.SENTINEL2 else None,
            status=statuses[i],
            error_message="Download timeout after 3 retries" if statuses[i] == SceneStatus.FAILED else "",
            metadata={"demo": True, "platform": sources[i]},
        )
        scenes.append(scene)
        print(f"  SatelliteScene: {scene.scene_id} [{scene.status}]")
    return scenes


def seed_flood_maps(zones: list[FloodZone], scenes: list[SatelliteScene]) -> list[FloodMap]:
    flood_maps = []
    s2_scenes = [s for s in scenes if s.source == SatelliteSource.SENTINEL2]
    for i in range(10):
        zone = zones[i % len(zones)]
        bbox = zone.geometry.extent
        # Small flooded patch within the zone's bbox.
        pad = 0.01
        flood_poly = Polygon((
            (bbox[0]+pad, bbox[1]+pad), (bbox[0]+pad*3, bbox[1]+pad),
            (bbox[0]+pad*3, bbox[1]+pad*3), (bbox[0]+pad, bbox[1]+pad*3), (bbox[0]+pad, bbox[1]+pad),
        ), srid=4326)
        # NOTE: MultiPolygon([poly]) does NOT inherit the SRID from its
        # child polygon -- it comes back srid=None, which PostGIS rejects
        # for a field declared srid=4326. Must be set explicitly here.
        extent_geom = MultiPolygon([flood_poly])
        extent_geom.srid = 4326
        flood_map = FloodMap.objects.create(
            source_scene=s2_scenes[i % len(s2_scenes)] if s2_scenes else None,
            flood_zone=zone,
            extent_geometry=extent_geom,
            raster_path=f"media/satellite/preprocessed/demo_flood_mask_{i:02d}.tif",
            flooded_area_ha=round(random.uniform(2.0, 80.0), 1),
            confidence=round(random.uniform(0.4, 0.97), 2),
            confirmed_by_sensors=random.choice([True, False]),
            detection_method=random.choice(["mndwi_threshold", "changeformer", "sar_backscatter"]),
            statistics={"mndwi_mean": round(random.uniform(0.1, 0.4), 3), "demo": True},
        )
        flood_maps.append(flood_map)
        print(f"  FloodMap: {flood_map.flood_zone.name} {flood_map.flooded_area_ha}ha "
              f"conf={flood_map.confidence}")
    return flood_maps


def seed_flood_events(zones: list[FloodZone], flood_maps: list[FloodMap]) -> list[FloodEvent]:
    events = []
    for i in range(10):
        zone = zones[i % len(zones)]
        started = timezone.now() - timedelta(days=random.randint(0, 60), hours=random.randint(0, 23))
        # Make ~3 of the 10 still "active" (no ended_at) so active-event
        # KPI cards and the status banner have something to show.
        ended = None if i < 3 else started + timedelta(hours=random.randint(2, 48))
        event = FloodEvent.objects.create(
            flood_zone=zone,
            severity=random.choice(SEVERITIES[1:]),  # never GREEN for an actual event
            triggered_by=random.choice(TRIGGER_SOURCES),
            started_at=started,
            ended_at=ended,
            affected_area_ha=round(random.uniform(5.0, 90.0), 1),
            peak_water_level_cm=round(random.uniform(35.0, 95.0), 1),
            description=f"Flood event in {zone.name}, triggered by {random.choice(TRIGGER_SOURCES)} detection.",
            related_flood_map=flood_maps[i] if i < len(flood_maps) else None,
        )
        events.append(event)
        status = "ACTIVE" if event.is_active else "resolved"
        print(f"  FloodEvent: {zone.name} [{event.severity}] {status}")
    return events


def seed_alert_recipients(zones: list[FloodZone], users: list[User]) -> list[AlertRecipient]:
    recipients = []
    for i in range(10):
        # First 5 are linked to a registered User; last 5 are phone-only
        # community subscribers (the public self-service subscribe flow).
        user = users[i] if i < 5 and i < len(users) else None
        recipient = AlertRecipient.objects.create(
            user=user,
            full_name=user.get_full_name() if user else f"Community Member {i+1}",
            phone_number=f"+233200001{100+i}",
            preferred_channel=random.choice([AlertChannel.WHATSAPP, AlertChannel.SMS, AlertChannel.DASHBOARD]),
            min_severity=random.choice(SEVERITIES),
            is_active=random.choice([True, True, True, False]),  # mostly active
        )
        # Subscribe to 1-3 random zones (empty = all zones, so leave ~2 empty).
        if i % 4 != 0:
            recipient.flood_zones.set(random.sample(zones, k=random.randint(1, 3)))
        recipients.append(recipient)
        print(f"  AlertRecipient: {recipient.full_name} [{recipient.preferred_channel}]")
    return recipients


def seed_alerts(events: list[FloodEvent], recipients: list[AlertRecipient]) -> int:
    count = 0
    for i in range(10):
        event = events[i % len(events)]
        recipient = recipients[i % len(recipients)]
        delivery_status = random.choice(DELIVERY_STATUSES)
        created = timezone.now() - timedelta(hours=random.randint(0, 72))
        sent_at = created + timedelta(seconds=random.randint(1, 30)) \
            if delivery_status in (AlertDeliveryStatus.SENT, AlertDeliveryStatus.DELIVERED) else None
        delivered_at = sent_at + timedelta(seconds=random.randint(5, 120)) \
            if delivery_status == AlertDeliveryStatus.DELIVERED and sent_at else None

        alert = Alert.objects.create(
            flood_event=event, recipient=recipient, severity=event.severity,
            channel=recipient.preferred_channel,
            message=f"[FloodWatch Ghana — {event.get_severity_display().upper()}] "
                    f"Flooding detected in {event.flood_zone.name}. Stay alert and avoid the area.",
            delivery_status=delivery_status,
            provider_message_id=f"DEMO_SID_{i:04d}" if delivery_status != AlertDeliveryStatus.PENDING else "",
            sent_at=sent_at, delivered_at=delivered_at,
            error_message="Invalid phone number format" if delivery_status == AlertDeliveryStatus.FAILED else "",
        )
        # created_at has auto_now_add=True, so backdate via a second save
        # the way real historical data ends up backdated -- update() bypasses
        # auto_now_add on the existing row.
        Alert.objects.filter(pk=alert.pk).update(created_at=created)
        count += 1
        print(f"  Alert: {recipient} via {alert.channel} [{alert.delivery_status}]")
    return count


def seed_community_reports(zones: list[FloodZone], users: list[User]) -> list[CommunityReport]:
    reports = []
    descriptions = [
        "Water rising fast near the market, ankle deep on the main road.",
        "Drain completely blocked with debris, water backing up into compound.",
        "Knee-deep water blocking the bridge, motorbikes unable to pass.",
        "Flooding has reached the school compound wall.",
        "Severe flooding — water entering ground-floor shops, residents evacuating.",
        "Minor pooling after the rain, should clear within the hour.",
        "Gutter overflow near the taxi rank, pedestrians wading through.",
        "Waist-deep water on the access road, vehicles stranded.",
        "Localised flooding near the lagoon outlet, fishing boats affected.",
        "Water level dropping now compared to this morning.",
    ]
    for i in range(10):
        zone = zones[i % len(zones)]
        bbox = zone.geometry.extent
        lon = random.uniform(bbox[0] + 0.005, bbox[2] - 0.005)
        lat = random.uniform(bbox[1] + 0.005, bbox[3] - 0.005)
        severity = random.choice(["minor", "moderate", "moderate", "severe"])
        is_verified = i % 3 == 0
        reporter = users[i] if i < len(users) and i % 2 == 0 else None

        report = CommunityReport.objects.create(
            reporter=reporter,
            reporter_phone="" if reporter else f"+233200002{100+i}",
            location=Point(lon, lat, srid=4326),
            flood_zone=zone,
            severity=severity,
            description=descriptions[i],
            is_verified=is_verified,
            verified_by=users[0] if is_verified and users else None,
            verified_at=timezone.now() - timedelta(hours=random.randint(1, 24)) if is_verified else None,
        )
        reports.append(report)
        print(f"  CommunityReport: {zone.name} [{severity}] verified={is_verified}")
    return reports


def seed_historical_records(zones: list[FloodZone]) -> int:
    """Spans several past years so the historical trend chart on
    /dashboard/flood-maps/timeseries/ has a real multi-year curve.
    """
    count = 0
    sources = ["NADMO Report", "GhanaWeb Archive", "Daily Graphic", "Field Survey", "Community Records"]
    for i in range(10):
        zone = zones[i % len(zones)]
        year = 2024 - (i % 6)  # spread across 2019-2024
        event_date = date(year, random.randint(5, 10), random.randint(1, 28))  # rainy season months
        severity = random.choice(SEVERITIES[1:])
        record = HistoricalFloodRecord.objects.create(
            flood_zone=zone,
            event_date=event_date,
            severity=severity,
            rainfall_mm=round(random.uniform(30, 150), 1),
            affected_area_ha=round(random.uniform(10, 200), 1),
            casualties=random.choices([0, 0, 0, 1, 2, 5], weights=[40, 20, 15, 10, 10, 5])[0],
            displaced_persons=random.randint(0, 500),
            source=f"{random.choice(sources)} {year}",
            notes=f"Historical flood record for {zone.name}, {event_date.strftime('%B %Y')}.",
        )
        count += 1
        print(f"  HistoricalFloodRecord: {zone.name} {event_date} [{severity}] "
              f"casualties={record.casualties}")
    return count


def run(clear_first: bool = False) -> None:
    print("=" * 64)
    print("FloodWatch Ghana — Comprehensive Demo Seed Data")
    print("=" * 64)

    if clear_first:
        clear_demo_data()

    print("\n[1/10] Flood Zones")
    zones = seed_flood_zones()

    print("\n[2/10] Users")
    users = seed_users()

    print("\n[3/10] Sensor Stations")
    stations = seed_sensor_stations(zones)

    print("\n[4/10] Sensor Readings (dense 48h history)")
    seed_sensor_readings(stations)

    print("\n[5/10] Satellite Scenes")
    scenes = seed_satellite_scenes()

    print("\n[6/10] Flood Maps")
    flood_maps = seed_flood_maps(zones, scenes)

    print("\n[7/10] Flood Events")
    events = seed_flood_events(zones, flood_maps)

    print("\n[8/10] Alert Recipients")
    recipients = seed_alert_recipients(zones, users)

    print("\n[9/10] Alerts")
    seed_alerts(events, recipients)

    print("\n[10/10] Community Reports")
    seed_community_reports(zones, users)

    print("\n[Bonus] Historical Flood Records")
    seed_historical_records(zones)

    print("\n" + "=" * 64)
    print("Seed complete:")
    print(f"  {len(zones)} flood zones, {len(users)} users, {len(stations)} sensor stations")
    print(f"  {SensorReading.objects.count()} sensor readings")
    print(f"  {len(scenes)} satellite scenes, {len(flood_maps)} flood maps")
    print(f"  {len(events)} flood events, {len(recipients)} alert recipients")
    print(f"  {Alert.objects.count()} alerts, {CommunityReport.objects.count()} community reports")
    print(f"  {HistoricalFloodRecord.objects.count()} historical records")
    print("=" * 64)
    print("\nVisit /dashboard/ to see all charts populated with this data.")
    print("Demo user login: any seeded username (e.g. 'ama.owusu0') / demo-password-not-for-production")


if __name__ == "__main__":
    run(clear_first="--clear" in sys.argv)
