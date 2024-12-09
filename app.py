"""
AEOS Real-Time Access Control Dashboard

A web-based monitoring dashboard for Nedap AEOS that combines:
- SOAP web services (Zeep) for real-time event streaming (findEvent)
- SQL Server views for heavy analytics (hourly traffic, top access points)
- WebSocket push via Flask-SocketIO for live client updates

Architecture follows the official AEOS integration model:
  - Real-time data   → AEOS SOAP Web Services (aeosws)
  - Bulk analytics    → SQL Server read-only view (vw_AeosEventLog)
  - Live UI updates   → WebSocket (Socket.IO)

References:
    AEOS Web Services WSDL — http://<server>:8443/aeosws?wsdl
    EventInfo fields: Id, EventTypeId, EventTypeName, DateTime, HostName,
        AccesspointId, AccesspointName, EntranceId, EntranceName,
        IdentifierId, Identifier, CarrierId, CarrierFullName
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
from zeep import Client as SoapClient
from zeep.transports import Transport
from requests import Session as RequestsSession

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# AEOS SOAP Web Services
AEOS_WSDL_URL = os.getenv("AEOS_WSDL_URL", "https://localhost:8443/aeosws?wsdl")
AEOS_WS_USER = os.getenv("AEOS_WS_USER", "")
AEOS_WS_PASSWORD = os.getenv("AEOS_WS_PASSWORD", "")
AEOS_WS_VERIFY_SSL = os.getenv("AEOS_WS_VERIFY_SSL", "false").lower() in ("true", "1")

# SQL Server (for analytics views)
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
# AEOS SOAP Client
# ---------------------------------------------------------------------------

_soap_client: Optional[SoapClient] = None


def get_soap_client() -> SoapClient:
    """
    Create or return a cached Zeep SOAP client for AEOS web services.

    Connects to the AEOS aeosws endpoint and authenticates using
    WS-Security UsernameToken (AEOS default authentication method).
    """
    global _soap_client
    if _soap_client is None:
        session = RequestsSession()
        session.verify = AEOS_WS_VERIFY_SSL
        if AEOS_WS_USER:
            session.auth = (AEOS_WS_USER, AEOS_WS_PASSWORD)
        transport = Transport(session=session, timeout=15, operation_timeout=15)
        _soap_client = SoapClient(wsdl=AEOS_WSDL_URL, transport=transport)
        logger.info("AEOS SOAP client initialized: %s", AEOS_WSDL_URL)
    return _soap_client


def soap_find_events(from_dt: datetime, to_dt: datetime = None,
                     max_results: int = 50) -> list[dict]:
    """
    Call AEOS findEvent SOAP operation.

    Returns EventInfo objects as dicts with fields matching the WSDL:
        Id, EventTypeId, EventTypeName, DateTime, HostName,
        AccesspointId, AccesspointName, EntranceId, EntranceName,
        IdentifierId, Identifier, CarrierId, CarrierFullName
    """
    client = get_soap_client()
    try:
        search = {
            "EventSearchInfo": {
                "DateTimeRange": {
                    "From": from_dt,
                    "To": to_dt or datetime.utcnow(),
                },
            },
            "SearchRange": {
                "StartRecord": 0,
                "NrOfRecords": max_results,
            },
        }
        result = client.service.findEvent(**search)

        events = []
        if result:
            for evt in result:
                events.append({
                    "Id": getattr(evt, "Id", None),
                    "EventTypeId": getattr(evt, "EventTypeId", None),
                    "EventTypeName": getattr(evt, "EventTypeName", ""),
                    "DateTime": getattr(evt, "DateTime", None),
                    "HostName": getattr(evt, "HostName", ""),
                    "AccesspointId": getattr(evt, "AccesspointId", None),
                    "AccesspointName": getattr(evt, "AccesspointName", ""),
                    "EntranceId": getattr(evt, "EntranceId", None),
                    "EntranceName": getattr(evt, "EntranceName", ""),
                    "IdentifierId": getattr(evt, "IdentifierId", None),
                    "Identifier": getattr(evt, "Identifier", ""),
                    "CarrierId": getattr(evt, "CarrierId", None),
                    "CarrierFullName": getattr(evt, "CarrierFullName", ""),
                })
        return events
    except Exception as exc:
        logger.error("SOAP findEvent failed: %s", exc)
        return []


def soap_find_access_points() -> list[dict]:
    """
    Call AEOS findAccessPoint SOAP operation.

    Returns AccessPointInfo objects with fields:
        Id, Name, HostName, Type, Description, EntranceId
    """
    client = get_soap_client()
    try:
        result = client.service.findAccessPoint(
            AccessPointSearchInfo={"Name": "*"}
        )
        points = []
        if result:
            for ap in result:
                points.append({
                    "Id": getattr(ap, "Id", None),
                    "Name": getattr(ap, "Name", ""),
                    "HostName": getattr(ap, "HostName", ""),
                    "Type": getattr(ap, "Type", ""),
                    "Description": getattr(ap, "Description", ""),
                    "EntranceId": getattr(ap, "EntranceId", None),
                })
        return points
    except Exception as exc:
        logger.error("SOAP findAccessPoint failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Database helpers (for SQL analytics views)
# ---------------------------------------------------------------------------

def get_connection() -> pyodbc.Connection:
    """Create a new SQL Server connection for analytics queries."""
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
# AEOS Event type classification
# ---------------------------------------------------------------------------
# AEOS EventTypeName is a descriptive string, not a boolean.
# Common values from the AEOS event log:

GRANTED_TYPES = {
    "Access granted",
    "Access granted (first person)",
    "Access granted with extended unlock",
}

DENIED_TYPES = {
    "Access denied",
    "Access denied: badge not valid",
    "Access denied: badge blocked",
    "Access denied: badge unknown",
    "Access denied: no authorisation",
    "Access denied: antipassback",
    "Access denied: wrong time schedule",
}

ALARM_TYPES = {
    "Door forced open",
    "Door held open",
    "Tailgating",
}


def classify_event(event_type_name: str) -> str:
    """Classify an AEOS EventTypeName into a category."""
    name = event_type_name.strip()
    if name in GRANTED_TYPES or name.lower().startswith("access granted"):
        return "granted"
    if name in DENIED_TYPES or name.lower().startswith("access denied"):
        return "denied"
    if name in ALARM_TYPES:
        return "alarm"
    return "other"


# ---------------------------------------------------------------------------
# SQL Analytics Queries — uses vw_AeosEventLog view
# ---------------------------------------------------------------------------
# The view vw_AeosEventLog must be created by the DBA to expose the
# AEOS internal event log with columns matching the WSDL EventInfo:
#
#   CREATE VIEW dbo.vw_AeosEventLog AS
#   SELECT
#       e.Id,
#       e.EventTypeId,
#       et.EventTypeName,
#       e.DateTime,
#       e.HostName,
#       e.AccesspointId,
#       ap.AccesspointName,
#       e.EntranceId,
#       en.EntranceName,
#       e.IdentifierId,
#       e.Identifier,
#       e.CarrierId,
#       e.CarrierFullName
#   FROM dbo.<internal_event_table> e
#   JOIN ...
#
# Column names follow the AEOS WSDL EventInfo schema exactly.
# ---------------------------------------------------------------------------

SQL_HOURLY_TRAFFIC = """
SELECT
    DATEPART(HOUR, ev.[DateTime]) AS [Hour],
    COUNT(*) AS EventCount,
    SUM(CASE WHEN ev.EventTypeName LIKE 'Access granted%' THEN 1 ELSE 0 END) AS Granted,
    SUM(CASE WHEN ev.EventTypeName LIKE 'Access denied%' THEN 1 ELSE 0 END) AS Denied
FROM dbo.vw_AeosEventLog ev WITH (NOLOCK)
WHERE ev.[DateTime] >= @since
  AND ev.[DateTime] < @until
GROUP BY DATEPART(HOUR, ev.[DateTime])
ORDER BY [Hour];
"""

SQL_TOP_ACCESS_POINTS = """
SELECT TOP (@top)
    ev.AccesspointName,
    COUNT(*) AS EventCount,
    SUM(CASE WHEN ev.EventTypeName LIKE 'Access granted%' THEN 1 ELSE 0 END) AS Granted,
    SUM(CASE WHEN ev.EventTypeName LIKE 'Access denied%' THEN 1 ELSE 0 END) AS Denied
FROM dbo.vw_AeosEventLog ev WITH (NOLOCK)
WHERE ev.[DateTime] >= @since
GROUP BY ev.AccesspointName
ORDER BY EventCount DESC;
"""

SQL_SECURITY_ALERTS = """
SELECT TOP (@top)
    ev.[DateTime],
    ev.EventTypeName,
    ev.AccesspointName,
    ev.EntranceName,
    ev.CarrierFullName,
    ev.Identifier,
    CASE
        WHEN ev.EventTypeName = 'Tailgating'       THEN 'Tailgating détecté'
        WHEN ev.EventTypeName = 'Door forced open'  THEN 'Porte forcée'
        WHEN ev.EventTypeName = 'Door held open'    THEN 'Porte maintenue ouverte'
        WHEN ev.EventTypeName LIKE 'Access denied%' THEN 'Accès refusé — ' + ev.EventTypeName
        ELSE ev.EventTypeName
    END AS AlertDescription
FROM dbo.vw_AeosEventLog ev WITH (NOLOCK)
WHERE ev.[DateTime] >= @since
  AND (
      ev.EventTypeName LIKE 'Access denied%'
      OR ev.EventTypeName IN ('Door forced open', 'Door held open', 'Tailgating')
  )
ORDER BY ev.[DateTime] DESC;
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
    """Health check — test both SOAP and SQL connections."""
    soap_status = "ok"
    db_status = "ok"

    try:
        get_soap_client()
    except Exception as exc:
        soap_status = f"error: {exc}"

    try:
        with get_connection() as conn:
            conn.cursor().execute("SELECT 1")
    except Exception as exc:
        db_status = f"error: {exc}"

    return jsonify({
        "status": "ok",
        "aeos_soap": soap_status,
        "database": db_status,
        "timestamp": datetime.utcnow().isoformat(),
    })


@app.route("/api/events/recent")
def api_recent_events():
    """
    Return recent access events from AEOS via SOAP findEvent.

    Events are returned with the full AEOS EventInfo structure:
    Id, EventTypeName, DateTime, AccesspointName, CarrierFullName, etc.
    """
    limit = min(int(request.args.get("limit", 50)), 500)
    hours = int(request.args.get("hours", 1))
    since = datetime.utcnow() - timedelta(hours=hours)

    try:
        events = soap_find_events(from_dt=since, max_results=limit)
        # Add classification for the UI
        for evt in events:
            evt["_status"] = classify_event(evt.get("EventTypeName", ""))
        return jsonify({"events": json.loads(json.dumps(events, default=serialize))})
    except Exception as exc:
        logger.error("Failed to fetch events: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/accesspoints")
def api_access_points():
    """Return all access points from AEOS via SOAP findAccessPoint."""
    try:
        points = soap_find_access_points()
        return jsonify({"access_points": points})
    except Exception as exc:
        logger.error("Failed to fetch access points: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/analytics/hourly")
def api_hourly_traffic():
    """Return hourly traffic breakdown from SQL analytics view."""
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
    """Return busiest access points from SQL analytics view."""
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
    """Return security alerts from SQL analytics view."""
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
# WebSocket event push — polls AEOS SOAP findEvent
# ---------------------------------------------------------------------------

_last_event_time: Optional[datetime] = None


def poll_new_events():
    """Background task: poll AEOS findEvent SOAP and push via WebSocket."""
    global _last_event_time
    _last_event_time = datetime.utcnow()

    while True:
        socketio.sleep(POLL_INTERVAL)
        try:
            events = soap_find_events(from_dt=_last_event_time, max_results=20)
            if events:
                for evt in events:
                    evt["_status"] = classify_event(evt.get("EventTypeName", ""))

                # Update watermark to latest event DateTime
                latest = max(
                    (e["DateTime"] for e in events if e.get("DateTime")),
                    default=_last_event_time,
                )
                if isinstance(latest, str):
                    latest = datetime.fromisoformat(latest)
                _last_event_time = latest

                socketio.emit(
                    "new_events",
                    json.loads(json.dumps(events, default=serialize)),
                    namespace="/",
                )
                logger.debug("Pushed %d new events via WebSocket", len(events))
        except Exception as exc:
            logger.warning("Event poll failed: %s", exc)


@socketio.on("connect")
def handle_connect():
    """Handle new WebSocket connection."""
    logger.info("Client connected: %s", request.sid)
    emit("status", {"message": "Connecté au Dashboard AEOS"})


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
