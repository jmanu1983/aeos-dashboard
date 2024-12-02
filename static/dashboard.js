/**
 * AEOS Dashboard — Client-side logic
 *
 * Handles WebSocket connection, REST API polling, and Chart.js rendering.
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
    document.getElementById("ws-label").textContent = "Disconnected";
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

// ---------------------------------------------------------------------------
// Events table
// ---------------------------------------------------------------------------

function prependEvents(events) {
    const tbody = document.getElementById("events-body");
    events.forEach((evt) => {
        const tr = document.createElement("tr");
        const statusClass = evt.Granted ? "granted" : "denied";
        const statusText = evt.Granted ? "Granted" : "Denied";
        const name = [evt.LastName, evt.FirstName].filter(Boolean).join(", ") || "Unknown";

        tr.innerHTML = `
            <td>${formatTime(evt.EventTime)}</td>
            <td>${name}</td>
            <td>${evt.AccessPoint || "--"}</td>
            <td><span class="badge ${statusClass}">${statusText}</span></td>
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
        const [evtData, alertData, doorData] = await Promise.all([
            fetchJSON("/api/analytics/hourly"),
            fetchJSON("/api/alerts?limit=200&hours=24"),
            fetchJSON("/api/doors/status"),
        ]);

        const totalEvents = evtData.hourly.reduce((s, h) => s + h.EventCount, 0);
        const totalDenied = evtData.hourly.reduce((s, h) => s + h.Denied, 0);
        const doorsOnline = doorData.doors.filter((d) => d.Online).length;

        document.getElementById("kpi-events-today").textContent = totalEvents.toLocaleString();
        document.getElementById("kpi-denied").textContent = totalDenied.toLocaleString();
        document.getElementById("kpi-doors-online").textContent =
            `${doorsOnline}/${doorData.doors.length}`;
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
                    { label: "Granted", data: granted, backgroundColor: "#22c55e88", borderRadius: 4 },
                    { label: "Denied", data: denied, backgroundColor: "#ef444488", borderRadius: 4 },
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
        const labels = data.access_points.map((ap) => ap.AccessPoint);
        const counts = data.access_points.map((ap) => ap.EventCount);

        const ctx = document.getElementById("top-ap-chart").getContext("2d");
        if (topAPChart) topAPChart.destroy();

        topAPChart = new Chart(ctx, {
            type: "bar",
            data: {
                labels,
                datasets: [
                    {
                        label: "Events",
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
// Door status grid
// ---------------------------------------------------------------------------

async function renderDoorGrid() {
    try {
        const data = await fetchJSON("/api/doors/status");
        const grid = document.getElementById("door-grid");
        grid.innerHTML = "";

        data.doors.forEach((door) => {
            const isOnline = door.Online;
            const hasAlarm = door.AlarmState && door.AlarmState !== "NONE";
            const dotClass = hasAlarm ? "dot alert-dot" : isOnline ? "dot online" : "dot offline";
            const stateText = hasAlarm ? door.AlarmState : isOnline ? "Online" : "Offline";

            const tile = document.createElement("div");
            tile.className = "door-tile";
            tile.innerHTML = `
                <span class="${dotClass}" style="${hasAlarm ? 'background:var(--warning);box-shadow:0 0 6px var(--warning)' : ''}"></span>
                <div>
                    <div class="door-name">${door.Name}</div>
                    <div class="door-state">${stateText}</div>
                </div>
            `;
            grid.appendChild(tile);
        });
    } catch (e) {
        console.warn("Failed to render door grid:", e);
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
            const name = [a.LastName, a.FirstName].filter(Boolean).join(", ") || "--";
            tr.innerHTML = `
                <td>${formatTime(a.EventTime)}</td>
                <td><span class="badge alert">${a.AlertDescription}</span></td>
                <td>${a.AccessPoint || "--"}</td>
                <td>${name}</td>
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
        renderDoorGrid(),
        loadAlerts(),
    ]);

    // Refresh every 30 seconds
    setInterval(() => {
        updateKPIs();
        renderHourlyChart();
        renderTopAPChart();
        renderDoorGrid();
        loadAlerts();
    }, 30000);
}

init();
