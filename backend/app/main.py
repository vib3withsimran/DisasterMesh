"""
DisasterMesh FastAPI application entrypoint.

Run locally:
    cd backend
    uvicorn app.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import get_qdrant_client_sync, init_db
from app.routers import communication, dispatch, health, incidents, ingest, responders

settings = get_settings()

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    logger.info("DisasterMesh API starting — env=%s", settings.app_env)
    await init_db()
    logger.info("Database tables initialised")
    # Phase 2: initialise Qdrant vector store
    from app.agents.vector_store import init_vector_store

    await init_vector_store(get_qdrant_client_sync())
    logger.info("Qdrant vector store ready")

    # Phase 4.5: Background task to process intake queue retries every 30s
    from app.agents.intake_queue import get_intake_queue

    intake_queue = get_intake_queue()

    async def _queue_worker():
        while True:
            try:
                await asyncio.sleep(30)
                await intake_queue.process_pending()
            except asyncio.CancelledError:
                break
            except Exception as err:
                logger.warning("Intake queue background worker error: %s", err)

    worker_task = asyncio.create_task(_queue_worker())

    yield

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    logger.info("DisasterMesh API shutting down")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="DisasterMesh API",
    description=(
        "Multi-agent disaster response coordination system. "
        "Fuses satellite, social, citizen, and IoT signals into "
        "verified, prioritized, and dispatched incidents."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS (Next.js frontend at localhost:3000) ─────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(health.router)
app.include_router(ingest.router, prefix="/ingest", tags=["Ingestion"])
app.include_router(incidents.router, prefix="/incidents", tags=["Incidents"])
app.include_router(dispatch.router, prefix="/dispatch", tags=["Dispatch"])
app.include_router(responders.router, prefix="/responders", tags=["Responders"])
# Phase 6: Communication Agent — no prefix so WS /ws/updates is at root level
app.include_router(communication.router, tags=["Communication"])
