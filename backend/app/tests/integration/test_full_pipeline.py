"""
End-to-End Pipeline Integration Tests — Phase 7.

Validates the complete DisasterMesh 6-agent lifecycle in a single test
session using the in-memory SQLite + in-memory Qdrant fixtures from
conftest.py (no real external services required).

Test coverage:
  1. test_citizen_sms_deduplication_pipeline
  2. test_satellite_plus_citizen_cross_source_boost
  3. test_iot_sensor_alert_pipeline
  4. test_severity_assessment_p1_triggers_multi_responder_dispatch
  5. test_full_lifecycle_state_machine
  6. test_websocket_receives_transition_events
  7. test_communication_log_written_for_full_pipeline
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.agents.embeddings import get_embedding_service
from app.agents.vector_store import get_vector_store
from app.main import app
from app.models import CommunicationLog
from app.schemas import (
    IncidentStatus,
    NeedsProfile,
    Priority,
    SourceType,
    VerifiedIncident,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_client():
    """ASGI test client — reuses the in-memory fixtures from conftest.py."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _seed_verified_incident(
    cluster_id: str,
    lat: float = 28.6667,
    lon: float = 77.2333,
    severity: Priority = Priority.P1,
    needs: NeedsProfile | None = None,
    status: IncidentStatus = IncidentStatus.REPORTED,
    source_provenance: list[SourceType] | None = None,
) -> VerifiedIncident:
    """Embed and upsert a VerifiedIncident into the in-memory Qdrant store."""
    emb_svc = get_embedding_service()
    vs = get_vector_store()

    incident = VerifiedIncident(
        cluster_id=cluster_id,
        source_provenance=source_provenance or [SourceType.SMS],
        lat=lat,
        lon=lon,
        timestamp=datetime.now(UTC),
        confidence=0.88,
        severity=severity,
        needs=needs or NeedsProfile(medical=True, rescue=True),
        media_urls=[],
        status=status,
    )

    vector = await emb_svc.embed_text(f"Emergency flood rescue at {lat:.4f},{lon:.4f}")
    await vs.upsert_verified(incident, vector)
    return incident


async def _seed_responders(async_client: AsyncClient, count: int = 3) -> list[str]:
    """Register *count* diverse responder teams. Returns list of IDs."""
    teams = [
        {
            "name": "Delhi Medical Team Alpha",
            "team_type": "medical",
            "capabilities": ["medical", "rescue"],
            "team_size": 8,
            "capacity": 3,
            "lat": 28.6600,
            "lon": 77.2200,
        },
        {
            "name": "NDRF Water Rescue Bravo",
            "team_type": "rescue",
            "capabilities": ["rescue", "water"],
            "team_size": 12,
            "capacity": 4,
            "lat": 28.6700,
            "lon": 77.2400,
        },
        {
            "name": "Civil Defence Logistics Charlie",
            "team_type": "logistics",
            "capabilities": ["logistics", "evacuation"],
            "team_size": 6,
            "capacity": 2,
            "lat": 28.6500,
            "lon": 77.2100,
        },
    ]

    ids: list[str] = []
    for payload in teams[:count]:
        resp = await async_client.post("/responders", json=payload)
        assert resp.status_code == 201, f"Failed to seed responder: {resp.text}"
        ids.append(resp.json()["id"])
    return ids


# ---------------------------------------------------------------------------
# 1. SMS deduplication pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_citizen_sms_deduplication_pipeline(async_client, memory_vector_store):
    """
    5 overlapping SMS reports about the Yamuna Bazar flood are ingested via
    POST /ingest/report.  Each must return HTTP 200 with a unique message_id,
    and the VectorStore collection must grow by at least 5 points.
    """
    vs = get_vector_store()
    count_before = await vs.collection_size()

    sms_texts = [
        "Water rising fast near Yamuna Bazar, need boats urgently",
        "Yamuna ka paani bahut badh gaya hai, madad chahiye",
        "Flooding at Yamuna Bazar area, families trapped",
        "Heavy flood near Yamuna Bazaar, rescue required immediately",
        "Yamuna bazar mein paani bhar gaya, log phanse hain",
    ]

    message_ids: list[str] = []
    for i, text in enumerate(sms_texts):
        resp = await async_client.post(
            "/ingest/report",
            json={
                "source": "sms",
                "text": text,
                "lat": 28.6667 + 0.0001 * i,
                "lon": 77.2333 + 0.0001 * i,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        assert resp.status_code == 200, f"Report {i} failed: {resp.text}"
        data = resp.json()
        assert data["status"] == "received"
        assert data["message_id"]
        message_ids.append(data["message_id"])

    assert len(set(message_ids)) == 5, "Expected 5 unique message IDs"

    count_after = await vs.collection_size()
    assert count_after >= count_before + 5, (
        f"VectorStore should grow by ≥5: before={count_before}, after={count_after}"
    )


# ---------------------------------------------------------------------------
# 2. Satellite + citizen cross-source pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_satellite_plus_citizen_cross_source_boost(async_client, memory_vector_store):
    """
    A Sentinel-2 GeoJSON polygon and 3 SMS reports are ingested.
    All 4 should land in Qdrant, and a nearby search should surface the
    satellite source among results.
    """
    vs = get_vector_store()
    count_before = await vs.collection_size()

    satellite_payload = {
        "source": "satellite",
        "geojson": {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [77.2300, 28.6640],
                        [77.2400, 28.6640],
                        [77.2400, 28.6720],
                        [77.2300, 28.6720],
                        [77.2300, 28.6640],
                    ]
                ],
            },
            "properties": {"flood_area_km2": 2.3, "source": "Sentinel-2"},
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }
    resp = await async_client.post("/ingest/satellite", json=satellite_payload)
    assert resp.status_code == 200, f"Satellite ingest failed: {resp.text}"

    sms_reports = [
        ("Yamuna Bazar ke paas bahut barish ho rahi hai, boats chahiye", 28.6667, 77.2333),
        ("Flooding spotted near Yamuna Bazar, people stranded on rooftops", 28.6670, 77.2340),
        ("Emergency at Yamuna Bazar flood zone, medical help needed", 28.6665, 77.2330),
    ]
    for text, lat, lon in sms_reports:
        resp = await async_client.post(
            "/ingest/report",
            json={
                "source": "sms",
                "text": text,
                "lat": lat,
                "lon": lon,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        assert resp.status_code == 200, f"SMS ingest failed: {resp.text}"

    count_after = await vs.collection_size()
    assert count_after >= count_before + 4, (
        f"Expected ≥4 new Qdrant points: before={count_before}, after={count_after}"
    )

    results = await vs.search_nearby(lat=28.6680, lon=77.2350, radius_m=2000, limit=20)
    sources = [r.get("source") for r in results]
    assert "satellite" in sources, f"Satellite source not found in nearby search results: {sources}"


# ---------------------------------------------------------------------------
# 3. IoT sensor alert pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_iot_sensor_alert_pipeline(async_client, memory_vector_store):
    """
    An IoT water-level reading above the 3.0 m alert threshold is ingested
    via POST /ingest/sensor and stored in Qdrant as source='iot_sensor'.
    """
    vs = get_vector_store()
    count_before = await vs.collection_size()

    resp = await async_client.post(
        "/ingest/sensor",
        json={
            "source": "iot_sensor",
            "sensor_id": "WL-YAMUNA-004",
            "sensor_type": "water_level",
            "value": 4.2,
            "unit": "metres",
            "lat": 28.6650,
            "lon": 77.2350,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert resp.status_code == 200, f"Sensor ingest failed: {resp.text}"
    data = resp.json()
    assert data["status"] == "received"
    assert data["message_id"]
    assert data["lat"] is not None

    count_after = await vs.collection_size()
    assert count_after >= count_before + 1, (
        f"Qdrant should grow by ≥1: before={count_before}, after={count_after}"
    )

    results = await vs.search_nearby(lat=28.6650, lon=77.2350, radius_m=500, limit=10)
    assert len(results) >= 1
    sources = [r.get("source") for r in results]
    assert "iot_sensor" in sources, f"IoT sensor source not found in nearby results: {sources}"


# ---------------------------------------------------------------------------
# 4. P1 severity → multi-responder dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_severity_assessment_p1_triggers_multi_responder_dispatch(
    async_client, db_session, memory_vector_store
):
    """
    A P1 VerifiedIncident with medical+rescue needs must receive ≥ 2
    responders from the Orchestrator (OR-Tools SCIP min-responders constraint
    for P1 is 2).
    """
    await _seed_responders(async_client, count=3)

    incident = await _seed_verified_incident(
        cluster_id="e2e-p1-dispatch-001",
        lat=28.6667,
        lon=77.2333,
        severity=Priority.P1,
        needs=NeedsProfile(medical=True, rescue=True, water=True),
    )

    resp = await async_client.post(f"/dispatch/{incident.cluster_id}")
    assert resp.status_code == 200, f"Dispatch failed: {resp.text}"

    data = resp.json()
    assert data["cluster_id"] == incident.cluster_id
    assert data["status"] in ("ASSIGNED", "HEURISTIC_FALLBACK"), (
        f"Unexpected dispatch status: {data['status']}"
    )
    assignments = data["assignments"]
    assert len(assignments) >= 2, f"P1 incident must get ≥2 responders; got {len(assignments)}"
    for a in assignments:
        assert a["responder_id"]
        assert a["eta_seconds"] >= 0


# ---------------------------------------------------------------------------
# 5. Full lifecycle state machine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_lifecycle_state_machine(async_client, db_session, memory_vector_store):
    """
    Walk the complete 5-step lifecycle via POST /incidents/{id}/status and
    assert each transition returns 200 with the correct old/new_status.
    Then assert a 6th (illegal) transition is rejected.
    """
    incident = await _seed_verified_incident(
        cluster_id="e2e-lifecycle-001",
        status=IncidentStatus.REPORTED,
        severity=Priority.P2,
    )
    cid = incident.cluster_id

    transitions = [
        (IncidentStatus.REPORTED, IncidentStatus.VERIFIED),
        (IncidentStatus.VERIFIED, IncidentStatus.ASSIGNED),
        (IncidentStatus.ASSIGNED, IncidentStatus.EN_ROUTE),
        (IncidentStatus.EN_ROUTE, IncidentStatus.ON_SCENE),
        (IncidentStatus.ON_SCENE, IncidentStatus.RESOLVED),
    ]

    for expected_old, expected_new in transitions:
        resp = await async_client.post(
            f"/incidents/{cid}/status",
            json={"new_status": expected_new, "reason": f"E2E → {expected_new}"},
        )
        assert resp.status_code == 200, (
            f"Transition {expected_old}→{expected_new} failed ({resp.status_code}): {resp.text}"
        )
        data = resp.json()
        assert data["cluster_id"] == cid
        assert data["old_status"] == expected_old
        assert data["new_status"] == expected_new

    # Illegal transition out of RESOLVED must be rejected
    resp = await async_client.post(
        f"/incidents/{cid}/status",
        json={"new_status": IncidentStatus.ON_SCENE},
    )
    assert resp.status_code in (400, 422), (
        f"Expected rejection from RESOLVED, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# 6. WebSocket receives lifecycle transition events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_receives_transition_events(async_client, memory_vector_store):
    """
    A WebSocket client connected before status transitions begin must receive
    'lifecycle_transition' events for every HTTP-driven status change.

    Two transitions are driven via REST:
      REPORTED → VERIFIED → ASSIGNED
    """
    from starlette.testclient import TestClient

    with TestClient(app) as tc:
        incident = await _seed_verified_incident(
            cluster_id="e2e-ws-events-001",
            status=IncidentStatus.REPORTED,
            severity=Priority.P2,
        )
        cid = incident.cluster_id

        with tc.websocket_connect("/ws/updates") as ws:
            resp1 = await async_client.post(
                f"/incidents/{cid}/status",
                json={"new_status": "VERIFIED", "reason": "WS test"},
            )
            assert resp1.status_code == 200

            resp2 = await async_client.post(
                f"/incidents/{cid}/status",
                json={"new_status": "ASSIGNED", "reason": "WS test"},
            )
            assert resp2.status_code == 200

            ev1 = ws.receive_json()
            ev2 = ws.receive_json()

            assert ev1["event"] == "lifecycle_transition"
            assert ev1["cluster_id"] == cid
            assert ev1["old_status"] == "REPORTED"
            assert ev1["new_status"] == "VERIFIED"

            assert ev2["event"] == "lifecycle_transition"
            assert ev2["cluster_id"] == cid
            assert ev2["old_status"] == "VERIFIED"
            assert ev2["new_status"] == "ASSIGNED"


# ---------------------------------------------------------------------------
# 7. CommunicationLog audit trail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_communication_log_written_for_full_pipeline(
    async_client, db_session, memory_vector_store
):
    """
    Triggering a lifecycle transition that includes citizen_phone must write
    ≥ 1 row into the CommunicationLog table for that cluster_id.
    """
    incident = await _seed_verified_incident(
        cluster_id="e2e-comm-log-001",
        status=IncidentStatus.REPORTED,
        severity=Priority.P1,
    )
    cid = incident.cluster_id

    resp = await async_client.post(
        f"/incidents/{cid}/status",
        json={
            "new_status": "VERIFIED",
            "reason": "Comm log test",
            "citizen_phone": "+919876543210",
        },
    )
    assert resp.status_code == 200, f"Status transition failed: {resp.text}"

    result = await db_session.execute(
        select(CommunicationLog).where(CommunicationLog.incident_id == cid)
    )
    logs = result.scalars().all()

    assert len(logs) >= 1, f"Expected ≥1 CommunicationLog row for {cid}, found {len(logs)}"
    log = logs[0]
    assert log.incident_id == cid
    assert log.recipient_type == "citizen"
    assert log.message_body  # non-empty notification text
