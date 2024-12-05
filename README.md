# AEOS Dashboard temps réel

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0+-green?logo=flask)
![SQL Server](https://img.shields.io/badge/SQL%20Server-2019+-CC2927?logo=microsoftsqlserver&logoColor=white)
![WebSocket](https://img.shields.io/badge/WebSocket-SocketIO-black?logo=socketdotio)
![License](https://img.shields.io/badge/License-MIT-yellow)

**Dashboard de supervision temps réel** pour le système de contrôle d'accès Nedap AEOS. Fournit une visibilité en direct sur les événements d'accès, l'état des portes, les statistiques de trafic et les alertes de sécurité — le tout alimenté par des requêtes SQL Server et du push WebSocket.

## Fonctionnalités

- **Flux d'événements en direct** — Événements d'accès poussés en temps réel via WebSocket (Socket.IO)
- **Monitoring des portes** — État en ligne/hors ligne/alarme de tous les points d'accès
- **Statistiques de trafic horaire** — Graphique empilé accès accordés vs refusés
- **Classement des points d'accès** — Portes les plus fréquentées sur 24h
- **Alertes de sécurité** — Tailgating, portes forcées, maintenues ouvertes, accès refusés
- **Cartes KPI** — Métriques en un coup d'oeil (événements du jour, refusés, portes en ligne, alertes)
- **API REST** — Toutes les données disponibles en JSON pour intégration tierce
- **Interface moderne sombre** — Layout responsive CSS Grid, visualisations Chart.js

## Architecture

```
┌──────────────┐     Requêtes SQL    ┌──────────────────┐
│  SQL Server  │ ◄──────────────────► │  Backend Flask   │
│  (aeosdb)    │                      │  + SocketIO      │
└──────────────┘                      └────────┬─────────┘
                                               │
                                     WebSocket │ API REST
                                               │
                                      ┌────────▼─────────┐
                                      │  Client navigateur│
                                      │  Chart.js + Live  │
                                      └──────────────────┘
```

## Stack technique

| Composant | Technologie |
|-----------|------------|
| Backend | Python 3.10+, Flask 3, Flask-SocketIO |
| Base de données | SQL Server 2019+ (pyodbc) |
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

Modifier `.env` avec vos paramètres de connexion SQL Server :

```ini
DB_SERVER=votre-serveur-sql
DB_NAME=aeosdb
DB_USER=votre_utilisateur
DB_PASSWORD=votre_mot_de_passe
```

## Utilisation

```bash
python app.py
```

Ouvrir http://localhost:5000 dans votre navigateur.

### Points d'accès API REST

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/api/health` | GET | Vérification de santé + état de la base |
| `/api/events/recent?limit=50&hours=1` | GET | Événements d'accès récents |
| `/api/doors/status` | GET | État de toutes les portes |
| `/api/analytics/hourly?date=2026-02-10` | GET | Répartition horaire du trafic |
| `/api/analytics/top-access-points?limit=10` | GET | Points d'accès les plus fréquentés |
| `/api/alerts?limit=20&hours=24` | GET | Alertes de sécurité |

### Événements WebSocket

| Événement | Direction | Description |
|-----------|-----------|-------------|
| `new_events` | Serveur → Client | Nouveaux événements d'accès (poussés toutes les 5s) |
| `status` | Serveur → Client | Confirmation de connexion |

## Structure du projet

```
aeos-dashboard/
├── app.py                  # Backend Flask + SocketIO
├── templates/
│   └── dashboard.html      # Page principale du dashboard
├── static/
│   ├── style.css           # Thème sombre
│   └── dashboard.js        # Logique client + graphiques
├── .env.example            # Modèle de configuration
├── requirements.txt        # Dépendances Python
└── README.md
```

## Prérequis SQL Server

Le dashboard lit les tables standard de la base AEOS :
- `dbo.Event` — Événements d'accès
- `dbo.Person` — Fiches personnes
- `dbo.Carrier` — Badges/porteurs
- `dbo.AccessPoint` — Configuration portes/lecteurs

> Nécessite un accès en lecture seule à la base AEOS. Aucune écriture n'est effectuée.

## Licence

Ce projet est sous licence MIT.
