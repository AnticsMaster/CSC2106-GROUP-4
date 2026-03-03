# Classroom Availability Tracker Dashboard

A React web app that displays real-time classroom availability status,
powered by Raspberry Pi Pico W devices communicating over MQTT.

> **Note:** The student-tracking sensor hardware is not yet implemented.
> The Pico W devices currently publish **simulated** occupancy data
> via a random-walk algorithm to demonstrate the full data pipeline.

## Architecture

```
┌──────────────┐     ┌──────────────┐
│  Pico W (A)  │     │  Pico W (B)  │
│  Simulates   │     │  Simulates   │
│  Room 2.1    │     │  Room 2.2    │
└──────┬───────┘     └──────┬───────┘
       │   MQTT pub          │   MQTT pub
       └────────┐   ┌───────┘
                ▼   ▼
         ┌──────────────┐
         │ Pico W Broker│  (mesh/server.py — custom MQTT 3.1.1 broker)
         │  port 1883   │
         └──────┬───────┘
                │  MQTT sub
                ▼
         ┌──────────────┐
         │ Bridge Script│  (Python 3 on PC — bridge/mqtt_to_firebase.py)
         │  paho-mqtt → │──► Firebase Firestore
         │  firebase SDK│
         └──────────────┘
                         ◄── real-time reads via onSnapshot
                ┌──────────────┐
                │ React + Vite │  (dashboard/)
                │  Dashboard   │
                │  Tailwind CSS│
                └──────────────┘
```

## MQTT Topic Design

| Topic | Payload | Direction |
|-------|---------|-----------|
| `csc2106/classroom/<room_id>/occupancy` | `{"room_id", "room_name", "occupied", "count", "timestamp"}` | Pico → Broker |
| `csc2106/classroom/<room_id>/status` | `"online"` / `"offline"` (retained, LWT) | Pico → Broker |

Room IDs: `room-A`, `room-B` (one per Pico W).

## Firestore Data Model

```
classrooms/<room_id>          — current state (upserted on each message)
  roomId, roomName, occupied, count, lastUpdated, deviceStatus, picoTimestamp

occupancy_history/<auto-id>   — append-only time-series
  roomId, roomName, occupied, count, timestamp, picoTimestamp
```

## Project Structure

```
CSC2106-GROUP-4/
├── mesh/                    # BLE mesh networking (lab code, unchanged)
│   ├── picoA.py
│   ├── picoB.py
│   └── server.py            # Custom MQTT broker on Pico W
├── mqtt/                    # Pico W MQTT clients (simulated occupancy)
│   ├── picoA.py             # Publishes room-A data every 15s
│   └── picoB.py             # Publishes room-B data every 15s
├── bridge/                  # MQTT → Firestore bridge (runs on PC)
│   ├── mqtt_to_firebase.py
│   ├── requirements.txt
│   └── .env.example
├── dashboard/               # React web dashboard
│   ├── src/
│   │   ├── components/      # Navbar, StatusBadge, ClassroomCard, ClassroomGrid,
│   │   │                    # OccupancyChart, PredictionBadge, ClassroomDetail
│   │   ├── hooks/           # useClassrooms, useOccupancyHistory (Firestore listeners)
│   │   ├── lib/             # Firebase init, prediction algorithm
│   │   ├── types/           # TypeScript interfaces
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── .env.example
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
└── IMPLEMENTATION.md        # This file
```

## Setup Instructions

### Prerequisites

- 3x Raspberry Pi Pico W (one broker + two clients)
- MicroPython flashed on all Pico Ws
- Python 3.9+ on your PC
- Node.js 18+ on your PC
- A Firebase project with Firestore enabled

### 1. Firebase Setup

1. Go to [Firebase Console](https://console.firebase.google.com/) and create a project (or use existing)
2. Enable **Cloud Firestore** (start in test mode for development)
3. Register a **Web app** under Project Settings — copy the config values
4. Generate a **Service Account key** (Project Settings → Service Accounts → Generate New Private Key)
5. Save the JSON key file — you'll need it for the bridge script

### 2. Flash Pico W Devices

1. Flash MicroPython firmware on all three Pico Ws
2. Upload `mesh/server.py` to the broker Pico W as `main.py`
   - Edit `WIFI_SSID` and `WIFI_PASSWORD` to match your network
   - Note the broker's IP address from serial output
3. Upload `mqtt/picoA.py` to Pico A as `main.py`
   - Edit `WIFI_SSID`, `WIFI_PASSWORD`, and `BROKER_IP` to match your setup
4. Upload `mqtt/picoB.py` to Pico B as `main.py`
   - Edit `WIFI_SSID`, `WIFI_PASSWORD`, and `BROKER_IP` to match your setup

### 3. Run the Bridge Script

```bash
cd bridge
pip install -r requirements.txt
cp .env.example .env
# Edit .env:
#   MQTT_BROKER_IP=<broker pico IP>
#   FIREBASE_CREDENTIALS_PATH=<path to service account JSON>
python mqtt_to_firebase.py
```

### 4. Run the Dashboard

```bash
cd dashboard
npm install
cp .env.example .env
# Edit .env with your Firebase web app config values
npm run dev
```

Open http://localhost:5173 in your browser.

## Features

### Classroom Availability Status (v1 — implemented)
- Real-time grid of classroom cards showing occupied/available/offline state
- Student count per room
- Device online/offline status via MQTT Last Will and Testament
- Summary bar with total/occupied/available/offline counts
- Auto-updates via Firestore `onSnapshot` real-time listener

### Historical Charts & Predictive Analytics (v2 — implemented)
- **Click any room card** to open a detail modal with:
  - Live occupancy area chart (powered by recharts)
  - Historical stats: average, peak, and minimum student counts
  - Real-time data from the `occupancy_history` Firestore collection
- **Predictive analytics** based on weighted moving average:
  - Trend detection (rising / falling / stable) using window-split comparison
  - Predicted student count extrapolated from recent data
  - Confidence level (low / medium / high) based on data quantity
  - Forecast line rendered on the chart extending beyond "Now"
  - Human-readable prediction summary (e.g., "Likely busy soon — ~25 students expected")
- **Algorithm:** `dashboard/src/lib/prediction.ts`
  - Weighted Moving Average — newer data points carry more weight
  - Trend = comparison of avg(first third) vs avg(last third) of a 30-point window
  - Forecast = linear interpolation from current count toward predicted count over 8 steps

### Sensor Integration (planned)
- Replace simulated data with actual sensor hardware (PIR, IR break-beam, ultrasonic, etc.)
- No changes needed to the bridge, Firestore, or dashboard — only the Pico W
  client code needs to be updated to read real sensor values instead of random-walk
