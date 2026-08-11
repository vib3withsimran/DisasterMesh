"""Responders router — CRUD for the live responder registry (Phase 5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.resource import get_resource_agent
from app.db import get_db
from app.schemas import (
    LocationUpdate,
    Responder,
    ResponderCreate,
    ResponderStatus,
    StatusUpdate,
)

router = APIRouter()


# ── List / create ─────────────────────────────────────────────────────────────


@router.get("", summary="List responders", response_model=list[Responder])
async def list_responders(
    status: ResponderStatus | None = Query(
        default=None,
        description="Filter by operational status (available / assigned / en_route / on_scene).",
    ),
    db: AsyncSession = Depends(get_db),
) -> list[Responder]:
    """
    Return all registered responders, optionally filtered by status.

    Examples
    --------
    ``GET /responders`` — all responders
    ``GET /responders?status=available`` — only available teams
    """
    agent = get_resource_agent(db)
    return await agent.list_responders(status_filter=status)


@router.post("", summary="Register a new responder", response_model=Responder, status_code=201)
async def create_responder(
    body: ResponderCreate,
    db: AsyncSession = Depends(get_db),
) -> Responder:
    """
    Add a new responder team to the registry.

    The responder starts in **available** status at the supplied GPS coordinates.
    """
    agent = get_resource_agent(db)
    return await agent.register_responder(body)


# ── Single responder ──────────────────────────────────────────────────────────


@router.get("/{responder_id}", summary="Get a single responder", response_model=Responder)
async def get_responder(
    responder_id: str,
    db: AsyncSession = Depends(get_db),
) -> Responder:
    """Fetch a responder by ID."""
    agent = get_resource_agent(db)
    responder = await agent.get_responder(responder_id)
    if responder is None:
        raise HTTPException(status_code=404, detail=f"Responder '{responder_id}' not found")
    return responder


# ── Location update ───────────────────────────────────────────────────────────


@router.put(
    "/{responder_id}/location",
    summary="Update responder GPS location",
    response_model=Responder,
)
async def update_location(
    responder_id: str,
    body: LocationUpdate,
    db: AsyncSession = Depends(get_db),
) -> Responder:
    """
    Update a responder's current GPS coordinates.

    Called by a mobile app or fleet-tracking system as the team moves.
    """
    agent = get_resource_agent(db)
    updated = await agent.update_responder_location(responder_id, body)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Responder '{responder_id}' not found")
    return updated


# ── Status update ─────────────────────────────────────────────────────────────


@router.put(
    "/{responder_id}/status",
    summary="Update responder operational status",
    response_model=Responder,
)
async def update_status(
    responder_id: str,
    body: StatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> Responder:
    """
    Transition a responder's status through the operational lifecycle:

    ``available → assigned → en_route → on_scene → available``

    Transitioning back to **available** automatically clears the
    `assigned_incident_id` and `eta_minutes` fields.
    """
    agent = get_resource_agent(db)
    updated = await agent.update_responder_status(responder_id, body)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Responder '{responder_id}' not found")
    return updated
