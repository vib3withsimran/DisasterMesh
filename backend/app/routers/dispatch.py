"""
Dispatch router — trigger responder assignment via the Orchestrator Agent (Phase 5).

Endpoints
---------
POST /dispatch/optimize        Batch-dispatch across multiple cluster IDs.
POST /dispatch/{cluster_id}   Dispatch responders to a single incident cluster.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import get_orchestrator_agent
from app.agents.vector_store import VectorStore, get_vector_store
from app.db import get_db
from app.schemas import (
    DispatchResult,
    DispatchStatus,
    NeedsProfile,
    Priority,
    VerifiedIncident,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _fetch_incident(cluster_id: str, vector_store: VectorStore) -> VerifiedIncident:
    """
    Retrieve a VerifiedIncident from Qdrant by cluster_id.

    Raises HTTPException(404) if not found.
    """
    payload = await vector_store.get_by_cluster_id(cluster_id)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"Incident cluster '{cluster_id}' not found in vector store",
        )

    # Reconstruct VerifiedIncident from stored Qdrant payload
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
        incident = VerifiedIncident(
            cluster_id=payload["cluster_id"],
            source_provenance=payload.get("source_provenance", []),
            lat=payload["lat"],
            lon=payload["lon"],
            timestamp=ts,
            confidence=payload.get("confidence", 0.5),
            severity=Priority(payload.get("severity", "P4")),
            needs=NeedsProfile(**needs_raw) if isinstance(needs_raw, dict) else NeedsProfile(),
            media_urls=payload.get("media_urls", []),
            status=payload.get("status", "VERIFIED"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.error("Failed to reconstruct incident %s: %s", cluster_id, exc)
        raise HTTPException(
            status_code=422,
            detail=f"Incident payload for '{cluster_id}' is malformed: {exc}",
        ) from exc

    return incident


# ── Batch optimize (MUST BE DECLARED BEFORE /{cluster_id}) ─────────────────────


class BatchDispatchRequest(BaseModel):
    """Request body for the batch optimize endpoint."""

    cluster_ids: list[str]


@router.post(
    "/optimize",
    summary="Batch dispatch across multiple incidents",
    response_model=list[DispatchResult],
)
async def optimize_batch(
    body: BatchDispatchRequest,
    db: AsyncSession = Depends(get_db),
) -> list[DispatchResult]:
    """
    Run the LangGraph dispatch pipeline for multiple incident clusters in sequence.

    Responder deconfliction is automatic: each dispatched responder is marked
    **assigned** before the next incident is processed, preventing double-booking.

    Returns one `DispatchResult` per requested `cluster_id`.
    Missing cluster IDs return a `NO_RESPONDERS_AVAILABLE` result rather than
    failing the entire batch.
    """
    vector_store = get_vector_store()
    orchestrator = get_orchestrator_agent(db)
    results: list[DispatchResult] = []

    for cid in body.cluster_ids:
        try:
            incident = await _fetch_incident(cid, vector_store)
            result = await orchestrator.dispatch_incident(incident)
        except HTTPException as exc:
            # Incident not found — return a NO_RESPONDERS result for this id
            logger.warning("Batch dispatch: incident %s not found (%s)", cid, exc.detail)
            result = DispatchResult(
                cluster_id=cid,
                status=DispatchStatus.NO_RESPONDERS,
                reason=exc.detail,
            )
        results.append(result)

    return results


# ── Single dispatch ───────────────────────────────────────────────────────────


@router.post(
    "/{cluster_id}",
    summary="Dispatch responders to an incident",
    response_model=DispatchResult,
)
async def dispatch_incident(
    cluster_id: str,
    db: AsyncSession = Depends(get_db),
) -> DispatchResult:
    """
    Trigger the LangGraph dispatch pipeline for a single incident cluster.

    **Pipeline**:
    1. Fetch incident from Qdrant by `cluster_id`.
    2. Pass through LangGraph StateGraph:
       - `fetch_responders` → geo-filtered available pool
       - `run_solver` → OR-Tools SCIP optimization
       - `heuristic_assign` → greedy fallback if solver infeasible
       - `commit_assignments` → persist DispatchRecords + update responder statuses
    3. Notify responders via CommunicationAgent.
    4. Return `DispatchResult` with all assignments, ETAs, and solver metadata.
    """
    vector_store = get_vector_store()
    incident = await _fetch_incident(cluster_id, vector_store)

    orchestrator = get_orchestrator_agent(db)
    result = await orchestrator.dispatch_incident(incident)

    # Notify responders of their assignments
    if result.assignments:
        from app.agents.communication import get_communication_agent

        comm_agent = get_communication_agent()
        for assignment in result.assignments:
            try:
                await comm_agent.notify_responder_assignment(assignment, incident, db)
            except Exception as err:
                logger.warning("Failed to notify responder %s: %s", assignment.responder_id, err)

    logger.info(
        "Dispatch %s → status=%s, assigned=%d",
        cluster_id,
        result.status,
        len(result.assignments),
    )
    return result
