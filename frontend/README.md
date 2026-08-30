# DisasterMesh Frontend

Next.js 14+ dashboard with Mapbox GL JS map for live incident monitoring.

## Setup

```bash
cd frontend

# Install dependencies
npm install

# Copy environment template
cp .env.local.example .env.local
# Edit .env.local and add your Mapbox token

# Start dev server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Features

- **Interactive Mapbox GL JS map** centered on Delhi NCR
- **Incident markers** color-coded by severity (P1–P4)
- **Responder markers** showing live positions
- **Incident sidebar** with detail card, needs, and confidence
- **Dispatch button** triggers OR-Tools solver from the UI
- **Situational summary** view for incident commanders
- **Real-time event feed** via WebSocket (`/ws/updates`)
- **Auto-refresh** incident data every 5 seconds

## Environment Variables

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_MAPBOX_TOKEN` | Mapbox GL JS access token ([get one free](https://account.mapbox.com/access-tokens/)) |
| `NEXT_PUBLIC_API_URL` | Backend API URL (default: `http://localhost:8000`) |
| `NEXT_PUBLIC_WS_URL` | WebSocket URL (default: `ws://localhost:8000/ws/updates`) |
