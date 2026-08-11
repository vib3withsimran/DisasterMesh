"""
Resource Agent — Agent 4.

Responsibilities:
  - Maintain live responder registry (SQLite via SQLAlchemy async)
  - Return available responders filtered by geo-radius and capabilities
  - Update responder location and operational status
  - Score how well a responder's capabilities match an incident's needs

Implemented in Phase 5.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ResponderRecord
from app.schemas import (
    LocationUpdate,
    NeedsProfile,
    Responder,
    ResponderCapability,
    ResponderCreate,
    ResponderStatus,
    StatusUpdate,
    VerifiedIncident,
)

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two lat/lon points."""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * asin(sqrt(a)) * 6_371_000  # Earth radius in metres


def _record_to_schema(rec: ResponderRecord) -> Responder:
    """Convert an ORM row to the Pydantic Responder schema."""
    caps = [
        ResponderCapability(k)
        for k, v in (rec.capabilities or {}).items()
        if v and k in ResponderCapability.__members__.values()  # type: ignore[attr-defined]
    ]
    status = (
        ResponderStatus(rec.current_status) if rec.current_status else ResponderStatus.AVAILABLE
    )
    return Responder(
        id=rec.id,
        name=rec.name,
        team_type=rec.team_type,
        capabilities=caps,
        team_size=rec.team_size,
        capacity=rec.capacity,
        lat=rec.current_lat,
        lon=rec.current_lon,
        available=(status == ResponderStatus.AVAILABLE),
        status=status,
        assigned_incident_id=rec.assigned_incident_id,
        eta_minutes=rec.eta_minutes,
        last_location_update=rec.last_location_update,
        available_from=rec.available_from,
    )


# ── Resource Agent ────────────────────────────────────────────────────────────


class ResourceAgent:
    """
    Tracks and queries the live responder registry.

    All mutations are committed within the caller-supplied AsyncSession
    (lifecycle managed by the FastAPI `get_db` dependency).
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def register_responder(self, data: ResponderCreate) -> Responder:
        """
        Create a new responder entry in the registry.

        Returns the full Responder schema for the newly created row.
        """
        caps_dict = {cap.value: True for cap in data.capabilities}
        now = datetime.now(UTC)
        rec = ResponderRecord(
            id=str(uuid4()),
            name=data.name,
            team_type=data.team_type,
            capabilities=caps_dict,
            team_size=data.team_size,
            capacity=data.capacity,
            current_lat=data.lat,
            current_lon=data.lon,
            current_status=ResponderStatus.AVAILABLE,
            last_location_update=now,
            available_from=now,
        )
        self.db.add(rec)
        await self.db.flush()  # get the id without committing (caller commits)
        logger.info("Registered responder %s (%s)", rec.id, rec.name)
        return _record_to_schema(rec)

    async def list_responders(
        self, status_filter: ResponderStatus | None = None
    ) -> list[Responder]:
        """Return all responders, optionally filtered by status."""
        stmt = select(ResponderRecord)
        if status_filter is not None:
            stmt = stmt.where(ResponderRecord.current_status == status_filter.value)
        result = await self.db.execute(stmt)
        return [_record_to_schema(r) for r in result.scalars().all()]

    async def get_responder(self, responder_id: str) -> Responder | None:
        """Fetch a single responder by id; returns None if not found."""
        rec = await self.db.get(ResponderRecord, responder_id)
        return _record_to_schema(rec) if rec else None

    # ── Location & status updates ─────────────────────────────────────────────

    async def update_responder_location(
        self, responder_id: str, update: LocationUpdate
    ) -> Responder | None:
        """
        Update a responder's GPS position.

        Returns the updated Responder, or None if the id is unknown.
        """
        rec = await self.db.get(ResponderRecord, responder_id)
        if rec is None:
            logger.warning("update_location: unknown responder %s", responder_id)
            return None
        rec.current_lat = update.lat
        rec.current_lon = update.lon
        rec.last_location_update = datetime.now(UTC)
        await self.db.flush()
        logger.debug("Updated location for %s → (%.5f, %.5f)", responder_id, update.lat, update.lon)
        return _record_to_schema(rec)

    async def update_responder_status(
        self, responder_id: str, update: StatusUpdate
    ) -> Responder | None:
        """
        Update a responder's operational status.

        When transitioning back to 'available', clears the incident assignment.
        Returns the updated Responder, or None if the id is unknown.
        """
        rec = await self.db.get(ResponderRecord, responder_id)
        if rec is None:
            logger.warning("update_status: unknown responder %s", responder_id)
            return None

        rec.current_status = update.status.value
        now = datetime.now(UTC)
        if update.status == ResponderStatus.AVAILABLE:
            # Clear assignment fields when returning to available pool
            rec.assigned_incident_id = None
            rec.eta_minutes = None
            rec.available_from = now
        else:
            if update.incident_id is not None:
                rec.assigned_incident_id = update.incident_id
            if update.eta_minutes is not None:
                rec.eta_minutes = update.eta_minutes
                rec.available_from = now + timedelta(minutes=update.eta_minutes)
            else:
                rec.available_from = now + timedelta(hours=2)

        await self.db.flush()
        logger.info(
            "Responder %s status → %s (incident=%s)",
            responder_id,
            update.status,
            rec.assigned_incident_id,
        )
        return _record_to_schema(rec)

    # ── Availability query ────────────────────────────────────────────────────

    async def get_available_responders(
        self,
        incident: VerifiedIncident,
        radius_m: float = 50_000,
    ) -> list[Responder]:
        """
        Return responders that are available and within *radius_m* metres of
        the incident, sorted by distance (nearest first).

        Availability rules:
        - status == "available", OR
        - status == "assigned" AND available_from <= now  (finishing soon)

        Parameters
        ----------
        incident:   incident whose location defines the search centre.
        radius_m:   geo-radius filter (default 50 km).
        """
        now = datetime.now(UTC)
        stmt = select(ResponderRecord).where(
            (ResponderRecord.current_status == ResponderStatus.AVAILABLE.value)
            | (
                (ResponderRecord.current_status == ResponderStatus.ASSIGNED.value)
                & (ResponderRecord.available_from <= now)
            )
        )
        result = await self.db.execute(stmt)
        all_available = result.scalars().all()

        # Server-side Haversine filter (Qdrant-free — responder table is small)
        nearby: list[tuple[float, ResponderRecord]] = []
        if incident.lat is not None and incident.lon is not None:
            for rec in all_available:
                dist = _haversine_m(incident.lat, incident.lon, rec.current_lat, rec.current_lon)
                if dist <= radius_m:
                    nearby.append((dist, rec))
        else:
            # No incident location — return all available, distance unknown
            nearby = [(0.0, rec) for rec in all_available]

        nearby.sort(key=lambda t: t[0])
        return [_record_to_schema(rec) for _, rec in nearby]

    # ── Capability scoring ────────────────────────────────────────────────────

    def get_capability_score(
        self,
        responder: Responder,
        required_capabilities: dict[str, bool],
    ) -> float:
        """
        Score how well *responder* matches the incident's required capabilities.

        Returns
        -------
        1.0  if all required capabilities are present (or none are required).
        0.0  if the responder has none of the required capabilities.
        partial  proportion of matched requirements otherwise.
        """
        required = [cap for cap, needed in required_capabilities.items() if needed]
        if not required:
            return 1.0

        responder_caps = {c.value for c in responder.capabilities}
        matched = sum(1 for cap in required if cap in responder_caps)
        return matched / len(required)

    # ── Needs-to-capabilities mapping ────────────────────────────────────────

    @staticmethod
    def needs_to_required_caps(needs: NeedsProfile) -> dict[str, bool]:
        """
        Convert a NeedsProfile to the capability dict expected by the solver.

        ``water`` maps to the ResponderCapability.WATER tag.
        ``evacuation`` or ``shelter`` maps to ``logistics``.
        """
        return {
            ResponderCapability.MEDICAL: needs.medical,
            ResponderCapability.RESCUE: needs.rescue,
            ResponderCapability.WATER: needs.water,
            ResponderCapability.LOGISTICS: needs.evacuation or needs.shelter,
            ResponderCapability.EVACUATION: needs.evacuation,
        }


# ── Singleton factory ─────────────────────────────────────────────────────────

# One ResourceAgent per DB session — callers supply the session.
# No module-level singleton needed here since the agent is stateless
# between requests (all state lives in the DB).


def get_resource_agent(db: AsyncSession) -> ResourceAgent:
    """Return a ResourceAgent bound to *db* (a per-request AsyncSession)."""
    return ResourceAgent(db)
