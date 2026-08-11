"""
Unit tests for ResourceAgent (Agent 4) — Phase 5.

Tests responder registration, listing, location updates, status updates,
geo-radius availability filtering, and capability match scoring.
"""

from __future__ import annotations

import pytest

from app.agents.resource import ResourceAgent
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


@pytest.mark.asyncio
async def test_register_responder(db_session):
    agent = ResourceAgent(db_session)
    data = ResponderCreate(
        name="Team Alpha",
        team_type="rescue",
        capabilities=[ResponderCapability.MEDICAL, ResponderCapability.RESCUE],
        team_size=4,
        capacity=2,
        lat=28.6670,
        lon=77.2330,
    )
    res = await agent.register_responder(data)
    assert res.id is not None
    assert res.name == "Team Alpha"
    assert res.team_type == "rescue"
    assert ResponderCapability.MEDICAL in res.capabilities
    assert ResponderCapability.RESCUE in res.capabilities
    assert res.status == ResponderStatus.AVAILABLE
    assert res.available is True


@pytest.mark.asyncio
async def test_list_responders_all(db_session):
    agent = ResourceAgent(db_session)
    r1 = await agent.register_responder(ResponderCreate(name="R1", lat=28.6, lon=77.2))
    r2 = await agent.register_responder(ResponderCreate(name="R2", lat=28.7, lon=77.3))
    all_resp = await agent.list_responders()
    assert len(all_resp) >= 2
    ids = [r.id for r in all_resp]
    assert r1.id in ids
    assert r2.id in ids


@pytest.mark.asyncio
async def test_list_responders_by_status(db_session):
    agent = ResourceAgent(db_session)
    r1 = await agent.register_responder(ResponderCreate(name="R1", lat=28.6, lon=77.2))
    r2 = await agent.register_responder(ResponderCreate(name="R2", lat=28.7, lon=77.3))
    await agent.update_responder_status(r2.id, StatusUpdate(status=ResponderStatus.ASSIGNED))

    avail = await agent.list_responders(status_filter=ResponderStatus.AVAILABLE)
    assigned = await agent.list_responders(status_filter=ResponderStatus.ASSIGNED)

    assert any(r.id == r1.id for r in avail)
    assert not any(r.id == r2.id for r in avail)
    assert any(r.id == r2.id for r in assigned)


@pytest.mark.asyncio
async def test_get_available_responders_radius(db_session):
    agent = ResourceAgent(db_session)
    # R1 in Delhi Yamuna Bazar
    r1 = await agent.register_responder(ResponderCreate(name="Near", lat=28.6667, lon=77.2333))
    # R2 in Mumbai (~1100 km away)
    r2 = await agent.register_responder(ResponderCreate(name="Far", lat=18.9400, lon=72.8240))

    incident = VerifiedIncident(
        cluster_id="cluster_test",
        lat=28.6670,
        lon=77.2340,
        timestamp="2026-08-08T00:00:00Z",
        confidence=0.9,
    )

    # 50 km radius should include Delhi, exclude Mumbai
    avail = await agent.get_available_responders(incident, radius_m=50_000)
    ids = [r.id for r in avail]
    assert r1.id in ids
    assert r2.id not in ids


@pytest.mark.asyncio
async def test_get_available_responders_excludes_assigned(db_session):
    agent = ResourceAgent(db_session)
    r1 = await agent.register_responder(ResponderCreate(name="Avail", lat=28.6667, lon=77.2333))
    r2 = await agent.register_responder(ResponderCreate(name="Busy", lat=28.6667, lon=77.2333))
    await agent.update_responder_status(r2.id, StatusUpdate(status=ResponderStatus.ASSIGNED))

    incident = VerifiedIncident(
        cluster_id="cluster_test",
        lat=28.6670,
        lon=77.2340,
        timestamp="2026-08-08T00:00:00Z",
        confidence=0.9,
    )
    avail = await agent.get_available_responders(incident)
    ids = [r.id for r in avail]
    assert r1.id in ids
    assert r2.id not in ids


@pytest.mark.asyncio
async def test_update_location(db_session):
    agent = ResourceAgent(db_session)
    r1 = await agent.register_responder(ResponderCreate(name="Mover", lat=28.6, lon=77.2))
    updated = await agent.update_responder_location(r1.id, LocationUpdate(lat=28.65, lon=77.25))
    assert updated.lat == 28.65
    assert updated.lon == 77.25
    assert updated.last_location_update is not None


@pytest.mark.asyncio
async def test_update_status_to_assigned(db_session):
    agent = ResourceAgent(db_session)
    r1 = await agent.register_responder(ResponderCreate(name="Worker", lat=28.6, lon=77.2))
    updated = await agent.update_responder_status(
        r1.id,
        StatusUpdate(status=ResponderStatus.ASSIGNED, incident_id="inc_123", eta_minutes=15),
    )
    assert updated.status == ResponderStatus.ASSIGNED
    assert updated.assigned_incident_id == "inc_123"
    assert updated.eta_minutes == 15


@pytest.mark.asyncio
async def test_update_status_to_available(db_session):
    agent = ResourceAgent(db_session)
    r1 = await agent.register_responder(ResponderCreate(name="Worker", lat=28.6, lon=77.2))
    await agent.update_responder_status(
        r1.id,
        StatusUpdate(status=ResponderStatus.ASSIGNED, incident_id="inc_123", eta_minutes=15),
    )
    # Reset to available
    reset = await agent.update_responder_status(
        r1.id, StatusUpdate(status=ResponderStatus.AVAILABLE)
    )
    assert reset.status == ResponderStatus.AVAILABLE
    assert reset.assigned_incident_id is None
    assert reset.eta_minutes is None


def test_capability_score_perfect_match(db_session):
    agent = ResourceAgent(db_session)
    _ = ResponderCreate(
        name="Team",
        capabilities=[ResponderCapability.MEDICAL, ResponderCapability.RESCUE],
        lat=0,
        lon=0,
    )
    # Convert to Pydantic Responder schema
    r = agent.needs_to_required_caps(NeedsProfile(medical=True, rescue=True))
    pydantic_resp = Responder(
        id="1",
        name="Team",
        capabilities=[ResponderCapability.MEDICAL, ResponderCapability.RESCUE],
        lat=0,
        lon=0,
    )
    score = agent.get_capability_score(pydantic_resp, r)
    assert score == 1.0


def test_capability_score_partial(db_session):
    agent = ResourceAgent(db_session)
    pydantic_resp = Responder(
        id="1",
        name="Team",
        capabilities=[ResponderCapability.MEDICAL],
        lat=0,
        lon=0,
    )
    r = agent.needs_to_required_caps(NeedsProfile(medical=True, rescue=True))
    score = agent.get_capability_score(pydantic_resp, r)
    assert score == 0.5


def test_capability_score_no_required(db_session):
    agent = ResourceAgent(db_session)
    pydantic_resp = Responder(id="1", name="Team", capabilities=[], lat=0, lon=0)
    score = agent.get_capability_score(pydantic_resp, {})
    assert score == 1.0


def test_capability_score_zero_match(db_session):
    agent = ResourceAgent(db_session)
    pydantic_resp = Responder(
        id="1",
        name="Team",
        capabilities=[ResponderCapability.LOGISTICS],
        lat=0,
        lon=0,
    )
    r = agent.needs_to_required_caps(NeedsProfile(medical=True, rescue=True))
    score = agent.get_capability_score(pydantic_resp, r)
    assert score == 0.0
