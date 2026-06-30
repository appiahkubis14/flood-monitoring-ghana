"""
Spectral water-index helpers built on top of PyGeoVision's preprocessed
GeoTIFFs, plus the area/vectorisation utilities the satellite pipeline uses
to turn a raw flood mask into a stored :class:`FloodMap` record.

All functions here operate on **already-preprocessed** scenes (the output
of ``client.prepare_for_ai()``) -- never on raw downloads -- so the band
order, normalisation, and cloud masking PyGeoVision applies upstream are
always respected. See ``apps.satellite.processors`` for the pipeline that
produces those preprocessed paths.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("apps.satellite")

# Band positions within the standard 6-band Sentinel-2 L2A stack this
# project downloads via PyGeoVision: [B02, B03, B04, B08, B11, B12]
# = [Blue, Green, Red, NIR, SWIR1, SWIR2].
BAND_BLUE, BAND_GREEN, BAND_RED, BAND_NIR, BAND_SWIR1, BAND_SWIR2 = range(6)

# MNDWI above this threshold is classified as open water / flooded surface.
# 0.20 is a conservative middle ground for Sentinel-2 over urban/peri-urban
# Accra -- low enough to catch turbid floodwater (which has a weaker MNDWI
# signal than clean water), high enough to avoid flagging wet bare soil.
MNDWI_FLOOD_THRESHOLD = 0.20


def compute_mndwi(stack: np.ndarray) -> np.ndarray:
    """Modified NDWI = (Green - SWIR1) / (Green + SWIR1).

    Preferred over plain NDWI for flood mapping in built-up areas because
    SWIR1 (vs NIR) is far less affected by the urban background reflectance
    that surrounds Accra's flood-prone communities.
    """
    green = stack[BAND_GREEN].astype(np.float32)
    swir1 = stack[BAND_SWIR1].astype(np.float32)
    return (green - swir1) / (green + swir1 + 1e-8)


def compute_ndwi(stack: np.ndarray) -> np.ndarray:
    """Classic NDWI = (Green - NIR) / (Green + NIR), kept for comparison /
    cross-validation against MNDWI -- two independent water indices
    agreeing raises confidence in a detection.
    """
    green = stack[BAND_GREEN].astype(np.float32)
    nir = stack[BAND_NIR].astype(np.float32)
    return (green - nir) / (green + nir + 1e-8)


def flood_mask_from_mndwi(stack: np.ndarray, threshold: float = MNDWI_FLOOD_THRESHOLD) -> np.ndarray:
    """Binary flood mask (uint8, 1=water/flooded) from MNDWI thresholding."""
    mndwi = compute_mndwi(stack)
    return (mndwi > threshold).astype(np.uint8)


def compute_confidence(mndwi: np.ndarray, mask: np.ndarray) -> float:
    """A simple, explainable confidence score in [0, 1] for a flood
    detection: how far above threshold the *flagged* pixels sit, on
    average -- a mask where flagged pixels are barely over the threshold
    is much less trustworthy than one where they're strongly positive.
    """
    if mask.sum() == 0:
        return 0.0
    flagged_values = mndwi[mask.astype(bool)]
    margin = float(np.clip(flagged_values.mean() - MNDWI_FLOOD_THRESHOLD, 0, 0.6) / 0.6)
    return round(margin, 3)


def pixel_area_ha(transform, mask: np.ndarray) -> float:
    """Flooded area in hectares from a binary mask + the raster's affine
    transform (works for both geographic and projected CRS by using the
    transform's pixel size directly -- callers are expected to have
    reprojected to a metric CRS before calling this, matching how
    PyGeoVision's ``prepare_for_ai`` output is produced in this project).
    """
    px_w = abs(transform.a)
    px_h = abs(transform.e)
    pixel_area_m2 = px_w * px_h
    flooded_pixels = int(mask.sum())
    return round(flooded_pixels * pixel_area_m2 / 10_000.0, 2)


def vectorise_flood_mask(mask_path: str, simplify_tolerance_m: float = 2.0) -> dict | None:
    """Vectorise a binary flood-mask GeoTIFF into a GeoJSON-like dict
    (MultiPolygon), **reprojected to WGS84 (EPSG:4326)** regardless of the
    mask raster's native CRS.

    The mask itself is typically in a projected CRS (this project
    reprojects to UTM 30N / EPSG:32630 before flood detection, so pixel
    areas are in real square metres) -- but every geometry field on the
    Django models (``FloodMap.extent_geometry``, ``FloodZone.geometry``)
    is declared ``srid=4326``. Returning UTM coordinates here would silently
    corrupt any ``intersects()``/``intersection()`` call against a
    WGS84 zone geometry, so the reprojection back to 4326 happens inside
    this function rather than being left to (and potentially forgotten by)
    every caller.

    Returns ``None`` when the mask has no flooded pixels at all -- callers
    should treat that as "no FloodMap geometry to store", not an error.
    """
    try:
        import rasterio
        from rasterio.features import shapes
        from rasterio.warp import transform_geom
        from shapely.geometry import shape, mapping, MultiPolygon
        from shapely.ops import unary_union
    except ImportError as exc:
        logger.error("vectorise_flood_mask requires rasterio + shapely: %s", exc)
        return None

    with rasterio.open(mask_path) as src:
        band = src.read(1)
        transform = src.transform
        raster_crs = src.crs

    polygons = []
    for geom, value in shapes(band, mask=(band == 1), transform=transform):
        if value == 1:
            polygons.append(shape(geom))

    if not polygons:
        return None

    # Simplify in the raster's native (typically metric) units BEFORE
    # reprojecting -- simplifying in degrees with a metre-scale tolerance
    # is the bug this docstring warns about avoiding.
    merged = unary_union(polygons).simplify(simplify_tolerance_m)

    if raster_crs is not None and raster_crs.to_epsg() != 4326:
        reprojected = transform_geom(raster_crs, "EPSG:4326", mapping(merged))
        merged = shape(reprojected)

    if merged.geom_type == "Polygon":
        merged = MultiPolygon([merged])

    return mapping(merged)


def summarise_flood_map(mask_path: str) -> dict[str, Any]:
    """One-call convenience: load a flood-mask GeoTIFF and return area,
    confidence proxy (pixel count fraction), and a human-readable summary
    -- used by the dashboard's flood map detail view to avoid re-deriving
    these from the raw raster on every request.
    """
    try:
        import rasterio
    except ImportError:
        return {"error": "rasterio not available"}

    with rasterio.open(mask_path) as src:
        band = src.read(1)
        transform = src.transform
        total_pixels = band.size

    flooded_pixels = int((band == 1).sum())
    area_ha = pixel_area_ha(transform, band)
    coverage_pct = round(flooded_pixels / total_pixels * 100, 2) if total_pixels else 0.0

    return {
        "flooded_area_ha": area_ha,
        "coverage_pct": coverage_pct,
        "flooded_pixels": flooded_pixels,
        "total_pixels": total_pixels,
    }
