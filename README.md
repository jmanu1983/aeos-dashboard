# AEOS Dashboard temps réel

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0+-green?logo=flask)
![Zeep](https://img.shields.io/badge/Zeep-SOAP_Client-orange)
![SQL Server](https://img.shields.io/badge/SQL%20Server-2019+-CC2927?logo=microsoftsqlserver&logoColor=white)
![WebSocket](https://img.shields.io/badge/WebSocket-SocketIO-black?logo=socketdotio)
![License](https://img.shields.io/badge/License-MIT-yellow)

**Dashboard de supervision temps réel** pour le système de contrôle d'accès Nedap AEOS. Architecture hybride combinant :
- **SOAP Web Services** (Zeep) pour le flux d'événements en direct (`findEvent`, `findAccessPoint`)
- **SQL Server** (vue `vw_AeosEventLog`) pour les analyses de trafic lourdes
- **WebSocket** (Socket.IO) pour le push temps réel vers les clients

## Fonctionnalités

- **Flux d'événements en direct** — Interrogation SOAP `findEvent` toutes les 5s, push via WebSocket
- **Découverte des points d'accès** — SOAP `findAccessPoint` pour lister tous les lecteurs AEOS
- **Statistiques de trafic horaire** — Graphique empilé "Access granted" vs "Access denied" (SQL analytique)
- **Classement des points d'accès** — `AccesspointName` les plus fréquentés sur 24h
- **Alertes de sécurité** — Détection des EventTypeName : "Door forced open", "Door held open", "Tailgating", "Access denied"
- **Cartes KPI** — Événements du jour, accès refusés, nombre de points d'accès, alertes
- **API REST** — Toutes les données disponibles en JSON pour intégration tierce
- **Interface moderne sombre** — Layout responsive CSS Grid, visualisations Chart.js

## Architecture

```
┌──────────────────────┐
│  AEOS Server         │
│  (Nedap)             │
│                      │
│  ┌────────────────┐  │        SOAP (Zeep)        ┌──────────────────┐
│  │ aeosws WSDL    │◄─┼───────────────────────────►│  Backend Flask   │
│  │ findEvent      │  │                            │  + SocketIO      │
│  │ findAccessPoint│  │                            │                  │
│  └────────────────┘  │                            │  Endpoints:      │
│                      │        SQL (pyodbc)        │  /api/events     │
│  ┌────────────────┐  │        vw_AeosEventLog     │  /api/accesspoints│
│  │ SQL Server     │◄─┼───────────────────────────►│  /api/analytics  │
│  │ (aeosdb)       │  │                            │  /api/alerts     │
│  └────────────────┘  │                            └────────┬─────────┘
└──────────────────────┘                                     │
                                                   WebSocket │ REST
                                                             │
                                                    ┌────────▼─────────┐
                                                    │  Client navigateur│
                                                    │  Chart.js + Live  │
                                                    └──────────────────┘
```

## Modèle de données AEOS

### EventInfo (WSDL `findEvent`)

| Champ | Type | Description |
|-------|------|-------------|
| `Id` | long | Identifiant unique de l'événement |
| `EventTypeId` | long | ID du type d'événement |
| `EventTypeName` | string | Libellé : "Access granted", "Access denied", "Door forced open"… |
| `DateTime` | dateTime | Horodatage de l'événement |
| `HostName` | string | Nom du contrôleur |
| `AccesspointId` | long | ID du point d'accès |
| `AccesspointName` | string | Nom du point d'accès |
| `EntranceId` | long | ID de l'entrée |
| `EntranceName` | string | Nom de l'entrée |
| `CarrierId` | long | ID du porteur/badge |
| `CarrierFullName` | string | Nom complet du porteur |
| `IdentifierId` | long | ID de l'identifiant |
| `Identifier` | string | Numéro de badge |

### AccessPointInfo (WSDL `findAccessPoint`)

| Champ | Type | Description |
|-------|------|-------------|
| `Id` | long | Identifiant du point d'accès |
| `Name` | string | Nom du point d'accès |
| `HostName` | string | Nom du contrôleur hôte |
| `Type` | string | Type de lecteur |
| `Description` | string | Description |
| `EntranceId` | long | ID de l'entrée associée |

## Stack technique

| Composant | Technologie |
|-----------|------------|
| Backend | Python 3.10+, Flask 3, Flask-SocketIO |
| SOAP Client | Zeep (appels `findEvent`, `findAccessPoint` vers aeosws) |
| Base de données | SQL Server 2019+ (pyodbc) — vue `vw_AeosEventLog` |
| Frontend | Vanilla JS, Chart.js 4, Socket.IO client |
| Style | CSS personnalisé (thème sombre, CSS Grid) |
| Temps réel | WebSocket via Socket.IO |

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

Modifier `.env` avec vos paramètres :

```ini
# AEOS SOAP Web Services
AEOS_WSDL_URL=https://votre-serveur-aeos:8443/aeosws?wsdl
AEOS_WS_USER=votre_utilisateur_ws
AEOS_WS_PASSWORD=votre_mot_de_passe_ws

# SQL Server (vue analytique)
DB_SERVER=votre-serveur-sql
DB_NAME=aeosdb
DB_USER=votre_utilisateur_db
DB_PASSWORD=votre_mot_de_passe_db
```

## Prérequis SQL Server

Le dashboard utilise une vue SQL `vw_AeosEventLog` pour les analyses lourdes (trafic horaire, top access points, alertes). Cette vue doit être créée par le DBA pour exposer le journal d'événements AEOS avec des colonnes alignées sur le WSDL :

```sql
CREATE VIEW dbo.vw_AeosEventLog AS
SELECT
    e.Id,
    e.EventTypeId,
    et.Name            AS EventTypeName,
    e.EventDateTime    AS [DateTime],
    e.HostName,
    e.AccesspointId,
    ap.Name            AS AccesspointName,
    e.EntranceId,
    en.Name            AS EntranceName,
    e.IdentifierId,
    i.Code             AS Identifier,
    e.CarrierId,
    e.CarrierFullName
FROM dbo.<table_evenements_interne> e
LEFT JOIN dbo.<table_types_evenements> et ON e.EventTypeId = et.Id
LEFT JOIN dbo.<table_access_points> ap   ON e.AccesspointId = ap.Id
LEFT JOIN dbo.<table_entrances> en       ON e.EntranceId = en.Id
LEFT JOIN dbo.<table_identifiers> i      ON e.IdentifierId = i.Id;
```

> **Note :** Les noms de tables internes AEOS varient selon la version. Consultez votre DBA pour les noms exacts. Accès en lecture seule uniquement — aucune écriture n'est effectuée.

## Utilisation

```bash
python app.py
```

Ouvrir http://localhost:5000 dans votre navigateur.

### Points d'accès API REST

| Endpoint | Méthode | Source | Description |
|----------|---------|--------|-------------|
| `/api/health` | GET | — | Vérification SOAP + SQL |
| `/api/events/recent?limit=50&hours=1` | GET | SOAP `findEvent` | Événements récents |
| `/api/accesspoints` | GET | SOAP `findAccessPoint` | Tous les points d'accès |
| `/api/analytics/hourly?date=2026-02-10` | GET | SQL `vw_AeosEventLog` | Répartition horaire |
| `/api/analytics/top-access-points?limit=10` | GET | SQL `vw_AeosEventLog` | Points d'accès les plus fréquentés |
| `/api/alerts?limit=20&hours=24` | GET | SQL `vw_AeosEventLog` | Alertes de sécurité |

### Événements WebSocket

| Événement | Direction | Description |
|-----------|-----------|-------------|
| `new_events` | Serveur → Client | Nouveaux événements AEOS (SOAP, toutes les 5s) |
| `status` | Serveur → Client | Confirmation de connexion |

## Structure du projet

```
aeos-dashboard/
├── app.py                  # Backend Flask + Zeep SOAP + SocketIO
├── templates/
│   └── dashboard.html      # Page principale du dashboard
├── static/
│   ├── style.css           # Thème sombre
│   └── dashboard.js        # Logique client + graphiques
├── .env.example            # Modèle de configuration
├── requirements.txt        # Dépendances Python
└── README.md
```

## Licence

Ce projet est sous licence MIT.
