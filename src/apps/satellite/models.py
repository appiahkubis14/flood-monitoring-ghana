"""
Satellite intelligence models: scene metadata, generated flood maps, and the
predefined flood risk zones used by both the satellite pipeline and the
sensor network.

These models store *metadata and derived statistics*, not raster pixels --
the actual GeoTIFFs produced by PyGeoVision live on disk (or S3) under
``MEDIA_ROOT/satellite/`` and are referenced by path/URL fields here. This
keeps the database small and queryable while large rasters stay in
object/file storage, which is the right split for this workload.
"""
from __future__ import annotations

from django.contrib.gis.db import models as gis_models
from django.db import models

from apps.core.models import SeverityLevel, TimeStampedModel


class SatelliteSource(models.TextChoices):
    SENTINEL1 = "sentinel-1", "Sentinel-1 (SAR)"
    SENTINEL2 = "sentinel-2", "Sentinel-2 (Optical)"
    LANDSAT = "landsat", "Landsat"


class SceneStatus(models.TextChoices):
    DISCOVERED = "discovered", "Discovered"
    DOWNLOADING = "downloading", "Downloading"
    DOWNLOADED = "downloaded", "Downloaded"
    PROCESSING = "processing", "Processing"
    PROCESSED = "processed", "Processed"
    FAILED = "failed", "Failed"


class SatelliteScene(TimeStampedModel):
    """Metadata for a single satellite scene discovered/downloaded via PyGeoVision.

    ``scene_id`` is the provider's own scene identifier (STAC item id) and is
    unique so re-running a search never creates duplicate rows for the same
    acquisition -- ``sync_satellite_scenes`` relies on ``get_or_create`` here.
    """

    scene_id = models.CharField(max_length=255, unique=True, db_index=True)
    source = models.CharField(max_length=20, choices=SatelliteSource.choices, db_index=True)
    provider = models.CharField(max_length=50, help_text="e.g. planetary_computer, copernicus")
    acquisition_date = models.DateTimeField(db_index=True)
    cloud_cover_pct = models.FloatField(null=True, blank=True)
    footprint = gis_models.PolygonField(srid=4326, null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=SceneStatus.choices, default=SceneStatus.DISCOVERED, db_index=True
    )
    raw_path = models.CharField(max_length=500, blank=True, help_text="Local/S3 path to raw download")
    preprocessed_path = models.CharField(
        max_length=500, blank=True, help_text="Path to prepare_for_ai() output"
    )
    error_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True, help_text="Raw STAC properties")

    class Meta:
        ordering = ["-acquisition_date"]
        verbose_name = "Satellite Scene"
        verbose_name_plural = "Satellite Scenes"
        indexes = [
            models.Index(fields=["source", "status", "-acquisition_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_source_display()} {self.scene_id} ({self.acquisition_date:%Y-%m-%d})"


class FloodZone(TimeStampedModel):
    """A predefined flood risk zone (e.g. an Odaw River basin sub-catchment).

    Risk thresholds here are the per-zone overrides referenced by the alert
    rules engine; a zone with no sensor stations still gets risk assessments
    purely from satellite-derived flood maps.
    """

    name = models.CharField(max_length=150)
    geometry = gis_models.PolygonField(srid=4326)
    description = models.TextField(blank=True)
    current_risk_level = models.CharField(
        max_length=10, choices=SeverityLevel.choices, default=SeverityLevel.GREEN, db_index=True
    )
    water_level_threshold_cm = models.FloatField(
        default=50.0, help_text="Water level above which this zone is considered at risk"
    )
    rainfall_threshold_mm = models.FloatField(
        default=40.0, help_text="Rainfall (mm/hour) above which this zone is considered at risk"
    )
    population_estimate = models.PositiveIntegerField(null=True, blank=True)
    last_assessed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Flood Risk Zone"
        verbose_name_plural = "Flood Risk Zones"

    def __str__(self) -> str:
        return f"{self.name} [{self.get_current_risk_level_display()}]"


class FloodMap(TimeStampedModel):
    """A generated flood-extent raster/vector product derived from one or
    more satellite scenes (optionally combined with sensor confirmation).

    ``source_scene`` is nullable because a FloodMap can also be produced
    purely from change-detection across two scenes (before/after) -- in
    that case both are recorded in ``metadata`` rather than forcing a
    single-scene FK.
    """

    source_scene = models.ForeignKey(
        SatelliteScene, null=True, blank=True, on_delete=models.SET_NULL, related_name="flood_maps"
    )
    flood_zone = models.ForeignKey(
        FloodZone, null=True, blank=True, on_delete=models.SET_NULL, related_name="flood_maps"
    )
    extent_geometry = gis_models.MultiPolygonField(
        srid=4326, null=True, blank=True, help_text="Vectorised flood extent"
    )
    raster_path = models.CharField(max_length=500, blank=True, help_text="Path to flood mask GeoTIFF")
    flooded_area_ha = models.FloatField(default=0.0)
    confidence = models.FloatField(
        default=0.0, help_text="0-1, derived from MNDWI threshold strength / IoT confirmation"
    )
    confirmed_by_sensors = models.BooleanField(
        default=False, help_text="True when sensor readings in this zone corroborate the satellite detection"
    )
    detection_method = models.CharField(
        max_length=50,
        default="mndwi_threshold",
        help_text="e.g. mndwi_threshold, changeformer, sar_backscatter",
    )
    statistics = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Flood Map"
        verbose_name_plural = "Flood Maps"
        indexes = [
            models.Index(fields=["flood_zone", "-created_at"]),
        ]

    def __str__(self) -> str:
        zone = self.flood_zone.name if self.flood_zone else "Accra-wide"
        return f"FloodMap[{zone}] {self.created_at:%Y-%m-%d %H:%M} ({self.flooded_area_ha:.1f} ha)"
