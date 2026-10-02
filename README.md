# 🌐 DisasterMesh

**A multi-agent disaster response coordination system that fuses multi-source crisis signals into verified, prioritized, and dispatched incidents in real time.**

DisasterMesh ingests reports from satellites, social media, citizens, and IoT sensors, deduplicates and verifies them, scores severity, matches available responders, and closes the loop with real-time notifications — all through a pipeline of six coordinated agents.

---

## 📑 Table of contents

- [Project overview](#-project-overview)
- [Architecture](#-architecture)
- [Data flow](#-data-flow)
- [Tech stack](#-tech-stack)
- [Repository layout](#-repository-layout)
- [Data schema](#-data-schema)
- [API reference](#-api-reference)
- [Environment variables](#-environment-variables)
- [Quick start](#-quick-start)
- [Live data ingestion & monitors](#-live-data-ingestion--monitors)
- [Seeding demo data](#-seeding-demo-data)
- [Running a demo scenario](#-running-a-demo-scenario)
- [Testing](#-testing)
- [Deployment](#-deployment)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🧭 Project overview

During a disaster, the hardest problem isn't a lack of information — it's too much of it, arriving unverified, unstructured, and from too many channels at once. Satellite imagery flags a flooded region hours after it started. Citizens send panicked, inconsistent SMS reports. Social media surfaces real signal buried in noise. Responders operate with partial visibility into where they're needed most.

DisasterMesh is built to solve that fusion problem end-to-end:

- **Ingest** everything (satellite polygons, social posts, citizen reports, IoT sensor streams) into one canonical schema
- **Deduplicate and verify** so multiple reports of the same event become one confirmed incident, not duplicates
- **Score severity** using a multi-factor model, so P1 incidents surface before P4s
- **Match and dispatch** responders using constraint-based optimization, not just "nearest available"
- **Close the loop** with real-time status updates to both citizens and responders

The system is designed to work seamlessly both locally (offline vector DB + mock/seeded data) and in production with real external feeds (Exa AI social search, Sentinel-2, Vonage/Twilio SMS, and Groq LLM).

---

## 🏗️ Architecture

DisasterMesh is a six-agent pipeline. Each agent is a modular, independently callable backend component. All agents read/write through a shared vector memory layer (Qdrant) and are orchestrated by a FastAPI backend.

### 1️⃣ Situational Agent — Intake & Fusion
- **Inputs:** satellite polygons, social posts, citizen reports (SMS/WhatsApp/web form), IoT sensor streams
- **Responsibilities:** normalize every inbound message into a canonical incident schema; extract geolocation, timestamp, media links, and source metadata; run LLM structured parsing via Groq
- **Output:** proto-incident objects persisted into Qdrant with an embedding vector + metadata (`source_provenance`)

### 2️⃣ Verification Agent — Dedup & Confidence
- **Inputs:** proto-incidents from the Situational Agent
- **Responsibilities:** deduplicate via spatial/temporal clustering combined with vector similarity for cases where geo-coordinates are noisy or missing; filter stale/noisy reports; cross-source corroboration (e.g., satellite polygon corroborating citizen reports in the same area)
- **Output:** verified incident clusters with `cluster_id`, a confidence score (0–1), and a canonical representative record

### 3️⃣ Victim Agent — Needs & Severity
- **Inputs:** verified incident clusters
- **Responsibilities:** extract needs (medical, shelter, evacuation, rescue, food, water) from report text/media; compute a severity score using a multi-factor model (keyword multipliers, population density, cross-source corroboration bonus, temporal escalation)
- **Output:** priority label (`P1`–`P4`) and a structured needs profile JSON per cluster

### 4️⃣ Resource Agent — Responder State
- **Inputs:** registered responder resources (registry DB or real-time location feed)
- **Responsibilities:** maintain responder capability tags (medical, rescue, water, logistics), inventory, live status, location, and availability windows
- **Output:** a live, queryable resource pool consumed by the Orchestrator

### 5️⃣ Orchestrator Agent — Optimization & Dispatch
- **Inputs:** prioritized incidents, live resource pool, road/traffic ETA estimates
- **Responsibilities:** compute an assignment matrix that minimizes total ETA subject to capability and capacity constraints using **Google OR-Tools SCIP solver** with a greedy heuristic fallback
- **Output:** assignment records, ETA per assignment, route details

### 6️⃣ Communication Agent — Notify & Track
- **Inputs:** lifecycle state changes and assignment results
- **Responsibilities:** send citizen and responder notifications (Vonage / Twilio SMS); generate situational summaries; drive the incident lifecycle state machine
- **Output:** notification logs, callback webhooks, status updates

**Lifecycle state machine:**

```
REPORTED → VERIFIED → ASSIGNED → EN ROUTE → ON SCENE → RESOLVED
```

---

## 🔄 Data flow

```
 SATELLITE   SOCIAL (Exa)   CITIZEN (SMS/Web)   IoT SENSORS
     │            │                 │                │
     └────────────┼─────────────────┴────────────────┘
                  ▼
          Situational Agent
       (Groq LLM + Embeddings)
                  ▼
          Verification Agent
       (3D Cluster + Dedupe + Verify)
                  ▼
            Victim Agent
       (Needs Profile + Severity P1–P4)
                  ▼
          ┌───────┴────────┐
          ▼                ▼
   Resource Agent   Orchestrator Agent
   (Live Registry)  (OR-Tools SCIP Optimizer)
          └───────┬────────┘
                  ▼
          Communication Agent
       (Vonage SMS + WebSockets /ws/updates)
```

---

## 🛠️ Tech stack

| Layer | Technology | Details |
|---|---|---|
| **Backend** | Python 3.11+, FastAPI (async) | High-performance asynchronous REST API & WebSocket server |
| **Agent Orchestration** | LangGraph StateGraph + LangChain | Multi-agent coordination pipeline and structured LLM tool calling |
| **Vector Memory** | Qdrant | Built-in local file mode (`./qdrant_data`, 100% offline) or Qdrant Cloud |
| **Database** | SQLAlchemy + aiosqlite / PostgreSQL | Async relational persistence for incidents, responders, audit logs |
| **LLM (Intake)** | Groq (`openai/gpt-oss-120b` / `qwen/qwen3.8-27b`) | Sub-second structured extraction of incident type, coordinates, urgency & needs |
| **Social / Web Monitoring** | Exa AI Neural Search API | Real-time web-wide search for disaster alerts across Twitter/X, Reddit, news |
| **SMS Notifications** | Vonage SMS (or Twilio) | Automated dispatch and status alerts to responders and citizens |
| **Optimization** | Google OR-Tools (SCIP Solver) | Constraint-based optimization minimizing ETA while matching team capabilities |
| **Realtime Updates** | WebSocket (`/ws/updates`) | Push lifecycle transitions and new incidents directly to dashboards |
| **TUI Dashboard** | Textual | Interactive terminal dashboard with keyboard navigation and instant dispatch |
| **Web Frontend** | Next.js 14+ (App Router), TypeScript, Tailwind CSS | Tactical operations dashboard with live incident feeds and dispatch controls |
| **Mapping Engine** | MapLibre GL | Zero-token global map with Dark Tactical Basemap and Esri Satellite switcher |

---

## 📁 Repository layout

```
disastermesh/
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI entrypoint & lifecycle management
│   │   ├── config.py              # Pydantic settings (.env & .env.local loader)
│   │   ├── db.py                  # Qdrant + SQLAlchemy + Redis client factories
│   │   ├── models.py              # SQLAlchemy ORM models
│   │   ├── schemas.py             # Canonical incident and dispatch schemas
│   │   ├── incident_utils.py      # Incident dictionary normalization helpers
│   │   ├── agents/
│   │   │   ├── situational.py     # Agent 1: intake & fusion
│   │   │   ├── verification.py    # Agent 2: spatial/temporal/semantic dedup
│   │   │   ├── victim.py          # Agent 3: needs & severity scoring
│   │   │   ├── resource.py        # Agent 4: responder state & registry
│   │   │   ├── orchestrator.py    # Agent 5: OR-Tools SCIP dispatch optimization
│   │   │   ├── communication.py   # Agent 6: notifications & lifecycle
│   │   │   ├── embeddings.py      # HuggingFace all-MiniLM-L6-v2 embeddings
│   │   │   ├── vector_store.py    # Qdrant vector store operations
│   │   │   ├── intake_parser.py   # Groq LLM smart intake layer
│   │   │   └── intake_queue.py    # Retry queue for failed intakes
│   │   ├── services/
│   │   │   ├── exa_monitor.py     # Exa AI live social media / web monitor
│   │   │   └── twitter_sim.py     # Social media stream simulator
│   │   ├── routers/               # FastAPI route handlers
│   │   │   ├── health.py          # Health check endpoint
│   │   │   ├── ingest.py          # Multi-source ingestion endpoints
│   │   │   ├── incidents.py       # Cluster queries, verification, assessment
│   │   │   ├── dispatch.py        # Single & batch responder optimization
│   │   │   ├── responders.py      # Responder CRUD & GPS tracking
│   │   │   └── communication.py   # Notifications & WebSocket /ws/updates
│   │   ├── tui/                   # Textual terminal dashboard
│   │   │   ├── __init__.py
│   │   │   ├── __main__.py        # python -m app.tui
│   │   │   └── app.py             # TUI application interface
│   │   └── tests/
│   │       ├── unit/              # 170+ isolated unit tests
│   │       └── integration/       # Full pipeline integration tests
│   ├── scripts/
│   │   ├── seed_data.py           # Seed sample incidents & responders
│   │   └── run_demo_scenario.py   # Automated end-to-end scenario runner
│   ├── requirements.txt
│   ├── .env.example
│   └── .env.local                 # Local secret overrides (gitignored)
├── frontend/                      # Next.js 14+ app (App Router)
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx               # Main operational dashboard
│   │   └── globals.css
│   ├── components/
│   │   ├── MapView.tsx            # MapLibre GL map with Dark / Satellite switcher
│   │   ├── IncidentSidebar.tsx    # Incident list + filters
│   │   ├── IncidentCard.tsx       # Incident detail panel + one-click dispatch
│   │   ├── EventFeed.tsx          # Real-time WebSocket event log
│   │   └── StatusSummary.tsx      # Severity & status counters
│   ├── hooks/
│   │   ├── useIncidents.ts        # SWR polling hook
│   │   └── useWebSocket.ts        # Real-time WebSocket event hook
│   ├── lib/
│   │   └── api.ts                 # Typed API client
│   └── package.json
└── demo_data/
    ├── citizen_reports/           # Sample SMS-style reports (Hindi/English)
    ├── social_posts/              # Sample social posts
    ├── satellite/                 # Sample Sentinel-2 flood polygons
    └── responder_registry.json    # Sample responder teams
```

---

## 📦 Data schema

### Canonical incident record (Qdrant `proto_incidents` collection)

```json
{
  "vector": [0.021, -0.045, "... 384 dimensions"],
  "payload": {
    "cluster_id": "cluster_a1b2c3d4",
    "source_provenance": ["sms", "social", "sentinel"],
    "lat": 27.7172,
    "lon": 85.3240,
    "timestamp": "2026-10-02T10:15:00Z",
    "confidence": 0.92,
    "severity": "P1",
    "needs": {
      "medical": true,
      "rescue": true,
      "water": true,
      "shelter": false,
      "evacuation": true,
      "food": false
    },
    "status": "VERIFIED"
  }
}
```

---

## 🔌 API reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check (environment, status, version) |
| `POST` | `/ingest/report` | Ingest citizen report (supports Groq LLM structured parsing) |
| `POST` | `/ingest/social` | Ingest social media / news post |
| `POST` | `/ingest/satellite` | Ingest Sentinel-2 GeoJSON flood polygon |
| `POST` | `/ingest/sensor` | Ingest IoT water level or seismic sensor reading |
| `GET` | `/incidents/?lat=&lon=&radius=&limit=` | Geo query for nearby incidents |
| `GET` | `/incidents/{proto_id}` | Fetch a single proto-incident by ID |
| `GET` | `/incidents/search/semantic?q=&limit=` | Semantic similarity search across incidents |
| `POST` | `/incidents/verify` | Run VerificationAgent on an incident |
| `POST` | `/incidents/{cluster_id}/assess` | Run VictimAgent severity assessment |
| `POST` | `/incidents/{cluster_id}/status` | Transition incident lifecycle state |
| `GET` | `/incidents/{cluster_id}/summary` | Fetch AI situational summary |
| `POST` | `/dispatch/{cluster_id}` | Dispatch responders via OR-Tools optimization |
| `POST` | `/dispatch/optimize` | Batch dispatch across multiple incident clusters |
| `GET` | `/responders` | List all responders (filter by status) |
| `POST` | `/responders` | Register a new responder team |
| `GET` | `/responders/{id}` | Get responder details |
| `PUT` | `/responders/{id}/location` | Update responder GPS location |
| `PUT` | `/responders/{id}/status` | Update responder operational status |
| `GET` | `/communications/logs` | Communication audit log |
| `WS` | `/ws/updates` | Real-time WebSocket event stream |

---

## 🔐 Environment variables

Configure `backend/.env.local` (or `backend/.env`):

```env
# ── Groq LLM (Required for live AI report parsing) ────────────────────────────
# Sign up: https://console.groq.com
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
GROQ_TIMEOUT_S=10

# ── Qdrant Vector DB ─────────────────────────────────────────────────────────
# Leave blank to use built-in local file mode (./qdrant_data, zero setup required).
# Set to Qdrant Cloud URL for production: https://xxxx.qdrant.io
QDRANT_URL=
QDRANT_API_KEY=
QDRANT_LOCAL_PATH=./qdrant_data

# ── Database ──────────────────────────────────────────────────────────────────
# SQLite for dev, postgresql+asyncpg:// for production
DATABASE_URL=sqlite+aiosqlite:///./dev.db

# ── SMS Provider ────────────────────────────────────────────────────────────
# Vonage (recommended — free tier: 200 SMS/month)
VONAGE_API_KEY=your_vonage_key
VONAGE_API_SECRET=your_vonage_secret
VONAGE_FROM_NUMBER=DisasterMesh

# ── Exa Social Media Monitor ─────────────────────────────────────────────────
# Sign up: https://exa.ai
EXA_API_KEY=your_exa_api_key

# ── App ───────────────────────────────────────────────────────────────────────
APP_ENV=development
LOG_LEVEL=INFO
```

---

## ⚡ Quick start

### 1. Start the backend API server

```bash
cd backend
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Start backend server
uvicorn app.main:app --reload --port 8000
```
- **API Server:** `http://localhost:8000`
- **Interactive Swagger Docs:** `http://localhost:8000/docs`

### 2. Launch the Terminal UI (TUI)

In a separate terminal tab:

```bash
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.tui
```

**TUI Keyboard Shortcuts:**
- `↑` / `↓` : Navigate incidents table & view details
- `d` : Dispatch responders to selected incident
- `r` : Refresh incident data
- `s` : View summary stats
- `q` : Quit

### 3. Launch the web frontend

In a third terminal tab:

```bash
cd frontend
npm install
npm run dev
```

Open **`http://localhost:3000`** in your browser.
- Interactive map powered by **MapLibre GL**
- Toggle between **🌙 Dark Tactical Map** and **🛰️ Satellite View**
- Live incident cards, priority badges, and one-click dispatch

---

## 📡 Live data ingestion & monitors

### 1. Run live social media & web search (Exa AI)
Fetch real disaster and flood reports from across Twitter/X, Reddit, and news articles:

```bash
cd backend
.\.venv\Scripts\Activate.ps1

# Run a one-shot live search
python -m app.services.exa_monitor

# Or run continuous monitoring (polls every 60 seconds)
python -m app.services.exa_monitor --continuous
```

### 2. Submit a live report via API
```bash
curl -X POST http://localhost:8000/ingest/report \
  -H "Content-Type: application/json" \
  -d '{
    "source": "sms",
    "text": "Severe flood in Patan near Krishna Mandir, 4 feet water, 6 people trapped on rooftop, need rescue boat!",
    "lat": 27.6744,
    "lon": 85.3250
  }'
```

---

## 🌱 Seeding demo data

To pre-load demo data and test the offline scenario:

```bash
cd backend
.\.venv\Scripts\Activate.ps1
python -m scripts.seed_data
```

---

## ▶️ Running a demo scenario

To execute an automated end-to-end disaster scenario simulation:

```bash
cd backend
.\.venv\Scripts\Activate.ps1
python -m scripts.run_demo_scenario
```

---

## ✅ Testing

```bash
# Run backend test suite (170+ unit tests)
cd backend
pytest app/tests/unit -v

# Run frontend build & type check
cd frontend
npm run build
```

---

## 🚀 Deployment

| Component | Local dev | Production |
|---|---|---|
| **Backend** | `uvicorn` with `--reload` | Docker / Render / Fly.io / AWS ECS |
| **Terminal UI** | `python -m app.tui` | Terminal / SSH |
| **Web Frontend** | `npm run dev` | Vercel / Cloudflare Pages |
| **Vector DB** | Local `./qdrant_data` (embedded) | Qdrant Cloud Cluster |
| **Database** | SQLite (`dev.db`) | Managed PostgreSQL (Supabase / AWS RDS) |

---

## 🗺️ Roadmap

- [x] Textual TUI dashboard with live incident monitoring & keyboard dispatch
- [x] Next.js + MapLibre GL frontend with Dark / Satellite modes
- [x] Groq LLM structured intake layer for crisis reports
- [x] Exa AI neural search live web & social monitor
- [x] OR-Tools SCIP constraint optimizer for responder dispatch
- [x] Real-time WebSocket event broadcasting (`/ws/updates`)
- [x] Multi-source verification & confidence scoring
- [ ] WhatsApp Business API integration for two-way citizen alerts
- [ ] Real-time Sentinel-2 polygon streaming
- [ ] Multi-language voice note transcription via Whisper

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

MIT — see [`LICENSE`](LICENSE) for details.