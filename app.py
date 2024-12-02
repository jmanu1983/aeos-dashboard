"""
AEOS Real-Time Access Control Dashboard

A web-based monitoring dashboard that connects to the Nedap AEOS SQL Server
database and provides real-time visibility into access events, door status,
and security alerts via WebSocket push.

Features:
    - Live access event feed with WebSocket push
    - Door status monitoring (online/offline/alarm)
    - Daily traffic analytics with hourly breakdown
    - Top-N busiest access points ranking
    - Tailgating and forced-door alert detection
    - RESTful API for integration with third-party systems
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import pyodbc
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_DRIVER = os.getenv("DB_DRIVER", "{ODBC Driver 17 for SQL Server}")
DB_SERVER = os.getenv("DB_SERVER", "localhost")
DB_NAME = os.getenv("DB_NAME", "aeosdb")
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_TRUSTED = os.getenv("DB_TRUSTED_CONNECTION", "no").lower() in ("yes", "true", "1")

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("aeos-dashboard")

# ---------------------------------------------------------------------------
# Flask + SocketIO
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_connection() -> pyodbc.Connection:
    """Create a new SQL Server connection using environment configuration."""
    if DB_TRUSTED:
        conn_str = (
            f"DRIVER={DB_DRIVER};"
            f"SERVER={DB_SERVER};"
            f"DATABASE={DB_NAME};"
            f"Trusted_Connection=yes;"
            f"TrustServerCertificate=yes;"
        )
    else:
        conn_str = (
            f"DRIVER={DB_DRIVER};"
            f"SERVER={DB_SERVER};"
            f"DATABASE={DB_NAME};"
            f"UID={DB_USER};"
            f"PWD={DB_PASSWORD};"
            f"TrustServerCertificate=yes;"
        )
    return pyodbc.connect(conn_str, timeout=10)


def query_rows(sql: str, params: tuple = ()) -> list[dict]:
    """Execute a SELECT and return rows as a list of dicts."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def serialize(obj):
    """JSON serializer for datetime objects."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


# ---------------------------------------------------------------------------
# SQL Queries
# ---------------------------------------------------------------------------

SQL_RECENT_EVENTS = """
SELECT TOP (@top)
    e.EventTime,
    e.EventType,
    p.LastName,
    p.FirstName,
    p.PersonnelNr,
    ap.Name AS AccessPoint,
    e.Granted,
    e.ReaderName
FROM dbo.Event e WITH (NOLOCK)
LEFT JOIN dbo.Carrier c WITH (NOLOCK) ON e.CarrierId = c.Id
LEFT JOIN dbo.Person p WITH (NOLOCK) ON c.PersonId = p.Id
LEFT JOIN dbo.AccessPoint ap WITH (NOLOCK) ON e.AccessPointId = ap.Id
WHERE e.EventTime >= @since
ORDER BY e.EventTime DESC;
"""

SQL_DOOR_STATUS = """
SELECT
    ap.Id,
    ap.Name,
    ap.Online,
    ap.AlarmState,
    ap.DoorState,
    ap.LastEventTime
FROM dbo.AccessPoint ap WITH (NOLOCK)
WHERE ap.IsActive = 1
ORDER BY ap.Name;
"""

SQL_HOURLY_TRAFFIC = """
SELECT
    DATEPART(HOUR, e.EventTime) AS Hour,
    COUNT(*) AS EventCount,
    SUM(CASE WHEN e.Granted = 1 THEN 1 ELSE 0 END) AS Granted,
    SUM(CASE WHEN e.Granted = 0 THEN 1 ELSE 0 END) AS Denied
FROM dbo.Event e WITH (NOLOCK)
WHERE e.EventTime >= @since
  AND e.EventTime < @until
GROUP BY DATEPART(HOUR, e.EventTime)
ORDER BY Hour;
"""

SQL_TOP_ACCESS_POINTS = """
SELECT TOP (@top)
    ap.Name AS AccessPoint,
    COUNT(*) AS EventCount,
    SUM(CASE WHEN e.Granted = 1 THEN 1 ELSE 0 END) AS Granted,
    SUM(CASE WHEN e.Granted = 0 THEN 1 ELSE 0 END) AS Denied
FROM dbo.Event e WITH (NOLOCK)
JOIN dbo.AccessPoint ap WITH (NOLOCK) ON e.AccessPointId = ap.Id
WHERE e.EventTime >= @since
GROUP BY ap.Name
ORDER BY EventCount DESC;
"""

SQL_SECURITY_ALERTS = """
SELECT TOP (@top)
    e.EventTime,
    e.EventType,
    ap.Name AS AccessPoint,
    p.LastName,
    p.FirstName,
    e.ReaderName,
    CASE
        WHEN e.EventType IN ('TAILGATE','TAILGATING') THEN 'Tailgating detected'
        WHEN e.EventType IN ('FORCED_DOOR','DOOR_FORCED') THEN 'Door forced open'
        WHEN e.EventType = 'DOOR_HELD_OPEN' THEN 'Door held open too long'
        WHEN e.Granted = 0 THEN 'Access denied'
        ELSE e.EventType
    END AS AlertDescription
FROM dbo.Event e WITH (NOLOCK)
LEFT JOIN dbo.AccessPoint ap WITH (NOLOCK) ON e.AccessPointId = ap.Id
LEFT JOIN dbo.Carrier c WITH (NOLOCK) ON e.CarrierId = c.Id
LEFT JOIN dbo.Person p WITH (NOLOCK) ON c.PersonId = p.Id
WHERE e.EventTime >= @since
  AND (
      e.Granted = 0
      OR e.EventType IN (
          'TAILGATE','TAILGATING','FORCED_DOOR','DOOR_FORCED','DOOR_HELD_OPEN'
      )
  )
ORDER BY e.EventTime DESC;
"""


# ---------------------------------------------------------------------------
# REST API endpoints
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Render the main dashboard page."""
    return render_template("dashboard.html")


@app.route("/api/health")
def health():
    """Health check endpoint."""
    try:
        with get_connection() as conn:
            conn.cursor().execute("SELECT 1")
        db_status = "connected"
    except Exception as exc:
        db_status = f"error: {exc}"
    return jsonify({"status": "ok", "database": db_status, "timestamp": datetime.utcnow().isoformat()})


@app.route("/api/events/recent")
def api_recent_events():
    """Return the most recent access events."""
    top = min(int(request.args.get("limit", 50)), 500)
    hours = int(request.args.get("hours", 1))
    since = datetime.utcnow() - timedelta(hours=hours)
    try:
        rows = query_rows(SQL_RECENT_EVENTS, (top, since))
        return jsonify({"events": json.loads(json.dumps(rows, default=serialize))})
    except Exception as exc:
        logger.error("Failed to fetch events: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/doors/status")
def api_door_status():
    """Return the current status of all active access points."""
    try:
        rows = query_rows(SQL_DOOR_STATUS)
        return jsonify({"doors": json.loads(json.dumps(rows, default=serialize))})
    except Exception as exc:
        logger.error("Failed to fetch door status: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/analytics/hourly")
def api_hourly_traffic():
    """Return hourly traffic breakdown for a given date."""
    date_str = request.args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    target = datetime.strptime(date_str, "%Y-%m-%d")
    since = target.replace(hour=0, minute=0, second=0)
    until = since + timedelta(days=1)
    try:
        rows = query_rows(SQL_HOURLY_TRAFFIC, (since, until))
        return jsonify({"date": date_str, "hourly": rows})
    except Exception as exc:
        logger.error("Failed to fetch hourly traffic: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/analytics/top-access-points")
def api_top_access_points():
    """Return the busiest access points."""
    top = min(int(request.args.get("limit", 10)), 50)
    hours = int(request.args.get("hours", 24))
    since = datetime.utcnow() - timedelta(hours=hours)
    try:
        rows = query_rows(SQL_TOP_ACCESS_POINTS, (top, since))
        return jsonify({"access_points": rows})
    except Exception as exc:
        logger.error("Failed to fetch top access points: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/alerts")
def api_security_alerts():
    """Return recent security alerts (denied access, tailgating, forced doors)."""
    top = min(int(request.args.get("limit", 20)), 200)
    hours = int(request.args.get("hours", 24))
    since = datetime.utcnow() - timedelta(hours=hours)
    try:
        rows = query_rows(SQL_SECURITY_ALERTS, (top, since))
        return jsonify({"alerts": json.loads(json.dumps(rows, default=serialize))})
    except Exception as exc:
        logger.error("Failed to fetch alerts: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# WebSocket event push
# ---------------------------------------------------------------------------

_last_event_time: Optional[datetime] = None


def poll_new_events():
    """Background task that polls for new events and pushes via WebSocket."""
    global _last_event_time
    _last_event_time = datetime.utcnow()

    while True:
        socketio.sleep(POLL_INTERVAL)
        try:
            rows = query_rows(SQL_RECENT_EVENTS, (10, _last_event_time))
            if rows:
                _last_event_time = max(
                    row["EventTime"] for row in rows if row.get("EventTime")
                ) or _last_event_time
                socketio.emit(
                    "new_events",
                    json.loads(json.dumps(rows, default=serialize)),
                    namespace="/",
                )
                logger.debug("Pushed %d new events", len(rows))
        except Exception as exc:
            logger.warning("Event poll failed: %s", exc)


@socketio.on("connect")
def handle_connect():
    """Handle new WebSocket connection."""
    logger.info("Client connected: %s", request.sid)
    emit("status", {"message": "Connected to AEOS Dashboard"})


@socketio.on("disconnect")
def handle_disconnect():
    """Handle WebSocket disconnection."""
    logger.info("Client disconnected: %s", request.sid)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    socketio.start_background_task(poll_new_events)
    socketio.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
