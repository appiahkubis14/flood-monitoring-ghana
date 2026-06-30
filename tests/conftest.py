"""
Shared pytest fixtures for the FloodWatch Ghana test suite.

Tests run against the real PostGIS backend configured in settings -- no
SQLite/SpatiaLite fallback is used, because GeoDjango's spatial lookups
(``__within``, ``__intersects``, etc., used throughout the satellite and
alerts apps) are PostGIS-specific and a SQLite swap would silently hide
real bugs in geospatial query code. Run tests via the Docker Compose stack
(``docker compose exec web pytest``) so a real PostGIS instance is always
present.
"""
import pytest


@pytest.fixture
def accra_point():
    """A representative point inside the Odaw River basin study area."""
    from django.contrib.gis.geos import Point
    return Point(-0.2107, 5.5680, srid=4326)  # Agbogbloshie, central Accra


@pytest.fixture
def accra_polygon():
    """A small representative polygon covering part of the Odaw basin."""
    from django.contrib.gis.geos import Polygon
    return Polygon((
        (-0.22, 5.56), (-0.20, 5.56), (-0.20, 5.58), (-0.22, 5.58), (-0.22, 5.56),
    ), srid=4326)
