# 🌐 DisasterMesh

**A multi-agent disaster response coordination system that fuses multi-source crisis signals into verified, prioritized, and dispatched incidents in real time.**

DisasterMesh ingests reports from satellites, social media, citizens, and IoT sensors, deduplicates and verifies them, scores severity, matches available responders, and closes the loop with real-time notifications — all through a pipeline of six coordinated agents.

---

## 📑 Table of contents

- [🧭 Project overview](#project-overview)
- [🏗️ Architecture](#architecture)
- [🔄 Data flow](#data-flow)
- [🛠️ Tech stack](#tech-stack)
- [📁 Repository layout](#repository-layout)
- [📦 Data schema](#data-schema)
- [🔌 API reference](#api-reference)
- [🔐 Environment variables](#environment-variables)
- [⚡ Quick start](#quick-start)
- [🌱 Seeding demo data](#seeding-demo-data)
- [▶️ Running a demo scenario](#running-a-demo-scenario)
- [✅ Testing](#testing)
- [🚀 Deployment](#deployment)
- [🗺️ Roadmap](#roadmap)
- [🤝 Contributing](#contributing)
- [📄 License](#license)

---

## 🧭 Project overview

During a disaster, the hardest problem isn't a lack of information — it's too much of it, arriving unverified, unstructured, and from too many channels at once. Satellite imagery flags a flooded region hours after it started. Citizens send panicked, inconsistent SMS reports. Social media surfaces real signal buried in noise. Responders operate with partial visibility into where they're needed most.

DisasterMesh is built to solve that fusion problem end-to-end:

- **Ingest** everything (satellite polygons, social posts, citizen reports, IoT sensor streams) into one canonical schema
- **Deduplicate and verify** so five reports of the same fire become one confirmed incident, not five
- **Score severity** using a multi-factor model, so P1 incidents surface before P4s
- **Match and dispatch** responders using constraint-based optimization, not just "nearest available"
- **Close the loop** with real-time status updates to both citizens and responders

The system is designed to be demoable end-to-end on a laptop using mock data, while being architected in a way that scales to real feeds (Sentinel-2, IMD alerts, Twilio/WhatsApp) with minimal rework.

---

## 🏗️ Architecture

DisasterMesh is a six-agent pipeline. Each agent is a modular, independently callable backend component. All agents read/write through a shared vector memory layer (Qdrant) and are orchestrated by a FastAPI backend.

### 1️⃣ Situational Agent — Intake & Fusion
- **Inputs:** satellite polygons, social posts, citizen reports (SMS/WhatsApp/web form), IoT sensor streams
- **Responsibilities:** normalize every inbound message into a canonical incident schema; extract geolocation, timestamp, media links, and source metadata
- **Output:** proto-incident objects persisted into Qdrant with an embedding vector + metadata (`source_provenance`)

### 2️⃣ Verification Agent — Dedup & Confidence
- **Inputs:** proto-incidents from the Situational Agent
- **Responsibilities:** deduplicate via spatial/temporal clustering (150 m / 30 min window as a default) combined with vector similarity for cases where geo-coordinates are noisy or missing; filter stale/noisy reports; run basic image classification checks on attached media; cross-source corroboration (does a satellite polygon back up the citizen reports in the same area?)
- **Output:** verified incident clusters with `cluster_id`, a confidence score (0–1), and a canonical representative record

### 3️⃣ Victim Agent — Needs & Severity
- **Inputs:** verified incident clusters
- **Responsibilities:** extract needs (medical, shelter, evacuation, rescue) from report text/media; compute a severity score using a multi-factor model — keyword multipliers, population density overlay, multi-source corroboration bonus, satellite-derived area proxy, and temporal escalation (an incident that keeps generating new reports over time gets bumped up)
- **Output:** priority label (`P1`–`P4`) and a structured needs profile JSON per cluster

### 4️⃣ Resource Agent — Responder State
- **Inputs:** registered responder resources (registry DB or real-time location feed)
- **Responsibilities:** maintain responder capability tags (medical, rescue, water, logistics), inventory, live status, location, and availability windows
- **Output:** a live, queryable resource pool consumed by the Orchestrator

### 5️⃣ Orchestrator Agent — Optimization & Dispatch
- **Inputs:** prioritized incidents, live resource pool, road/traffic ETA estimates
- **Responsibilities:** compute an assignment matrix that minimizes total ETA subject to capability and capacity constraints, using **Google OR-Tools**; handle dynamic re-routing when traffic conditions change or a responder times out
- **Output:** assignment records, ETA per assignment, route details

### 6️⃣ Communication Agent — Notify & Track
- **Inputs:** lifecycle state changes and assignment results
- **Responsibilities:** send citizen and responder notifications (SMS/WhatsApp); generate situational summaries; drive the incident lifecycle state machine
- **Output:** notification logs, callback webhooks, status updates

**Lifecycle state machine:**

```
REPORTED → VERIFIED → ASSIGNED → EN ROUTE → ON SCENE → RESOLVED
```

---

## 🔄 Data flow

```
 SATELLITE   SOCIAL   CITIZEN   IoT
     │          │        │       │
     └────────┬─┴────────┴───────┘
              ▼
      Situational Agent
     (normalize + embed)
              ▼
      Verification Agent
     (cluster + dedupe + verify)
              ▼
       Victim Agent
   (needs extraction + severity)
              ▼
      ┌───────┴────────┐
      ▼                ▼
Resource Agent   Orchestrator Agent
(live state)    (optimize + assign)
      └───────┬────────┘
              ▼
      Communication Agent
      (notify + lifecycle)
```

---

## 🛠️ Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI (async) |
| Agent orchestration | LangGraph StateGraph + function-call pipeline |
| Vector memory | Qdrant — local file mode via `qdrant-client` (`path=`), Qdrant Cloud for production |
| Cache / task queue | Redis — [Upstash](https://upstash.com) free tier (local + production), or [Redis Cloud](https://redis.io/cloud) |
| LLM | Groq (llama-3.3-70b) for smart intake parsing; fallback to keyword extraction |
| Satellite data | Pre-downloaded Sentinel-2 GeoJSONs + NASA FIRMS REST for thermal alerts |
| Geocoding | OpenStreetMap / Nominatim + local landmark lookup table for Hindi transliterations |
| Optimization | Google OR-Tools SCIP (Python) |
| Realtime | WebSocket (`/ws/updates`) for lifecycle event broadcasting |
| Messaging | Twilio SMS (demo), WhatsApp Business API (optional) |
| Image hosting | Cloudinary or S3 |
| TUI Dashboard | [Textual](https://textual.textualize.io/) — terminal-based live incident monitor |
| Web Frontend | Next.js 14+ (App Router) + Mapbox GL JS + SWR |

---

## 📁 Repository layout

```
disastermesh/
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI entrypoint
│   │   ├── config.py              # Pydantic settings (env vars)
│   │   ├── db.py                  # Qdrant + SQLAlchemy + Redis clients
│   │   ├── models.py              # ORM models (raw ingestion, audit, responders, dispatch, comms)
│   │   ├── schemas.py             # Pydantic models — canonical incident schema
│   │   ├── agents/
│   │   │   ├── situational.py     # Agent 1: intake & fusion
│   │   │   ├── verification.py    # Agent 2: dedup & confidence (3D clustering)
│   │   │   ├── victim.py          # Agent 3: needs & severity scoring
│   │   │   ├── resource.py        # Agent 4: responder state
│   │   │   ├── orchestrator.py    # Agent 5: OR-Tools dispatch (LangGraph)
│   │   │   ├── communication.py   # Agent 6: notifications & lifecycle
│   │   │   ├── embeddings.py      # HuggingFace + LangChain embeddings
│   │   │   ├── vector_store.py    # Qdrant vector store operations
│   │   │   ├── intake_parser.py   # Groq LLM smart intake layer
│   │   │   └── intake_queue.py    # Redis retry queue for failed parses
│   │   ├── routers/               # FastAPI route handlers
│   │   │   ├── health.py
│   │   │   ├── ingest.py
│   │   │   ├── incidents.py
│   │   │   ├── dispatch.py
│   │   │   ├── responders.py
│   │   │   └── communication.py   # REST + WebSocket /ws/updates
│   │   ├── tui/                   # Textual terminal dashboard
│   │   │   ├── __init__.py
│   │   │   ├── __main__.py        # python -m app.tui
│   │   │   └── app.py             # TUI application
│   │   └── tests/
│   │       ├── unit/              # 16 unit test files
│   │       └── integration/       # 7 integration test files
│   ├── scripts/
│   │   ├── seed_data.py
│   │   └── run_demo_scenario.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/                      # Next.js 14+ app (App Router)
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx               # Main dashboard (map + sidebar + events)
│   │   └── globals.css
│   ├── components/
│   │   ├── MapView.tsx            # Mapbox GL JS map
│   │   ├── IncidentSidebar.tsx    # Incident list + detail panel
│   │   ├── IncidentCard.tsx       # Selected incident detail + dispatch
│   │   ├── EventFeed.tsx          # Real-time WebSocket event stream
│   │   └── StatusSummary.tsx      # Top bar with severity counts
│   ├── hooks/
│   │   ├── useIncidents.ts        # SWR polling hook
│   │   └── useWebSocket.ts        # WebSocket connection hook
│   ├── lib/
│   │   └── api.ts                 # Typed API client
│   ├── package.json
│   └── .env.local.example
└── demo_data/
    ├── citizen_reports/           # 20–30 mock SMS-style JSON messages (Hindi/English)
    ├── social_posts/              # 15–20 mock tweets/news items
    ├── satellite/                 # 3–5 Sentinel-2 flood GeoJSON polygons
    └── responder_registry.json    # 5–8 responder teams with capabilities
```

---

## 📦 Data schema

### Canonical incident record (Qdrant `incidents` collection)

```json
{
  "vector": "[float, float, ...]",
  "payload": {
    "cluster_id": "string",
    "source_provenance": ["sms", "sentinel", "tweet"],
    "lat": 28.6139,
    "lon": 77.2090,
    "timestamp": "2026-08-07T09:15:00Z",
    "confidence": 0.87,
    "severity": "P1",
    "needs": {
      "medical": true,
      "shelter": false,
      "evacuation": true,
      "rescue": true
    },
    "media_urls": ["https://..."]
  }
}
```

**Indexing & retrieval patterns:**
- Nearest incidents by vector similarity (semantic search across differently-worded reports of the same event)
- Geo-filtered nearest incidents by radius (150 m default for dedupe clustering)
- Time-window filtering (e.g., last 6 hours)

> **Note on geo queries:** Prefer Qdrant's native geo filtering where available. If your Qdrant version has limited geo support, fall back to storing `lat`/`lon` in the payload and running a server-side Haversine filter — this is fine for demo-scale datasets (hundreds to low thousands of incidents).

---

## 🔌 API reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check (environment, version) |
| `POST` | `/ingest/report` | Accept a citizen report (SMS/text/form). Supports Groq LLM smart intake. |
| `POST` | `/ingest/social` | Accept a social media post (tweet, news) |
| `POST` | `/ingest/satellite` | Accept a GeoJSON polygon from Sentinel-2 |
| `POST` | `/ingest/sensor` | Accept an IoT sensor reading |
| `GET` | `/incidents/?lat=&lon=&radius=&limit=` | Geo query for nearby proto-incidents |
| `GET` | `/incidents/{proto_id}` | Fetch a single proto-incident by ID |
| `GET` | `/incidents/search/semantic?q=&limit=` | Semantic search across incidents |
| `POST` | `/incidents/verify` | Run VerificationAgent on a ProtoIncident |
| `POST` | `/incidents/{proto_id}/verify` | Verify an ingested report by ID |
| `POST` | `/incidents/{cluster_id}/assess` | Run VictimAgent severity scoring |
| `POST` | `/incidents/{cluster_id}/status` | Transition incident lifecycle state |
| `GET` | `/incidents/{cluster_id}/summary` | Fetch situational summary |
| `POST` | `/dispatch/{cluster_id}` | Dispatch responders via OR-Tools + LangGraph |
| `POST` | `/dispatch/optimize` | Batch dispatch across multiple incidents |
| `GET` | `/responders` | List responders (filter by status) |
| `POST` | `/responders` | Register a new responder team |
| `GET` | `/responders/{id}` | Get a single responder |
| `PUT` | `/responders/{id}/location` | Update responder GPS location |
| `PUT` | `/responders/{id}/status` | Update responder operational status |
| `GET` | `/communications/logs` | Paginated communication audit log |
| `WS` | `/ws/updates` | Real-time lifecycle transition events |

**Example: submitting a citizen report**

```bash
curl -X POST http://localhost:8000/ingest/report \
  -H "Content-Type: application/json" \
  -d '{
    "source": "sms",
    "text": "Water rising fast near Yamuna Bazar, need boats",
    "lat": 28.6667,
    "lon": 77.2333,
    "timestamp": "2026-08-07T09:10:00Z",
    "media_urls": []
  }'
```

Full request/response schemas live in `backend/app/schemas.py`.

---

## 🔐 Environment variables

Create a `.env` file in `backend/` with:

```env
# ── Qdrant ────────────────────────────────────────────────────────────
# Leave blank to use local file mode (path="./qdrant_data") — no Docker needed.
# Set to your Qdrant Cloud URL for production.
QDRANT_URL=
QDRANT_API_KEY=
QDRANT_LOCAL_PATH=./qdrant_data   # used only when QDRANT_URL is empty

# ── Database ──────────────────────────────────────────────────────────
DATABASE_URL=sqlite:///./dev.db

# ── Frontend / Maps ───────────────────────────────────────────────────
MAPBOX_TOKEN=

# ── Messaging (optional for demo) ─────────────────────────────────────
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=

# ── Data paths ────────────────────────────────────────────────────────
SENTINEL_DATA_DIR=./demo_data/satellite
S3_BUCKET=

# ── Groq LLM (Smart Intake Layer — Phase 4.5) ─────────────────────────
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_TIMEOUT_S=10

# ── Optimization ──────────────────────────────────────────────────────
ORTOOLS_SCALAR_WEIGHTS=
```

**Qdrant connection logic** — add this helper to `backend/app/db.py`:

```python
import os
from qdrant_client import QdrantClient

def get_qdrant_client() -> QdrantClient:
    url = os.getenv("QDRANT_URL", "").strip()
    if url:
        # Qdrant Cloud
        return QdrantClient(url=url, api_key=os.getenv("QDRANT_API_KEY"))
    # Local file mode — data persists in ./qdrant_data
    path = os.getenv("QDRANT_LOCAL_PATH", "./qdrant_data")
    return QdrantClient(path=path)
```

For a demo, `DATABASE_URL` can stay on SQLite. Switch to Postgres for anything beyond local testing — you'll want relational queries over incident/responder history that Qdrant alone won't give you cleanly.

---

## ⚡ Quick start

### 1. Start the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # edit if needed — defaults work for local demo
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000/docs** to see the interactive API docs.

### 2. Launch the TUI dashboard (terminal)

In a second terminal:

```bash
cd backend
python -m app.tui
```

Key bindings: `r` refresh · `d` dispatch · `s` summary · `q` quit · `↑↓` navigate.

### 3. Launch the web frontend (browser)

In a third terminal:

```bash
cd frontend
npm install
cp .env.local.example .env.local   # add your Mapbox token
npm run dev
```

Open **http://localhost:3000**. The map centers on Delhi NCR. Get a free Mapbox token at [mapbox.com](https://account.mapbox.com/access-tokens/).

---

## 🌱 Seeding demo data

`backend/scripts/seed_data.py` should:
1. Create the Qdrant `incidents` collection with the schema above
2. Load demo GeoJSON polygons into it
3. Push mock SMS/tweet JSON through the ingestion pipeline (or directly into Qdrant, if you want to skip agent processing for a quick smoke test)
4. Create responder registry entries in the local DB

Recommended demo dataset sizes (small enough to reason about, large enough to show dedup working):
- 20–30 mock citizen reports (mix of Hindi/English)
- 3–5 satellite flood polygons
- 15–20 mock social posts
- 5–8 responder teams with distinct capability tags

---

## ▶️ Running a demo scenario

A good end-to-end demo flow:

1. Seed the data (above)
2. POST 4–5 citizen reports describing the *same* flooding event with slightly different wording/locations — this is what shows off the Verification Agent's dedup
3. Watch `/ws/updates` or the frontend map as the cluster forms, gets a confidence score, and is assigned a severity label
4. Call `/dispatch/{cluster_id}` (or let the Orchestrator auto-assign) and confirm a responder gets matched with a computed ETA
5. Confirm a notification log appears in the Communication Agent's output and the lifecycle state advances

---

## ✅ Testing

```bash
# Backend tests
cd backend
pytest -q

# Frontend typecheck
cd frontend
npx tsc --noEmit
```

- **Unit tests** (16 files): `backend/app/tests/unit/` — test each agent's logic in isolation with mocked inputs
- **Integration tests** (7 files): `backend/app/tests/integration/` — run against a small seeded Qdrant instance to validate the full pipeline

---

## 🚀 Deployment

| Component | Local dev | Production |
|---|---|---|
| Backend | `uvicorn` with `--reload` | Render / Fly.io |
| TUI Dashboard | `python -m app.tui` (terminal) | — |
| Web Frontend | `npm run dev` | Vercel |
| Qdrant | Local file mode (`path=`) | Qdrant Cloud |
| Redis | [Upstash](https://upstash.com) free tier | [Upstash](https://upstash.com) or [Redis Cloud](https://redis.io/cloud) |

Use environment variables to cleanly separate demo mode (mock data, no real SMS sending) from production mode (real Twilio/WhatsApp, real satellite feeds).

---

## 💡 Operational notes

- For live demos, pre-compute satellite flood polygons ahead of time and present them as "real-time" — don't rely on on-the-fly Sentinel downloads during a presentation.
- Maintain a geocoding fallback lookup table of known landmarks to avoid Hindi transliteration failures with Nominatim.
- Start the Orchestrator with a simple OR-Tools objective (minimize total travel time/distance) before layering in multi-objective constraints like capability matching or capacity limits — it's much easier to debug incrementally.

---

## 🗺️ Roadmap

- [x] Textual TUI dashboard — terminal-based live incident monitoring
- [x] Next.js + Mapbox GL JS web frontend
- [x] WebSocket real-time event broadcasting (`/ws/updates`)
- [x] LangGraph StateGraph for dispatch pipeline
- [x] Groq LLM smart intake layer (bilingual)
- [x] OR-Tools SCIP optimization with heuristic fallback
- [ ] Real-time Sentinel-2 ingestion (beyond pre-downloaded polygons)
- [ ] Multi-objective OR-Tools model (ETA + capability + capacity + fairness)
- [ ] WhatsApp Business API integration for two-way citizen communication
- [ ] Admin dashboard for manual override of agent decisions
- [ ] Multi-language support beyond Hindi/English

---

## 🤝 Contributing

Contributions are welcome:
1. Fork the repo
2. Create a feature branch
3. Add tests for new functionality
4. Submit a PR with a clear description and, where relevant, screenshots

---

## 📄 License

MIT — see `LICENSE` at the repo root.

## 🙏 Acknowledgements

DisasterMesh is an engineering reference for multi-source disaster detection and coordination. Keep demo data and any production data ethically sourced and privacy-aware — especially where citizen reports include location and personal details.