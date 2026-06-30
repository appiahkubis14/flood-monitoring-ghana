# FloodWatch Ghana — User Guide

## For community members

### Receiving flood alerts (no account needed)

Visit the dashboard (`/dashboard/`) and use the "Subscribe to Alerts" flow
(`POST /api/alerts/subscribe/` under the hood), or ask a field officer to
register your phone number. You'll receive WhatsApp messages by default
(SMS is used automatically if WhatsApp delivery fails) when a flood event
is detected in your selected zone(s) at or above your chosen severity.

### Reporting flooding you see

Open `/dashboard/reports/` and click "Submit a Report" — no login required.
Select the nearest flood zone, choose a severity (ankle/knee/waist-deep),
and optionally attach a photo. Reports marked **Severe** automatically open
or escalate a flood event for that zone, the same as a sensor or satellite
detection would.

A field officer or admin will review and "verify" your report — verified
reports are what feed into the public map and historical record; unverified
reports are still visible but flagged as such.

## For field officers / admins

### Registering a new sensor station

Either through Django admin (`/admin/sensors/sensorstation/add/`, which
gives you a map widget for placing the exact location), or in bulk via:

```bash
docker compose exec web python scripts/deploy_sensors.py stations.csv
```

### Adjusting alert thresholds

`/dashboard/settings/` (staff only) lets you tune each zone's water-level
and rainfall thresholds without touching code or redeploying. Changes take
effect on the *next* sensor reading or satellite cycle — there's no need to
restart anything.

### Sending a manual broadcast

From `/dashboard/alerts/`, the "Broadcast" button lets you send a message
to all subscribers (or subscribers of one zone) outside of the automatic
detection pipeline — useful for "shelter open at X" or "road closed"
announcements that aren't themselves a new flood detection.

### Triggering satellite monitoring manually

Normally runs automatically every 24h. To force an immediate run (e.g.
after a major storm, before the scheduled cycle would catch it):
`/dashboard/settings/` → "Run Now", or `POST /api/admin/satellite/run/`.

### Verifying community reports

`/dashboard/reports/` shows a "Mark Verified" button on each unverified
report (staff only). Verifying a report records who verified it and when.

## Understanding the severity scale

| Colour | Level | Meaning |
|---|---|---|
| 🟢 Green | Safe | No active flood event |
| 🟡 Yellow | Watch | Elevated water level/rainfall, monitor closely |
| 🟠 Orange | Warning | Threshold exceeded by one source (sensor *or* satellite) |
| 🔴 Red | Emergency | Threshold exceeded with **combined** sensor + satellite confirmation, or a single source far above threshold |

Combined (sensor + satellite) confirmation is treated as the most reliable
signal and is the only path that can escalate a detection all the way to
Red from a moderate single-source reading — see `apps.alerts.rules.AlertRules.combine()`.
