/**
 * FloodWatch Ghana — global WebSocket connections for live sensor readings
 * and flood alerts.
 *
 * Loaded on every page (see base.html). Two persistent connections:
 *   /ws/sensors/  -- live SensorReading broadcasts (see apps.sensors.consumers)
 *   /ws/alerts/   -- new Alert broadcasts (see apps.alerts.consumers, wired
 *                    via apps.sensors.consumers.AlertConsumer's group_send
 *                    pattern -- see apps.alerts.tasks.send_alert for the
 *                    publish side, added when that task is extended to
 *                    broadcast alongside delivery)
 *
 * Both sockets auto-reconnect with simple exponential backoff -- a
 * dashboard left open overnight must not silently stop receiving live
 * updates after one dropped connection.
 */
(function () {
    "use strict";

    const WS_SCHEME = window.location.protocol === "https:" ? "wss" : "ws";
    const WS_HOST = window.location.hostname + ":8001";  // Daphne port, see docker-compose.yml

    function connectWithBackoff(path, onMessage, attempt = 0) {
        const url = `${WS_SCHEME}://${WS_HOST}${path}`;
        let socket;
        try {
            socket = new WebSocket(url);
        } catch (err) {
            console.warn(`FloodWatch WS: failed to construct socket for ${path}`, err);
            return;
        }

        socket.addEventListener("open", () => {
            console.info(`FloodWatch WS connected: ${path}`);
        });

        socket.addEventListener("message", (event) => {
            try {
                const data = JSON.parse(event.data);
                onMessage(data);
            } catch (err) {
                console.warn(`FloodWatch WS: malformed message on ${path}`, err);
            }
        });

        socket.addEventListener("close", () => {
            const delay = Math.min(30000, 1000 * Math.pow(2, attempt));
            console.warn(`FloodWatch WS closed (${path}); reconnecting in ${delay}ms`);
            setTimeout(() => connectWithBackoff(path, onMessage, attempt + 1), delay);
        });

        socket.addEventListener("error", () => socket.close());
    }

    // ── Live sensor readings ────────────────────────────────────────────────
    connectWithBackoff("/ws/sensors/", (payload) => {
        document.dispatchEvent(new CustomEvent("floodwatch:sensor-reading", { detail: payload }));
    });

    // ── Live alert feed (updates the topbar bell badge on every page) ──────
    let liveAlertCount = 0;
    connectWithBackoff("/ws/alerts/", (payload) => {
        document.dispatchEvent(new CustomEvent("floodwatch:alert", { detail: payload }));

        liveAlertCount += 1;
        const badge = document.getElementById("live-alert-count");
        if (badge) badge.textContent = liveAlertCount;

        const list = document.getElementById("live-alert-list");
        if (list) {
            const item = document.createElement("div");
            item.className = "p-2 border-bottom fs-13";
            item.innerHTML = `<strong>${payload.severity || "Alert"}</strong>: ${payload.message || "New flood alert"}`;
            list.prepend(item);
        }
    });
})();
