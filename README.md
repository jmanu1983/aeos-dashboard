# AEOS Real-Time Dashboard

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0+-green?logo=flask)
![SQL Server](https://img.shields.io/badge/SQL%20Server-2019+-CC2927?logo=microsoftsqlserver&logoColor=white)
![WebSocket](https://img.shields.io/badge/WebSocket-SocketIO-black?logo=socketdotio)
![License](https://img.shields.io/badge/License-MIT-yellow)

A **real-time monitoring dashboard** for the Nedap AEOS access control system. Provides live visibility into access events, door status, traffic analytics, and security alerts — all powered by SQL Server queries and WebSocket push.

![Dashboard Preview](https://img.shields.io/badge/Preview-Dark%20Theme-0f1117?style=for-the-badge)

## Features

- **Live Event Feed** — Access events pushed in real-time via WebSocket (Socket.IO)
- **Door Status Monitoring** — Online/offline/alarm state for all access points
- **Hourly Traffic Analytics** — Stacked bar chart of granted vs. denied events
- **Top Access Points** — Ranking of busiest doors over 24h
- **Security Alerts** — Tailgating, forced doors, held-open, and denied access
- **KPI Cards** — At-a-glance metrics (events today, denied, doors online, alerts)
- **REST API** — All data available as JSON for third-party integration
- **Modern Dark UI** — Responsive CSS Grid layout, Chart.js visualizations

## Architecture

```
┌──────────────┐     SQL queries     ┌──────────────────┐
│  SQL Server  │ ◄──────────────────► │  Flask Backend   │
│  (aeosdb)    │                      │  + SocketIO      │
└──────────────┘                      └────────┬─────────┘
                                               │
                                     WebSocket │ REST API
                                               │
                                      ┌────────▼─────────┐
                                      │  Browser Client   │
                                      │  Chart.js + Live  │
                                      └──────────────────┘
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.10+, Flask 3, Flask-SocketIO |
| Database | SQL Server 2019+ (pyodbc) |
| Frontend | Vanilla JS, Chart.js 4, Socket.IO client |
| Styling | Custom CSS (dark theme, CSS Grid) |
| Real-time | WebSocket via Socket.IO |

## Installation

```bash
git clone https://github.com/jmanu1983/aeos-dashboard.git
cd aeos-dashboard

python -m venv .venv
.venv\Scripts\activate   # Windows

pip install -r requirements.txt
```

## Configuration

```bash
cp .env.example .env
```

Edit `.env` with your SQL Server connection details:

```ini
DB_SERVER=your-sql-server
DB_NAME=aeosdb
DB_USER=your_user
DB_PASSWORD=your_password
```

## Usage

```bash
python app.py
```

Open http://localhost:5000 in your browser.

### REST API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check + DB status |
| `/api/events/recent?limit=50&hours=1` | GET | Recent access events |
| `/api/doors/status` | GET | All door statuses |
| `/api/analytics/hourly?date=2026-02-10` | GET | Hourly traffic breakdown |
| `/api/analytics/top-access-points?limit=10` | GET | Busiest access points |
| `/api/alerts?limit=20&hours=24` | GET | Security alerts |

### WebSocket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `new_events` | Server → Client | New access events (pushed every 5s) |
| `status` | Server → Client | Connection confirmation |

## Project Structure

```
aeos-dashboard/
├── app.py                  # Flask + SocketIO backend
├── templates/
│   └── dashboard.html      # Main dashboard page
├── static/
│   ├── style.css           # Dark theme styling
│   └── dashboard.js        # Client-side logic + charts
├── .env.example            # Configuration template
├── requirements.txt        # Python dependencies
└── README.md
```

## SQL Server Requirements

The dashboard reads from standard AEOS database tables:
- `dbo.Event` — Access events
- `dbo.Person` — Person records
- `dbo.Carrier` — Badge/carrier records
- `dbo.AccessPoint` — Door/reader configuration

> Requires read-only access to the AEOS database. No writes are performed.

## License

This project is licensed under the MIT License.
