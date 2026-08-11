"""
Performance & Load Benchmark Suite — Phase 7.

Measures and asserts concrete latency / throughput targets for the four
critical paths in the DisasterMesh pipeline:

  1. test_ingestion_throughput_100_reports
       → 100 concurrent POST /ingest/report requests in < 5 000 ms

  2. test_qdrant_vector_search_latency
       → Median similarity search across 1 000-point dataset < 200 ms

  3. test_ortools_scip_solver_time
       → SCIP solve for 50 responders × 20 incidents < 500 ms total

  4. test_websocket_broadcast_latency
       → Broadcast to 10 concurrent WS clients; max receive latency < 100 ms

All tests are marked @pytest.mark.slow so they can be deselected with:
    pytest -m "not slow"
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.embeddings import get_embedding_service
from app.agents.orchestrator import DispatchState, run_solver
from app.agents.vector_store import get_vector_store
from app.main import app
from app.schemas import (
    IncidentStatus,
    NeedsProfile,
    Priority,
    Responder,
    ResponderCapability,
    SourceType,
    VerifiedIncident,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Performance targets (adjust conservatively for test/CI machines)
# ---------------------------------------------------------------------------

INGESTION_LIMIT_MS: float = 5_000.0  # 100 reports in 5 seconds
QDRANT_SEARCH_LIMIT_MS: float = 200.0  # median search across 1k points
SOLVER_LIMIT_MS: float = 500.0  # SCIP for 50 responders × 20 incidents
WS_BROADCAST_LIMIT_MS: float = 100.0  # all 10 clients receive in 100 ms

QDRANT_DATASET_SIZE: int = 1_000  # points to pre-load
QDRANT_SEARCH_REPEATS: int = 10  # number of searches to median

SOLVER_NUM_RESPONDERS: int = 50
SOLVER_NUM_INCIDENTS: int = 20


# ---------------------------------------------------------------------------
# Helper: build a dummy 384-dim vector (avoids embedding cost in benchmarks)
# ---------------------------------------------------------------------------


def _dummy_vec(seed: int = 0) -> list[float]:
    """Deterministic unit-ish vector; avoids real embedding for bulk loads."""
    import math

    n = 384
    # Simple rotation — different for each seed, normalised
    v = [math.sin(seed * 0.01 + i * 0.005) for i in range(n)]
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


# ---------------------------------------------------------------------------
# 1. Ingestion throughput — 100 reports in < 5 s
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_ingestion_throughput_100_reports(async_client, memory_vector_store, monkeypatch):
    """
    Submit 100 citizen reports concurrently via asyncio.gather and assert
    the total wall-clock time is under INGESTION_LIMIT_MS.

    Exercises: POST /ingest/report → SituationalAgent → VectorStore.upsert()
    """
    from app.agents.intake_parser import get_intake_parser

    # Disable external Groq LLM API calls for throughput benchmark to avoid rate limits
    parser = get_intake_parser()
    monkeypatch.setattr(parser, "is_available", lambda: False)

    base_lat = 28.6667
    base_lon = 77.2333

    reports = [
        {
            "source": "sms",
            "text": f"Flood emergency report number {i}: water rising, need rescue at sector {i % 10}",
            "lat": base_lat + (i % 10) * 0.001,
            "lon": base_lon + (i % 10) * 0.001,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        for i in range(100)
    ]

    async def _post(payload: dict) -> int:
        resp = await async_client.post("/ingest/report", json=payload)
        return resp.status_code

    t0 = time.perf_counter()
    results = await asyncio.gather(*[_post(r) for r in reports])
    elapsed_ms = (time.perf_counter() - t0) * 1000

    ok_count = sum(1 for s in results if s == 200)
    assert ok_count == 100, f"Only {ok_count}/100 reports returned HTTP 200"

    assert elapsed_ms < INGESTION_LIMIT_MS, (
        f"Ingestion throughput FAILED: 100 reports took {elapsed_ms:.1f} ms "
        f"(limit: {INGESTION_LIMIT_MS} ms)"
    )
    print(
        f"\n[PERF] Ingestion throughput: 100 reports in {elapsed_ms:.1f} ms "
        f"({100_000 / elapsed_ms:.1f} reports/s)"
    )


# ---------------------------------------------------------------------------
# 2. Qdrant vector search latency — median < 200 ms over 1 000-point dataset
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_qdrant_vector_search_latency(memory_vector_store):
    """
    Pre-load 1 000 ProtoIncidents (with dummy pre-computed vectors to avoid
    embedding cost) then run QDRANT_SEARCH_REPEATS similarity searches and
    assert the median is under QDRANT_SEARCH_LIMIT_MS.

    Exercises: VectorStore.search_similar() — the primary Verification Agent
    dedup path.
    """
    vs = get_vector_store()

    # Bulk-upsert 1 000 proto incidents with dummy vectors
    import uuid

    from qdrant_client.models import PointStruct

    points = []
    for i in range(QDRANT_DATASET_SIZE):
        lat = 28.5 + (i % 100) * 0.002
        lon = 77.0 + (i % 100) * 0.002
        proto_id = str(uuid.uuid4())
        text = f"Benchmark incident {i} at lat={lat:.4f} lon={lon:.4f}"
        payload = {
            "proto_id": proto_id,
            "source": "sms",
            "lat": lat,
            "lon": lon,
            "timestamp_epoch": datetime.now(UTC).timestamp(),
            "text": text,
            "language": "en",
            "address": None,
            "page_content": text,
        }
        vec = _dummy_vec(seed=i)
        from app.agents.vector_store import COLLECTION_NAME, _uuid_to_int

        point_id = _uuid_to_int(proto_id)
        points.append(PointStruct(id=point_id, vector=vec, payload=payload))

    # Upsert in batches of 200
    raw_client = vs._raw_client
    for batch_start in range(0, QDRANT_DATASET_SIZE, 200):
        batch = points[batch_start : batch_start + 200]
        raw_client.upsert(collection_name=COLLECTION_NAME, points=batch)

    assert await vs.collection_size() >= QDRANT_DATASET_SIZE

    # Warm up with one search (cold-start cost excluded from measurement)
    await vs.search_similar("flood rescue emergency", limit=10)

    # Measure QDRANT_SEARCH_REPEATS searches and take median
    latencies_ms: list[float] = []
    for k in range(QDRANT_SEARCH_REPEATS):
        query = f"flooding and water rescue emergency incident {k}"
        t0 = time.perf_counter()
        results = await vs.search_similar(query, limit=10)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        latencies_ms.append(elapsed_ms)
        assert len(results) >= 1, f"Search {k} returned 0 results"

    latencies_ms.sort()
    median_ms = latencies_ms[len(latencies_ms) // 2]
    p95_ms = latencies_ms[int(len(latencies_ms) * 0.95)]

    assert median_ms < QDRANT_SEARCH_LIMIT_MS, (
        f"Qdrant search latency FAILED: median={median_ms:.1f} ms "
        f"(limit: {QDRANT_SEARCH_LIMIT_MS} ms) over {QDRANT_DATASET_SIZE} points"
    )
    print(
        f"\n[PERF] Qdrant search ({QDRANT_DATASET_SIZE} points): "
        f"median={median_ms:.1f} ms  p95={p95_ms:.1f} ms  "
        f"(limit: {QDRANT_SEARCH_LIMIT_MS} ms)"
    )


# ---------------------------------------------------------------------------
# 3. OR-Tools SCIP solver — 50 responders × 20 incidents < 500 ms
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_ortools_scip_solver_time(async_client, db_session, memory_vector_store):
    """
    Build a DispatchState with 50 mock Responder objects and a P1 incident,
    call run_solver() directly (bypassing DB persistence and graph routing),
    and assert the SCIP solve step completes in under SOLVER_LIMIT_MS.

    This isolates pure solver time from I/O latency.
    """
    # Build 50 mock responders with mixed capabilities
    caps_cycle = [
        [ResponderCapability.MEDICAL, ResponderCapability.RESCUE],
        [ResponderCapability.RESCUE, ResponderCapability.WATER],
        [ResponderCapability.LOGISTICS, ResponderCapability.EVACUATION],
        [ResponderCapability.MEDICAL],
        [ResponderCapability.WATER, ResponderCapability.LOGISTICS],
    ]

    mock_responders: list[Responder] = [
        Responder(
            id=f"bench-resp-{i:03d}",
            name=f"Bench Team {i}",
            team_type="rescue",
            capabilities=caps_cycle[i % len(caps_cycle)],
            team_size=6,
            capacity=2,
            lat=28.5 + (i % 20) * 0.005,
            lon=77.0 + (i % 20) * 0.005,
        )
        for i in range(SOLVER_NUM_RESPONDERS)
    ]

    # Time the solver across SOLVER_NUM_INCIDENTS independent runs
    total_elapsed_ms = 0.0

    for j in range(SOLVER_NUM_INCIDENTS):
        incident = VerifiedIncident(
            cluster_id=f"bench-inc-{j:03d}",
            lat=28.6667 + j * 0.001,
            lon=77.2333 + j * 0.001,
            timestamp=datetime.now(UTC),
            confidence=0.9,
            severity=Priority.P1,
            needs=NeedsProfile(medical=True, rescue=True, water=True),
        )

        state: DispatchState = {
            "incident": incident,
            "priority": Priority.P1,
            "available": mock_responders,
            "req_caps": {
                "medical": True,
                "rescue": True,
                "water": True,
                "logistics": False,
                "evacuation": False,
            },
        }

        t0 = time.perf_counter()
        result_state = await run_solver(state)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        total_elapsed_ms += elapsed_ms

        # Solver must produce a result (OPTIMAL, FEASIBLE, or route to heuristic)
        solver_status = result_state.get("solver_status", "")
        assert solver_status in ("OPTIMAL", "FEASIBLE", "INFEASIBLE", "NO_RESPONDERS"), (
            f"Unexpected solver status for incident {j}: {solver_status}"
        )

    assert total_elapsed_ms < SOLVER_LIMIT_MS, (
        f"OR-Tools SCIP FAILED: {SOLVER_NUM_INCIDENTS} incidents × {SOLVER_NUM_RESPONDERS} "
        f"responders took {total_elapsed_ms:.1f} ms (limit: {SOLVER_LIMIT_MS} ms)"
    )
    per_incident_ms = total_elapsed_ms / SOLVER_NUM_INCIDENTS
    print(
        f"\n[PERF] OR-Tools SCIP: {SOLVER_NUM_INCIDENTS} incidents × {SOLVER_NUM_RESPONDERS} "
        f"responders = {total_elapsed_ms:.1f} ms total "
        f"({per_incident_ms:.1f} ms/incident)"
    )


# ---------------------------------------------------------------------------
# 4. WebSocket broadcast latency — 10 clients receive in < 100 ms
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_websocket_broadcast_latency(async_client, memory_vector_store):
    """
    Connect 10 WebSocket clients to /ws/updates simultaneously, then trigger
    a single lifecycle transition. Assert all 10 clients receive the event
    within WS_BROADCAST_LIMIT_MS of the HTTP request completing.
    """
    from starlette.testclient import TestClient

    N_CLIENTS = 10

    with TestClient(app) as tc:
        # Seed an incident to transition
        emb_svc = get_embedding_service()
        vs = get_vector_store()
        incident = VerifiedIncident(
            cluster_id="bench-ws-broadcast-001",
            source_provenance=[SourceType.SMS],
            lat=28.6667,
            lon=77.2333,
            timestamp=datetime.now(UTC),
            confidence=0.9,
            severity=Priority.P2,
            needs=NeedsProfile(medical=True),
            status=IncidentStatus.REPORTED,
        )
        vec = await emb_svc.embed_text("Benchmark WS broadcast test flood emergency")
        await vs.upsert_verified(incident, vec)
        cid = incident.cluster_id

        ws_clients = [tc.websocket_connect("/ws/updates") for _ in range(N_CLIENTS)]
        for ws in ws_clients:
            ws.__enter__()

        try:
            t0 = time.perf_counter()
            resp = await async_client.post(
                f"/incidents/{cid}/status",
                json={"new_status": "VERIFIED", "reason": "WS broadcast benchmark"},
            )
            assert resp.status_code == 200

            t_recv_list = []
            for ws in ws_clients:
                data = ws.receive_json()
                t1 = time.perf_counter()
                assert data["event"] == "lifecycle_transition"
                assert data["cluster_id"] == cid
                t_recv_list.append(t1)

            max_latency_ms = (max(t_recv_list) - t0) * 1000
            assert max_latency_ms < WS_BROADCAST_LIMIT_MS, (
                f"WebSocket broadcast FAILED: max latency={max_latency_ms:.1f} ms "
                f"to {N_CLIENTS} clients (limit: {WS_BROADCAST_LIMIT_MS} ms)"
            )
            avg_latency_ms = (sum(t_recv_list) / len(t_recv_list) - t0) * 1000
            print(
                f"\n[PERF] WS broadcast → {N_CLIENTS} clients: "
                f"avg={avg_latency_ms:.1f} ms  max={max_latency_ms:.1f} ms  "
                f"(limit: {WS_BROADCAST_LIMIT_MS} ms)"
            )
        finally:
            for ws in ws_clients:
                ws.__exit__(None, None, None)
