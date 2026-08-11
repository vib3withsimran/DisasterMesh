"""
Integration tests for the Communication Agent REST & WebSocket APIs — Phase 6.

Validates:
  - POST /incidents/{cluster_id}/status  — lifecycle transition endpoint
  - GET  /incidents/{cluster_id}/summary — situational summary endpoint
  - GET  /communications/logs            — audit log endpoint
  - WS   /ws/updates                     — real-time broadcast endpoint

All tests use the in-memory SQLite + in-memory Qdrant fixtures from conftest.py.
Twilio is not required; mock mode is active whenever credentials are absent.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _seed_incident(
    cluster_id: str = "cluster_integ-test-001",
    status: IncidentStatus = IncidentStatus.VERIFIED,
) -> VerifiedIncident:
    """
    Insert a VerifiedIncident into the in-memory Qdrant instance used by tests.
    Returns the VerifiedIncident that was seeded.
    """
    from app.agents.embeddings import get_embedding_service

    incident = VerifiedIncident(
        cluster_id=cluster_id,
        source_provenance=[SourceType.SMS, SourceType.SATELLITE],
        lat=28.6139,
        lon=77.2090,
        timestamp=datetime(2026, 8, 8, 7, 0, 0, tzinfo=UTC),
        confidence=0.87,
        severity=Priority.P1,
        needs=NeedsProfile(medical=True, rescue=True),
        media_urls=[],
        status=status,
    )

    emb_svc = get_embedding_service()
    vector = await emb_svc.embed_text(f"Medical emergency at {incident.lat},{incident.lon}")
    vs = get_vector_store()
    await vs.upsert_verified(incident, vector)
    return incident


# ---------------------------------------------------------------------------
# POST /incidents/{cluster_id}/status — lifecycle transition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_status_transition_returns_200(async_client, db_session):
    """VERIFIED → ASSIGNED transition should return 200 with correct fields."""
    cluster_id = "cluster_integ-sm-001"
    await _seed_incident(cluster_id=cluster_id, status=IncidentStatus.VERIFIED)

    resp = await async_client.post(
        f"/incidents/{cluster_id}/status",
        json={"new_status": "ASSIGNED", "reason": "OR-Tools dispatch completed"},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["cluster_id"] == cluster_id
    assert data["old_status"] == "VERIFIED"
    assert data["new_status"] == "ASSIGNED"


@pytest.mark.asyncio
async def test_invalid_transition_returns_422(async_client, db_session):
    """REPORTED → RESOLVED (skipping states) must return 422."""
    cluster_id = "cluster_integ-sm-002"
    await _seed_incident(cluster_id=cluster_id, status=IncidentStatus.REPORTED)

    resp = await async_client.post(
        f"/incidents/{cluster_id}/status",
        json={"new_status": "RESOLVED"},
    )

    assert resp.status_code == 422, resp.text
    # Error message must reference REPORTED
    body = resp.json()
    assert "REPORTED" in str(body)


@pytest.mark.asyncio
async def test_unknown_incident_returns_404(async_client, db_session):
    """Status transition for a non-existent cluster must return 404."""
    resp = await async_client.post(
        "/incidents/cluster_does-not-exist/status",
        json={"new_status": "VERIFIED"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_transition_with_citizen_phone_writes_comm_log(async_client, db_session):
    """When citizen_phone is provided, a CommunicationLog row must be written."""
    from sqlalchemy import select

    cluster_id = "cluster_integ-sm-003"
    await _seed_incident(cluster_id=cluster_id, status=IncidentStatus.ASSIGNED)

    # Strip Twilio creds to ensure mock mode
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TWILIO_ACCOUNT_SID", None)
        os.environ.pop("TWILIO_AUTH_TOKEN", None)

        resp = await async_client.post(
            f"/incidents/{cluster_id}/status",
            json={
                "new_status": "EN_ROUTE",
                "citizen_phone": "+919876543210",
                "reason": "Responder confirmed departure",
            },
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["notifications_sent"] is True

    # Verify the CommunicationLog was written
    rows = (
        (
            await db_session.execute(
                select(CommunicationLog).where(CommunicationLog.incident_id == cluster_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    log = rows[0]
    assert log.recipient_type == "citizen"
    assert log.channel == "mock"
    assert log.delivery_status == "sent"
    assert cluster_id in log.message_body


# ---------------------------------------------------------------------------
# GET /incidents/{cluster_id}/summary — situational summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_endpoint_returns_valid_schema(async_client, db_session):
    """GET /incidents/{id}/summary must return a valid SituationalSummary."""
    cluster_id = "cluster_integ-sum-001"
    await _seed_incident(cluster_id=cluster_id, status=IncidentStatus.EN_ROUTE)

    resp = await async_client.get(f"/incidents/{cluster_id}/summary")

    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Validate top-level fields
    assert data["cluster_id"] == cluster_id
    assert data["status"] == "EN_ROUTE"
    assert data["severity"] == "P1"
    assert abs(data["confidence"] - 0.87) < 0.01
    assert "human_summary" in data
    assert "generated_at" in data
    assert isinstance(data["assigned_responders"], list)
    assert isinstance(data["needs"], dict)


@pytest.mark.asyncio
async def test_summary_human_text_is_non_empty(async_client, db_session):
    """human_summary must be a non-empty string containing key identifiers."""
    cluster_id = "cluster_integ-sum-002"
    await _seed_incident(cluster_id=cluster_id, status=IncidentStatus.ASSIGNED)

    resp = await async_client.get(f"/incidents/{cluster_id}/summary")
    assert resp.status_code == 200
    text = resp.json()["human_summary"]
    assert len(text) > 50
    assert cluster_id in text
    assert "P1" in text


@pytest.mark.asyncio
async def test_summary_missing_incident_returns_404(async_client, db_session):
    resp = await async_client.get("/incidents/cluster_does-not-exist/summary")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /communications/logs — audit log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_comms_log_returns_empty_list_for_unused_incident(async_client, db_session):
    """GET /communications/logs?incident_id=unused should return []."""
    resp = await async_client.get("/communications/logs?incident_id=cluster_unused_999")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_comms_log_shows_written_entries(async_client, db_session):
    """After a citizen SMS is triggered, the log entry must be queryable."""
    cluster_id = "cluster_integ-log-001"
    await _seed_incident(cluster_id=cluster_id, status=IncidentStatus.ASSIGNED)

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TWILIO_ACCOUNT_SID", None)
        os.environ.pop("TWILIO_AUTH_TOKEN", None)

        await async_client.post(
            f"/incidents/{cluster_id}/status",
            json={
                "new_status": "EN_ROUTE",
                "citizen_phone": "+919876543210",
            },
        )

    resp = await async_client.get(f"/communications/logs?incident_id={cluster_id}")
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) == 1
    log = logs[0]
    assert log["incident_id"] == cluster_id
    assert log["recipient_type"] == "citizen"
    assert log["message_type"] == "status_update"
    assert log["delivery_status"] == "sent"


@pytest.mark.asyncio
async def test_comms_log_pagination(async_client, db_session):
    """limit and offset query params must work correctly."""
    resp = await async_client.get("/communications/logs?limit=10&offset=0")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# WS /ws/updates — real-time broadcast
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_connects_and_receives_broadcast():
    """
    Verify that connected WebSocket clients receive broadcast lifecycle events.
    """
    from starlette.testclient import TestClient

    from app.routers.communication import manager

    cluster_id = "cluster_integ-ws-001"

    with TestClient(app) as client:
        with client.websocket_connect("/ws/updates") as ws:
            # Directly trigger broadcast on the ConnectionManager
            await manager.broadcast(
                {
                    "event": "lifecycle_transition",
                    "cluster_id": cluster_id,
                    "old_status": "VERIFIED",
                    "new_status": "ASSIGNED",
                }
            )

            # Check if WS received broadcast event
            data = ws.receive_json()
            assert data["event"] == "lifecycle_transition"
            assert data["cluster_id"] == cluster_id
            assert data["old_status"] == "VERIFIED"
            assert data["new_status"] == "ASSIGNED"


def test_websocket_endpoint_accepts_connection():
    """
    Verify that WS /ws/updates accepts connections and is registered on the app.
    """
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        with client.websocket_connect("/ws/updates") as ws:
            ws.send_text("ping")
