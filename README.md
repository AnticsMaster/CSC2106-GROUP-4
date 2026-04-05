# CSC2106 Group 4 — Smart Study Space Occupancy Detection System​

A hierarchical IoT system that tracks real-time classroom occupancy across campus buildings using Raspberry Pi Pico W sensor nodes, a BLE mesh network, an MQTT broker on a Raspberry Pi 4, and a Firebase-backed web dashboard.

---

## Table of Contents

1. [Brief Introduction](#brief-introduction)
2. [Features](#features)
3. [Architecture](#architecture)
4. [MQTT Topic Design](#mqtt-topic-design)
5. [Firestore Data Model](#firestore-data-model)
6. [Setup Instructions](#setup-instructions)
   - [Prerequisites](#prerequisites)
   - [1. Firebase Setup](#1-firebase-setup)
   - [2. Flash Pico W Devices](#2-flash-pico-w-devices)
   - [3. Configure Root Nodes](#3-configure-root-nodes)
   - [4. Run the Bridge](#4-run-the-bridge)
   - [5. Run the Dashboard](#5-run-the-dashboard)
7. [Project Structure](#project-structure)

---

## Brief Introduction

University classrooms are frequently over- or under-utilised because students have no live visibility into room availability. This project solves that with a multi-tier IoT pipeline:

- **Edge nodes** (Pico W) — PIR and ultrasonic sensors detect occupancy per classroom.
- **BLE mesh** — sensor nodes relay data hop-by-hop to a building head node.
- **Head nodes** (Pico W, active-passive pair) — aggregate local data and forward it to the server via MQTT QoS 1.
- **Main Server** (Raspberry Pi 4) — runs a custom MQTT broker and a Python bridge that decrypts payloads and writes records to Firebase Firestore.
- **Web dashboard** — any authorised device can check real-time occupancy, historical trends, and predictive analytics.

Payloads are AES-128-CBC encrypted end-to-end. Automatic failover is handled by MQTT Last Will and Testament (LWT): if the primary head node disconnects, its LWT fires and the backup head node takes over publishing.

---

## Features

### Real-time Occupancy (implemented)

- Live grid of classroom cards showing **occupied / available / offline** state
- Student count per room with configurable `maxOccupancy` threshold
- Device online/offline status via MQTT LWT retained messages
- Summary bar: total / occupied / available / offline counts
- Auto-updates via Firestore `onSnapshot` — no polling required

### Historical Charts & Predictive Analytics

- Click any room card to open a detail modal:
  - Live occupancy area chart (recharts)
  - Historical stats: average, peak, and minimum student counts
- Weighted Moving Average prediction:
  - Trend detection (rising / falling / stable) using window-split comparison
  - Predicted student count extrapolated from recent data
  - Confidence level (low / medium / high) based on data quantity
  - Forecast line rendered on the chart extending beyond "Now"
  - Human-readable summary (e.g., *"Likely busy soon — ~25 students expected"*)

### Per-zone Heatmap

- Each classroom is divided into four zones; the sensor reports a score (0–3) per zone
- Bridge maps scores to labels (`none` / `low` / `medium` / `high`) and stores them alongside occupancy

### Security

- MQTT username/password authentication per building cluster
- Client ID allowlist (`Pi4-HeadNode-E<N>`, `Pi4-BackUp-E<N>`, `bridge`)
- Topic-level ACL: each client restricted to its minimum required namespace
- AES-128-CBC payload encryption with per-message random IV
- Firestore security rules: dashboard clients may only write `maxOccupancy`

---

## Architecture

![System Architecture Diagram](architecture.jpg)

---

## MQTT Topic Design

All occupancy and heatmap payloads are **AES-128-CBC encrypted** (16-byte random IV prepended). Status messages are plaintext so the broker coordinator can read node health without a key.

| Topic | Payload | Direction | Encrypted |
| ----- | ------- | --------- | --------- |
| `csc2106/<node_id>/classroom/<room_id>/occupancy` | `{"room_name", "count", "timestamp"}` | Head Node → Broker | Yes |
| `csc2106/<node_id>/classroom/<room_id>/heatmap` | `{"zones": [0-3, 0-3, 0-3, 0-3], "timestamp"}` | Head Node → Broker | Yes |
| `csc2106/<node_id>/classroom/<room_id>/status` | `"online"` / `"offline"` (retained, LWT) | Head Node → Broker | No |
| `csc2106/<node_id>/status` | `"online"` / `"offline"` (retained, LWT) | Head Node → Broker | No |

**Topic-level ACL:**

| Client | Publish | Subscribe |
| ------ | ------- | --------- |
| `Pi4-HeadNode-E<N>` | `csc2106/HeadNode-E<N>/#` | — |
| `Pi4-BackUp-E<N>` | `csc2106/HeadNode-E<N>/#`, `csc2106/BackUp-E<N>/#` | — |
| `bridge` | — | `csc2106/#` |

Room IDs use the format `E<block>-<level>-<room>` (e.g., `E2-03-01`).

---

## Firestore Data Model

```text
classrooms/<room_id>
  ├── nodeId          string    — head node that last wrote this record
  ├── roomId          string    — matches document ID
  ├── roomName        string    — human-readable label
  ├── occupied        boolean   — true when count > maxOccupancy
  ├── count           number    — current student count
  ├── maxOccupancy    number    — editable threshold (default 30)
  ├── deviceStatus    string    — "online" | "offline"
  ├── lastUpdated     timestamp — Firestore server timestamp
  ├── lastSeen        timestamp — last message received
  ├── picoTimestamp   number    — epoch timestamp from Pico W
  └── heatmap
        ├── zones       number[]  — raw scores per zone [0–3]
        ├── zoneLabels  string[]  — ["none"|"low"|"medium"|"high"]
        ├── lastUpdated timestamp
        └── picoTimestamp number

occupancy_history/<auto-id>         — append-only time-series
  ├── roomId          string
  ├── roomName        string
  ├── occupied        boolean
  ├── count           number
  ├── timestamp       timestamp
  └── picoTimestamp   number

heatmap_history/<auto-id>           — append-only heatmap time-series
  ├── roomId          string
  ├── zones           number[]
  ├── zoneLabels      string[]
  ├── timestamp       timestamp
  └── picoTimestamp   number
```

**Firestore security rules summary:**

- Dashboard clients: read all, write only `maxOccupancy` on `classrooms/*`
- Bridge service account: full read/write (sole ingestion path)

---

## Setup Instructions

### Prerequisites

- 1× Raspberry Pi 4 (MQTT broker + bridge host)
- 2× Raspberry Pi Pico W per building (1 primary head node, 1 backup head node)
- Additional Pico W devices as sensor/edge nodes
- MicroPython firmware flashed on all Pico Ws
- Python 3.9+ on the RPi 4 (for the bridge)
- Node.js 18+ (for the dashboard)
- A Firebase project with Firestore enabled

### 1. Firebase Setup

1. Open the [Firebase Console](https://console.firebase.google.com/) and create or select a project.
2. Enable **Cloud Firestore** (Native mode).
3. Register a **Web app** under Project Settings — copy the config values into `dashboard/.env`.
4. Under Project Settings → Service Accounts, click **Generate New Private Key** and save the JSON file as `bridge/serviceAccountKey.json`.
5. Apply the security rules from the report (dashboard clients read-only; bridge service account full write).

### 2. Flash Pico W Devices

1. Flash MicroPython firmware on all Pico Ws ([official guide](https://micropython.org/download/RPI_PICO_W/)).
2. For **sensor/edge nodes**, upload `sensor_pico.py` as `main.py`.
3. For **head nodes**, upload `rootNodes/root_node_primary.py` (primary) or `rootNodes/root_node_backup.py` (backup) as `main.py`.
4. Copy the appropriate config to each Pico W's flash as `config.json` (see `rootNodes/configs/`).

### 3. Configure Root Nodes

Edit the `config.json` for each head node before uploading:

```json
{
  "wifi_ssid": "YOUR_SSID",
  "wifi_password": "YOUR_PASSWORD",
  "broker_ip": "RPi4_IP_ADDRESS",
  "node_id": "HeadNode-E2",
  "mqtt_pass": "your-node-secret",
  "building_prefix": "2",
  "ENC": "16-byte-hex-enc-key",
  "MAC": "16-byte-hex-mac-key",
  "COMPANY_ID": "0607"
}
```

Pre-built configs for buildings E2, E6, and a new-building template are in [rootNodes/configs/](rootNodes/configs/).

### 4. Run the Bridge

```bash
cd bridge
pip install -r requirements.txt
cp .env.example .env
# Edit .env:
#   MQTT_BROKER_IP=<RPi4 IP address>
#   MQTT_PORT=1883
#   FIREBASE_CREDENTIALS_PATH=serviceAccountKey.json
python mqtt_to_firebase.py
```

The bridge connects to the broker, subscribes to all `csc2106/#` topics, decrypts payloads with AES-128-CBC, and upserts records into Firestore. It retries with a 10-second backoff on disconnection.

### 5. Run the Dashboard

```bash
cd dashboard
npm install
cp .env.example .env
# Edit .env with your Firebase web app config values:
#   VITE_FIREBASE_API_KEY=...
#   VITE_FIREBASE_AUTH_DOMAIN=...
#   VITE_FIREBASE_PROJECT_ID=...
#   VITE_FIREBASE_STORAGE_BUCKET=...
#   VITE_FIREBASE_MESSAGING_SENDER_ID=...
#   VITE_FIREBASE_APP_ID=...
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## Project Structure

```text
CSC2106-GROUP-4/
├── rootNodes/
│   ├── root_node_primary.py     # Primary head node firmware (MicroPython)
│   ├── root_node_backup.py      # Backup head node firmware (MicroPython)
│   └── configs/                 # Per-building config.json files
│       ├── E2_primary_config.json
│       ├── E2_backup_config.json
│       ├── E6_primary_config.json
│       ├── E6_backup_config.json
│       └── NEW_BUILDING_*.json
├── bridge/
│   ├── mqtt_to_firebase.py      # MQTT → Firestore bridge (Python 3)
│   ├── requirements.txt
│   └── .env.example
├── dashboard/
│   ├── src/
│   │   ├── components/          # Navbar, ClassroomCard, ClassroomGrid,
│   │   │                        # OccupancyChart, PredictionBadge, ClassroomDetail
│   │   ├── hooks/               # useClassrooms, useOccupancyHistory
│   │   ├── lib/                 # Firebase init, prediction algorithm
│   │   └── types/               # TypeScript interfaces
│   ├── .env.example
│   ├── index.html
│   └── package.json
├── architecture.jpg             # System architecture diagram
└── README.md
```
