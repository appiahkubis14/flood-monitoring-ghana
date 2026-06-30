"""
PyGeoVision satellite processing pipeline for FloodWatch Ghana.

This is the production implementation of the conceptual workflow in the
project brief: search -> download -> prepare_for_ai -> detect -> store ->
alert. Every step records its outcome on a :class:`SatelliteScene` or
:class:`FloodMap` row, and every external call (PyGeoVision search/download,
rasterio reads) is wrapped so a single scene's failure can't abort the
whole monitoring cycle.

PyGeoVision API used here (search/download/prepare_for_ai/indices) matches
the ``pygeovision>=2.0`` client surface; see ``requirements.txt`` for the
pinned version.
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.utils import timezone

from apps.satellite.indices import (
    compute_confidence,
    compute_mndwi,
    flood_mask_from_mndwi,
    pixel_area_ha,
    vectorise_flood_mask,
)
from apps.satellite.models import (
    FloodMap,
    FloodZone,
    SatelliteScene,
    SatelliteSource,
    SceneStatus,
)

logger = logging.getLogger("apps.satellite")


class SatelliteProcessingError(Exception):
    """Raised for unrecoverable errors in a single scene's processing --
    caught at the per-scene level in ``run_monitoring_cycle`` so one bad
    scene doesn't stop the others from being processed.
    """


class SatelliteProcessor:
    """Orchestrates PyGeoVision search/download/preprocess/detect for the
    Accra study area, persisting results into the Django models.

    Example::

        processor = SatelliteProcessor()
        summary = processor.run_monitoring_cycle()
    """

    def __init__(self) -> None:
        from pygeovision import PyGeoVision

        self.client = PyGeoVision()
        self.bbox = settings.ACCRA_BBOX
        self.data_dir = Path(settings.PYGEOVISION_DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.s2_bands = settings.PYGEOVISION_S2_BANDS
        self.providers = settings.PYGEOVISION_PROVIDERS
        self.cloud_cover_max = settings.PYGEOVISION_CLOUD_COVER_MAX

    # ── Top-level entry point ─────────────────────────────────────────────

    def run_monitoring_cycle(self) -> dict[str, Any]:
        """Full cycle: discover new scenes, process any not yet processed,
        run flood detection, and return a summary dict for logging /
        Celery task results.
        """
        discovered = self.sync_scenes()
        processed = self.process_pending_scenes()
        return {
            "discovered": discovered,
            "processed": processed,
            "ran_at": timezone.now().isoformat(),
        }

    # ── Step 1: discover scenes ───────────────────────────────────────────

    def sync_scenes(self) -> dict[str, int]:
        """Search both Sentinel-1 (SAR) and Sentinel-2 (optical) for the
        Accra bbox over the configured lookback window, and upsert each
        result into :class:`SatelliteScene` (idempotent via ``scene_id``).
        """
        date_range = (
            (datetime.now() - timedelta(days=settings.PYGEOVISION_SCAN_DAYS_BACK)).strftime("%Y-%m-%d"),
            datetime.now().strftime("%Y-%m-%d"),
        )

        new_counts = {"sentinel-2": 0, "sentinel-1": 0}

        for source, satellites in [
            (SatelliteSource.SENTINEL2, None),
            (SatelliteSource.SENTINEL1, ["Sentinel-1"]),
        ]:
            try:
                kwargs = dict(
                    bbox=self.bbox, date_range=date_range, providers=self.providers,
                    cloud_cover_max=self.cloud_cover_max if source == SatelliteSource.SENTINEL2 else 100,
                )
                if satellites:
                    kwargs["satellites"] = satellites
                results = self.client.search(**kwargs)
            except Exception:
                logger.exception("Satellite search failed for source=%s", source)
                continue

            for result in results:
                _, created = SatelliteScene.objects.get_or_create(
                    scene_id=result.id,
                    defaults=dict(
                        source=source,
                        provider=getattr(result, "provider", self.providers[0]),
                        acquisition_date=getattr(result, "datetime", timezone.now()),
                        cloud_cover_pct=getattr(result, "cloud_cover", None),
                        metadata=getattr(result, "properties", {}) or {},
                    ),
                )
                if created:
                    new_counts[source] += 1

        logger.info("sync_scenes: discovered %s new Sentinel-2, %s new Sentinel-1",
                    new_counts["sentinel-2"], new_counts["sentinel-1"])
        return new_counts

    # ── Step 2: process pending scenes ────────────────────────────────────

    def process_pending_scenes(self, limit: int = 10) -> dict[str, int]:
        """Download + preprocess + detect for every scene still in
        ``DISCOVERED`` status, up to ``limit`` per call (keeps a single
        Celery task run bounded rather than potentially processing an
        unbounded backlog in one go).
        """
        pending = SatelliteScene.objects.filter(status=SceneStatus.DISCOVERED).order_by(
            "-acquisition_date"
        )[:limit]

        succeeded, failed = 0, 0
        for scene in pending:
            try:
                self._process_scene(scene)
                succeeded += 1
            except SatelliteProcessingError as exc:
                logger.error("Scene %s processing failed: %s", scene.scene_id, exc)
                scene.status = SceneStatus.FAILED
                scene.error_message = str(exc)
                scene.save(update_fields=["status", "error_message"])
                failed += 1
            except Exception:  # noqa: BLE001 -- one bad scene must not stop the batch
                logger.exception("Unexpected error processing scene %s", scene.scene_id)
                scene.status = SceneStatus.FAILED
                scene.error_message = traceback.format_exc()[-2000:]
                scene.save(update_fields=["status", "error_message"])
                failed += 1

        return {"succeeded": succeeded, "failed": failed}

    def _process_scene(self, scene: SatelliteScene) -> None:
        scene.status = SceneStatus.DOWNLOADING
        scene.save(update_fields=["status"])

        raw_dir = self.data_dir / "raw" / scene.scene_id
        raw_dir.mkdir(parents=True, exist_ok=True)

        try:
            download_results = self.client.download(
                [self._scene_id_to_search_result(scene)],
                output_dir=str(raw_dir),
                bands=self.s2_bands if scene.source == SatelliteSource.SENTINEL2 else None,
                post_process=["reproject:EPSG:32630", "cog"],  # UTM 30N covers Accra
            )
        except Exception as exc:
            raise SatelliteProcessingError(f"Download failed: {exc}") from exc

        if not download_results or not download_results[0].success:
            raise SatelliteProcessingError("Download returned no successful result")

        raw_path = download_results[0].path
        scene.raw_path = str(raw_path)
        scene.status = SceneStatus.DOWNLOADED
        scene.save(update_fields=["raw_path", "status"])

        if scene.source != SatelliteSource.SENTINEL2:
            # SAR flood detection lands in a future iteration (backscatter
            # threshold proxy); for now we store the download and stop --
            # this still gives the dashboard a SAR browse image / metadata.
            scene.status = SceneStatus.PROCESSED
            scene.save(update_fields=["status"])
            return

        scene.status = SceneStatus.PROCESSING
        scene.save(update_fields=["status"])

        preprocessed_path = self.data_dir / "preprocessed" / f"{scene.scene_id}.tif"
        preprocessed_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            scl_path = self._find_scl_path(raw_path)
            result = self.client.prepare_for_ai(
                str(raw_path),
                stack_bands=self.s2_bands,
                bbox=self.bbox,
                scl_path=str(scl_path) if scl_path else None,
                scl_keep_classes=[4, 5, 6],
                normalise="scale_factor",
                scale_factor=10000.0,
                model_type="change_detection",
                output_path=str(preprocessed_path),
            )
        except Exception as exc:
            raise SatelliteProcessingError(f"prepare_for_ai failed: {exc}") from exc

        scene.preprocessed_path = str(preprocessed_path)
        scene.status = SceneStatus.PROCESSED
        scene.save(update_fields=["preprocessed_path", "status"])

        self._detect_floods(scene, result["array"], preprocessed_path)

    def _scene_id_to_search_result(self, scene: SatelliteScene):
        """PyGeoVision's ``download()`` expects SearchResult objects from
        ``search()``, not bare scene_id strings -- re-search for this
        specific scene_id to get a fresh, download-ready result object
        (STAC asset URLs can be time-limited, so re-fetching at download
        time rather than caching the original result is the safer choice).
        """
        results = self.client.search(
            bbox=self.bbox,
            date_range=(scene.acquisition_date.strftime("%Y-%m-%d"), scene.acquisition_date.strftime("%Y-%m-%d")),
            providers=[scene.provider],
        )
        for r in results:
            if r.id == scene.scene_id:
                return r
        raise SatelliteProcessingError(f"Could not re-locate scene {scene.scene_id} for download")

    def _find_scl_path(self, raw_path) -> Optional[Path]:
        """Sentinel-2 L2A scenes include a Scene Classification Layer (SCL)
        band for cloud masking -- find it alongside the downloaded bands if
        present. Cloud masking is skipped (not an error) when absent.
        """
        raw_path = Path(raw_path)
        candidates = list(raw_path.parent.rglob("*SCL*.tif"))
        return candidates[0] if candidates else None

    # ── Step 3: flood detection ────────────────────────────────────────────

    def _detect_floods(self, scene: SatelliteScene, stack, preprocessed_path: Path) -> None:
        """MNDWI-threshold flood detection on one preprocessed scene,
        per-zone: for every FloodZone, clip the stack to that zone's
        geometry conceptually (here: evaluate the whole-scene mask, then
        attribute area per zone via the stored zone geometry) and create a
        FloodMap row if any flooding is detected.
        """
        import numpy as np
        import rasterio

        mndwi = compute_mndwi(stack)
        mask = flood_mask_from_mndwi(stack)
        confidence = compute_confidence(mndwi, mask)

        if mask.sum() == 0:
            logger.info("Scene %s: no flooding detected (MNDWI threshold)", scene.scene_id)
            return

        mask_path = preprocessed_path.parent / f"{scene.scene_id}_flood_mask.tif"
        with rasterio.open(str(preprocessed_path)) as src:
            profile = src.profile.copy()
            transform = src.transform
            raster_crs = src.crs
        profile.update(count=1, dtype="uint8", compress="lzw")
        with rasterio.open(str(mask_path), "w", **profile) as dst:
            dst.write(mask[None, ...])

        total_area_ha = pixel_area_ha(transform, mask)
        # geojson (from vectorise_flood_mask) is always WGS84 -- correct
        # CRS for the GEOSGeometry stored on FloodMap.extent_geometry.
        geojson = vectorise_flood_mask(str(mask_path))
        extent_geom = GEOSGeometry(str(geojson).replace("'", '"'), srid=4326) if geojson else None

        for zone in FloodZone.objects.all():
            zone_area_ha = self._zone_flood_area_ha(zone, mask, transform, raster_crs)
            if zone_area_ha <= 0:
                continue

            confirmed = self._check_sensor_confirmation(zone)

            flood_map = FloodMap.objects.create(
                source_scene=scene,
                flood_zone=zone,
                extent_geometry=extent_geom,
                raster_path=str(mask_path),
                flooded_area_ha=zone_area_ha,
                confidence=confidence,
                confirmed_by_sensors=confirmed,
                detection_method="mndwi_threshold",
                statistics={
                    "mndwi_mean": float(np.nanmean(mndwi)),
                    "mndwi_max": float(np.nanmax(mndwi)),
                    "total_scene_area_ha": total_area_ha,
                },
            )
            logger.info(
                "FloodMap created: zone=%s area=%.1fha confidence=%.2f confirmed=%s",
                zone.name, zone_area_ha, confidence, confirmed,
            )
            self._maybe_raise_flood_event(zone, flood_map, confirmed)

    def _zone_flood_area_ha(self, zone: FloodZone, mask, transform, raster_crs) -> float:
        """Flooded area within one zone, computed entirely in raster space
        to avoid any vector CRS mismatch: reproject the zone's WGS84
        polygon into the mask raster's CRS, rasterise it to a boolean
        zone-mask of the same shape, and count pixels where *both* masks
        are true. Pixel area then comes directly from the raster's own
        (typically metric, UTM) transform -- no degree/metre conversion
        approximation involved anywhere in this calculation.
        """
        import numpy as np
        from rasterio.features import geometry_mask
        from rasterio.warp import transform_geom
        import json as _json

        try:
            zone_geom_native = transform_geom(
                "EPSG:4326", raster_crs, _json.loads(zone.geometry.geojson)
            )
        except Exception:
            logger.exception("Failed to reproject zone %s geometry for area calc", zone.name)
            return 0.0

        zone_mask = ~geometry_mask(
            [zone_geom_native], out_shape=mask.shape, transform=transform, invert=False
        )
        overlap = mask.astype(bool) & zone_mask
        return pixel_area_ha(transform, overlap)

    def _check_sensor_confirmation(self, zone: FloodZone) -> bool:
        """True if any station in this zone has a recent reading above its
        own threshold -- this is the IoT-confirmation half of the
        "Combined IoT + satellite confirmation" alert trigger.
        """
        from apps.alerts.rules import AlertRules

        rules = AlertRules()
        recent_cutoff = timezone.now() - timedelta(hours=6)
        for station in zone.stations.filter(last_reading_at__gte=recent_cutoff):
            reading = station.latest_reading()
            if reading is None:
                continue
            result = rules.evaluate_water_level(reading.water_level_cm, zone)
            if result.triggered:
                return True
        return False

    def _maybe_raise_flood_event(self, zone: FloodZone, flood_map: FloodMap, sensor_confirmed: bool) -> None:
        from apps.alerts.models import FloodEvent
        from apps.alerts.rules import AlertRules, SeverityLevel, severity_rank
        from apps.alerts.tasks import create_and_send_alerts

        rules = AlertRules()
        sat_result = rules.evaluate_satellite(flood_map.flooded_area_ha, flood_map.confidence, zone)
        if not sat_result.triggered:
            return

        severity = sat_result.severity
        triggered_by = "satellite"
        if sensor_confirmed:
            # Escalate by one level when satellite + sensor both confirm,
            # capped at RED -- same "combined" escalation rule as
            # AlertRules.combine() applies for the sensor-threshold path.
            ordered_levels = list(SeverityLevel)
            current_rank = severity_rank(severity)
            severity = ordered_levels[min(current_rank + 1, len(ordered_levels) - 1)]
            triggered_by = "combined"

        event = FloodEvent.objects.filter(flood_zone=zone, ended_at__isnull=True).first()
        if event is None:
            event = FloodEvent.objects.create(
                flood_zone=zone, severity=severity, triggered_by=triggered_by,
                started_at=timezone.now(), affected_area_ha=flood_map.flooded_area_ha,
                affected_area_geometry=flood_map.extent_geometry, related_flood_map=flood_map,
            )
            create_and_send_alerts.delay(event.id)
        elif severity_rank(severity) > severity_rank(event.severity):
            event.severity = severity
            event.triggered_by = triggered_by
            event.affected_area_ha = flood_map.flooded_area_ha
            event.related_flood_map = flood_map
            event.save(update_fields=["severity", "triggered_by", "affected_area_ha", "related_flood_map"])
            create_and_send_alerts.delay(event.id)

    # ── Risk zone recalculation ────────────────────────────────────────────

    def update_flood_risk_zones(self) -> dict[str, int]:
        """Recompute each FloodZone's ``current_risk_level`` from its most
        recent FloodMap + any active FloodEvent -- run hourly via Celery
        beat so the dashboard's zone colour-coding stays current even
        between full monitoring cycles.
        """
        from apps.alerts.models import FloodEvent

        updated = 0
        for zone in FloodZone.objects.all():
            active_event = FloodEvent.objects.filter(flood_zone=zone, ended_at__isnull=True).first()
            new_level = active_event.severity if active_event else "green"
            if new_level != zone.current_risk_level:
                zone.current_risk_level = new_level
                zone.last_assessed_at = timezone.now()
                zone.save(update_fields=["current_risk_level", "last_assessed_at"])
                updated += 1
            else:
                zone.last_assessed_at = timezone.now()
                zone.save(update_fields=["last_assessed_at"])
        return {"zones_updated": updated}
