"""
Communication router — Phase 6.

Endpoints
---------
POST /incidents/{cluster_id}/status
    Transition the incident lifecycle state and trigger notifications.

GET  /incidents/{cluster_id}/summary
    Fetch a human-readable situational summary for incident commanders.

GET  /communications/logs
    Paginated view of the CommunicationLog audit table.

WS   /ws/updates
    Real-time broadcast of lifecycle transitions to connected dashboard clients.
    Every connected WebSocket client receives a JSON event whenever a status
    transition is committed via ``POST /incidents/{cluster_id}/status``.

WebSocket event payload shape:
    {
      "event": "lifecycle_transition",
      "cluster_id": "cluster_abc123",
      "old_status": "ASSIGNED",
      "new_status": "EN_ROUTE",
      "timestamp": "2026-08-08T07:00:00Z",
      "summary": { ...SituationalSummary }
    }
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.communication import get_communication_agent
from app.agents.vector_store import get_vector_store
from app.db import get_db
from app.models import CommunicationLog
from app.schemas import (
    CommLogEntry,
    IncidentStatus,
    SituationalSummary,
    StatusTransitionRequest,
    VerifiedIncident,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """
    Tracks all live WebSocket connections.

    Thread-safety note: FastAPI runs in a single-threaded async event loop so
    a plain ``set`` is safe here.  We discard dead sockets on each broadcast
    rather than maintaining a background heartbeat.
    """

    def __init__(self) -> None:
        self.active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)
        logger.info("WS client connected — total active: %d", len(self.active))

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)
        logger.info("WS client disconnected — total active: %d", len(self.active))

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """Send *payload* as JSON to every connected client, evicting dead sockets."""
        dead: set[WebSocket] = set()
        for ws in self.active:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                dead.add(ws)
        self.active -= dead
        if dead:
            logger.debug("Evicted %d dead WS connection(s)", len(dead))


#: Module-level singleton shared by all router handler instances.
manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Helper: load VerifiedIncident from Qdrant
# ---------------------------------------------------------------------------


async def _get_verified_incident(cluster_id: str) -> VerifiedIncident:
    """
    Fetch a ``VerifiedIncident`` from the Qdrant vector store.

    Raises
    ------
    HTTPException(404)
        If no incident with *cluster_id* exists in the vector store.
    """
    vs = get_vector_store()
    payload = await vs.get_incident(cluster_id)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"Incident '{cluster_id}' not found in vector store.",
        )
    # Reconstruct a VerifiedIncident Pydantic model from the stored payload dict
    try:
        ts_epoch = payload.get("timestamp_epoch")
        if ts_epoch is not None:
            ts = datetime.fromtimestamp(ts_epoch, tz=UTC)
        elif "timestamp" in payload:
            ts_val = payload["timestamp"]
            ts = datetime.fromisoformat(ts_val) if isinstance(ts_val, str) else ts_val
        else:
            ts = datetime.now(UTC)

        needs_raw = payload.get("needs") or {}
        from app.schemas import NeedsProfile, Priority, SourceType

        return VerifiedIncident(
            cluster_id=payload["cluster_id"],
            source_provenance=[SourceType(s) for s in payload.get("source_provenance", [])],
            lat=payload["lat"],
            lon=payload["lon"],
            timestamp=ts,
            confidence=payload.get("confidence", 0.5),
            severity=Priority(payload.get("severity", "P4")),
            needs=NeedsProfile(**needs_raw) if isinstance(needs_raw, dict) else NeedsProfile(),
            media_urls=payload.get("media_urls", []),
            status=IncidentStatus(payload.get("status", "REPORTED")),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"Failed to deserialise incident payload: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/incidents/{cluster_id}/status",
    response_model=dict,
    summary="Transition incident lifecycle state",
    tags=["Communication"],
)
async def transition_incident_status(
    cluster_id: str,
    body: StatusTransitionRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Advance the incident lifecycle state machine.

    Valid transitions:
    ``REPORTED → VERIFIED → ASSIGNED → EN_ROUTE → ON_SCENE → RESOLVED``

    If ``citizen_phone`` is provided in the request body the CommunicationAgent
    will also dispatch a status-update SMS to that number (mock mode when
    Twilio credentials are absent).

    Returns
    -------
    JSON object with ``cluster_id``, ``old_status``, ``new_status``, and
    ``notifications_sent`` flag.

    Raises
    ------
    422 Unprocessable Entity
        If the requested transition is not valid for the current state.
    404 Not Found
        If the incident does not exist in the vector store.
    """
    incident = await _get_verified_incident(cluster_id)
    agent = get_communication_agent()

    old_status: IncidentStatus = incident.status

    # Validate and apply state transition
    try:
        incident = agent.transition(incident, body.new_status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Persist updated status back to Qdrant
    vs = get_vector_store()
    await vs.upsert_incident_status(cluster_id, body.new_status)

    # Optionally notify citizen
    notification_sent = False
    if body.citizen_phone:
        # Best-effort; don't fail the whole request if SMS errors
        try:
            notification_sent = await agent.notify_citizen_status(
                phone=body.citizen_phone,
                cluster_id=cluster_id,
                new_status=body.new_status,
                db=db,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Citizen SMS failed: %s", exc)

    # Build broadcast payload
    broadcast_payload: dict[str, Any] = {
        "event": "lifecycle_transition",
        "cluster_id": cluster_id,
        "old_status": old_status,
        "new_status": body.new_status,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # Broadcast to all connected WS clients (fire-and-forget; errors are swallowed)
    await manager.broadcast(broadcast_payload)

    return {
        "cluster_id": cluster_id,
        "old_status": old_status,
        "new_status": body.new_status,
        "notifications_sent": notification_sent,
        "reason": body.reason,
    }


@router.get(
    "/incidents/{cluster_id}/summary",
    response_model=SituationalSummary,
    summary="Fetch human-readable situational summary",
    tags=["Communication"],
)
async def get_situational_summary(
    cluster_id: str,
    db: AsyncSession = Depends(get_db),
) -> SituationalSummary:
    """
    Generate and return a structured situational summary for incident commanders.

    The summary includes:
    - Incident ID, severity, confidence, and current status
    - GPS coordinates and timestamp
    - Needs breakdown (medical / rescue / evacuation / shelter / water / food)
    - Source provenance list
    - All assigned responders with ETA and capability match scores
    - A pre-formatted human-readable text block (``human_summary``)

    Raises
    ------
    404 Not Found
        If the incident does not exist.
    """
    incident = await _get_verified_incident(cluster_id)
    agent = get_communication_agent()
    return await agent.generate_situational_summary(incident, db)


@router.get(
    "/communications/logs",
    response_model=list[CommLogEntry],
    summary="View communication audit log",
    tags=["Communication"],
)
async def get_communication_logs(
    incident_id: str | None = Query(default=None, description="Filter by incident cluster_id"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[CommLogEntry]:
    """
    Retrieve paginated communication log entries.

    Optionally filter by ``incident_id``.  Results are ordered by ``sent_at``
    descending (most recent first).

    Parameters
    ----------
    incident_id:
        When provided, only rows matching this cluster ID are returned.
    limit:
        Max rows to return (1–500, default 50).
    offset:
        Number of rows to skip for pagination.
    """
    query = select(CommunicationLog).order_by(CommunicationLog.sent_at.desc())
    if incident_id:
        query = query.where(CommunicationLog.incident_id == incident_id)
    query = query.offset(offset).limit(limit)

    rows = (await db.execute(query)).scalars().all()
    return [CommLogEntry.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws/updates")
async def websocket_updates(ws: WebSocket) -> None:
    """
    Real-time WebSocket endpoint for incident lifecycle updates.

    Clients connect to ``WS /ws/updates`` and receive JSON events whenever an
    incident status transition is committed via
    ``POST /incidents/{cluster_id}/status``.

    The connection stays open until the client disconnects.  No authentication
    is required (demo mode).  Token-based auth can be added in Phase 9 via a
    ``?token=`` query parameter.

    Event shape:
    ::

        {
          "event": "lifecycle_transition",
          "cluster_id": "cluster_abc",
          "old_status": "ASSIGNED",
          "new_status": "EN_ROUTE",
          "timestamp": "2026-08-08T07:00:00+00:00"
        }
    """
    await manager.connect(ws)
    try:
        # Keep the connection alive — we only push; clients don't send messages.
        # If the client sends anything we silently ignore it.
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:  # noqa: BLE001
        manager.disconnect(ws)
