"""
Template context processors for the dashboard app.

``flood_status`` is wired into every template render via
``TEMPLATES[0]["OPTIONS"]["context_processors"]`` in settings/base.py, so
the site-wide status banner (colour-coded green/yellow/orange/red) and the
sidebar's "active alerts" badge can appear on *every* page -- login screen
included -- without every view needing to remember to pass this data in
its own context.

Kept deliberately cheap: one small aggregate query, cached for 60 seconds,
because this runs on every single page request including anonymous ones.
"""
from __future__ import annotations

from django.core.cache import cache

CACHE_KEY = "dashboard:flood_status_context"
CACHE_TIMEOUT_SECONDS = 60


def flood_status(request) -> dict:
    """Returns the current Accra-wide flood status for use in templates as
    ``{{ flood_status.overall_severity }}``, ``{{ flood_status.active_event_count }}``, etc.

    Cache reads/writes are wrapped defensively: this context processor runs
    on *every* page render (including error pages), so a transient Redis
    outage must degrade to "compute it fresh, skip the cache" rather than
    taking down the entire site with a 500 on every request.
    """
    try:
        cached = cache.get(CACHE_KEY)
    except Exception:  # noqa: BLE001 -- cache backend being down must not break every page
        cached = None

    if cached is not None:
        return {"flood_status": cached}

    data = _compute_flood_status()

    try:
        cache.set(CACHE_KEY, data, CACHE_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001
        pass  # caching is an optimisation here, not a correctness requirement

    return {"flood_status": data}


def _compute_flood_status() -> dict:
    # Imported lazily (not at module level) so this module has zero
    # required app dependencies at Django startup time -- context
    # processors are resolved very early in the settings load, and a
    # broken import here would break literally every page on the site,
    # including the 500 error page itself.
    from apps.alerts.models import FloodEvent
    from apps.core.models import SeverityLevel
    from apps.satellite.models import FloodZone

    active_events = FloodEvent.objects.filter(ended_at__isnull=True).select_related("flood_zone")
    severities = [e.severity for e in active_events]

    overall = SeverityLevel.GREEN
    for level in (SeverityLevel.RED, SeverityLevel.ORANGE, SeverityLevel.YELLOW):
        if level in severities:
            overall = level
            break

    return {
        "overall_severity": overall,
        "overall_severity_label": dict(SeverityLevel.choices).get(overall, "Safe"),
        "active_event_count": len(severities),
        "active_zones": [e.flood_zone.name for e in active_events],
        "total_zones": FloodZone.objects.count(),
    }
