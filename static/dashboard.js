/**
 * AEOS Dashboard — Client-side logic
 *
 * Handles WebSocket connection, REST API polling, and Chart.js rendering.
 * All field names align with the AEOS WSDL EventInfo schema:
 *   DateTime, EventTypeName, AccesspointName, CarrierFullName, Identifier, etc.
 */

// ---------------------------------------------------------------------------
// WebSocket connection
// ---------------------------------------------------------------------------

const socket = io();

socket.on("connect", () => {
    document.getElementById("ws-status").classList.replace("offline", "online");
    document.getElementById("ws-label").textContent = "Live";
});

socket.on("disconnect", () => {
    document.getElementById("ws-status").classList.replace("online", "offline");
    document.getElementById("ws-label").textContent = "Déconnecté";
});

socket.on("new_events", (events) => {
    prependEvents(events);
});

// ---------------------------------------------------------------------------
// REST API helpers
// ---------------------------------------------------------------------------

async function fetchJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

function formatTime(iso) {
    if (!iso) return "--";
    const d = new Date(iso);
    return d.toLocaleTimeString("fr-CH", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/**
 * Classify an AEOS EventTypeName into a display category.
 */
function classifyEvent(eventTypeName) {
    if (!eventTypeName) return { cls: "other", label: eventTypeName || "--" };
    const lower = eventTypeName.toLowerCase();
    if (lower.startsWith("access granted"))  return { cls: "granted", label: "Accordé" };
    if (lower.startsWith("access denied"))   return { cls: "denied", label: "Refusé" };
    if (lower === "door forced open")        return { cls: "alarm", label: "Porte forcée" };
    if (lower === "door held open")          return { cls: "alarm", label: "Porte maintenue" };
    if (lower === "tailgating")              return { cls: "alarm", label: "Tailgating" };
    return { cls: "other", label: eventTypeName };
}

// ---------------------------------------------------------------------------
// Events table — uses AEOS EventInfo fields
// ---------------------------------------------------------------------------

function prependEvents(events) {
    const tbody = document.getElementById("events-body");
    events.forEach((evt) => {
        const tr = document.createElement("tr");
        const { cls, label } = classifyEvent(evt.EventTypeName);
        const name = evt.CarrierFullName || "--";

        tr.innerHTML = `
            <td>${formatTime(evt.DateTime)}</td>
            <td>${name}</td>
            <td>${evt.AccesspointName || "--"}</td>
            <td>${evt.Identifier || "--"}</td>
            <td><span class="badge ${cls}">${label}</span></td>
        `;
        tbody.insertBefore(tr, tbody.firstChild);
    });

    // Keep max 100 rows
    while (tbody.children.length > 100) {
        tbody.removeChild(tbody.lastChild);
    }
}

async function loadRecentEvents() {
    try {
        const data = await fetchJSON("/api/events/recent?limit=50&hours=1");
        prependEvents(data.events.reverse());
    } catch (e) {
        console.warn("Failed to load events:", e);
    }
}

// ---------------------------------------------------------------------------
// KPI cards
// ---------------------------------------------------------------------------

async function updateKPIs() {
    try {
        const [evtData, alertData, apData] = await Promise.all([
            fetchJSON("/api/analytics/hourly"),
            fetchJSON("/api/alerts?limit=200&hours=24"),
            fetchJSON("/api/accesspoints"),
        ]);

        const totalEvents = evtData.hourly.reduce((s, h) => s + h.EventCount, 0);
        const totalDenied = evtData.hourly.reduce((s, h) => s + h.Denied, 0);
        const totalAPs = apData.access_points ? apData.access_points.length : 0;

        document.getElementById("kpi-events-today").textContent = totalEvents.toLocaleString();
        document.getElementById("kpi-denied").textContent = totalDenied.toLocaleString();
        document.getElementById("kpi-access-points").textContent = totalAPs;
        document.getElementById("kpi-alerts").textContent = alertData.alerts.length;
    } catch (e) {
        console.warn("Failed to update KPIs:", e);
    }
}

// ---------------------------------------------------------------------------
// Charts
// ---------------------------------------------------------------------------

let hourlyChart = null;
let topAPChart = null;

async function renderHourlyChart() {
    try {
        const data = await fetchJSON("/api/analytics/hourly");
        const labels = data.hourly.map((h) => `${String(h.Hour).padStart(2, "0")}:00`);
        const granted = data.hourly.map((h) => h.Granted);
        const denied = data.hourly.map((h) => h.Denied);

        const ctx = document.getElementById("hourly-chart").getContext("2d");
        if (hourlyChart) hourlyChart.destroy();

        hourlyChart = new Chart(ctx, {
            type: "bar",
            data: {
                labels,
                datasets: [
                    { label: "Accordé", data: granted, backgroundColor: "#22c55e88", borderRadius: 4 },
                    { label: "Refusé", data: denied, backgroundColor: "#ef444488", borderRadius: 4 },
                ],
            },
            options: {
                responsive: true,
                plugins: { legend: { labels: { color: "#8b8fa3" } } },
                scales: {
                    x: { stacked: true, ticks: { color: "#8b8fa3" }, grid: { color: "#2a2d3a" } },
                    y: { stacked: true, ticks: { color: "#8b8fa3" }, grid: { color: "#2a2d3a" } },
                },
            },
        });
    } catch (e) {
        console.warn("Failed to render hourly chart:", e);
    }
}

async function renderTopAPChart() {
    try {
        const data = await fetchJSON("/api/analytics/top-access-points?limit=8&hours=24");
        const labels = data.access_points.map((ap) => ap.AccesspointName);
        const counts = data.access_points.map((ap) => ap.EventCount);

        const ctx = document.getElementById("top-ap-chart").getContext("2d");
        if (topAPChart) topAPChart.destroy();

        topAPChart = new Chart(ctx, {
            type: "bar",
            data: {
                labels,
                datasets: [
                    {
                        label: "Événements",
                        data: counts,
                        backgroundColor: "#3b82f688",
                        borderRadius: 4,
                    },
                ],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: "#8b8fa3" }, grid: { color: "#2a2d3a" } },
                    y: { ticks: { color: "#8b8fa3" }, grid: { display: false } },
                },
            },
        });
    } catch (e) {
        console.warn("Failed to render top AP chart:", e);
    }
}

// ---------------------------------------------------------------------------
// Access Points grid (from SOAP findAccessPoint)
// ---------------------------------------------------------------------------

async function renderAccessPointGrid() {
    try {
        const data = await fetchJSON("/api/accesspoints");
        const grid = document.getElementById("door-grid");
        grid.innerHTML = "";

        data.access_points.forEach((ap) => {
            const tile = document.createElement("div");
            tile.className = "door-tile";
            tile.innerHTML = `
                <span class="dot online"></span>
                <div>
                    <div class="door-name">${ap.Name}</div>
                    <div class="door-state">${ap.Type || "Reader"} — ${ap.HostName || ""}</div>
                </div>
            `;
            grid.appendChild(tile);
        });
    } catch (e) {
        console.warn("Failed to render access point grid:", e);
    }
}

// ---------------------------------------------------------------------------
// Alerts table
// ---------------------------------------------------------------------------

async function loadAlerts() {
    try {
        const data = await fetchJSON("/api/alerts?limit=20&hours=24");
        const tbody = document.getElementById("alerts-body");
        tbody.innerHTML = "";

        data.alerts.forEach((a) => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${formatTime(a.DateTime)}</td>
                <td><span class="badge alert">${a.AlertDescription}</span></td>
                <td>${a.AccesspointName || "--"}</td>
                <td>${a.CarrierFullName || "--"}</td>
                <td>${a.Identifier || "--"}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.warn("Failed to load alerts:", e);
    }
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

async function init() {
    await Promise.all([
        loadRecentEvents(),
        updateKPIs(),
        renderHourlyChart(),
        renderTopAPChart(),
        renderAccessPointGrid(),
        loadAlerts(),
    ]);

    // Refresh every 30 seconds
    setInterval(() => {
        updateKPIs();
        renderHourlyChart();
        renderTopAPChart();
        renderAccessPointGrid();
        loadAlerts();
    }, 30000);
}

init();
