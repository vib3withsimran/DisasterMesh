"""
Unit tests for OrchestratorAgent (Agent 5) — Phase 5.

Tests dispatch optimization via LangGraph StateGraph & OR-Tools SCIP solver,
heuristic fallback, priority weights, capacity constraints, and batch multi-incident optimization.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.agents.orchestrator import OrchestratorAgent, _eta_seconds
from app.agents.resource import ResourceAgent
from app.schemas import (
    DispatchStatus,
    NeedsProfile,
    Priority,
    Responder,
    ResponderCapability,
    ResponderCreate,
    VerifiedIncident,
)


@pytest.mark.asyncio
async def test_dispatch_p1_assigns_2_responders(db_session):
    resource_agent = ResourceAgent(db_session)
    # Register 3 available responders
    await resource_agent.register_responder(
        ResponderCreate(
            name="R1",
            capabilities=[ResponderCapability.MEDICAL, ResponderCapability.RESCUE],
            capacity=2,
            lat=28.66,
            lon=77.23,
        )
    )
    await resource_agent.register_responder(
        ResponderCreate(
            name="R2",
            capabilities=[ResponderCapability.RESCUE, ResponderCapability.WATER],
            capacity=2,
            lat=28.67,
            lon=77.24,
        )
    )
    await resource_agent.register_responder(
        ResponderCreate(
            name="R3",
            capabilities=[ResponderCapability.LOGISTICS],
            capacity=1,
            lat=28.68,
            lon=77.25,
        )
    )

    incident = VerifiedIncident(
        cluster_id="cluster_p1",
        lat=28.665,
        lon=77.235,
        timestamp=datetime.now(UTC),
        confidence=0.95,
        severity=Priority.P1,
        needs=NeedsProfile(medical=True, rescue=True),
    )

    orchestrator = OrchestratorAgent(resource_agent, db_session)
    res = await orchestrator.dispatch_incident(incident)

    assert res.status in (DispatchStatus.ASSIGNED, DispatchStatus.HEURISTIC)
    assert len(res.assignments) >= 2
    assert res.total_capacity >= 3


@pytest.mark.asyncio
async def test_dispatch_p2_assigns_1_responder(db_session):
    resource_agent = ResourceAgent(db_session)
    await resource_agent.register_responder(
        ResponderCreate(
            name="R1",
            capabilities=[ResponderCapability.MEDICAL],
            capacity=2,
            lat=28.66,
            lon=77.23,
        )
    )

    incident = VerifiedIncident(
        cluster_id="cluster_p2",
        lat=28.665,
        lon=77.235,
        timestamp=datetime.now(UTC),
        confidence=0.8,
        severity=Priority.P2,
        needs=NeedsProfile(medical=True),
    )

    orchestrator = OrchestratorAgent(resource_agent, db_session)
    res = await orchestrator.dispatch_incident(incident)

    assert res.status in (DispatchStatus.ASSIGNED, DispatchStatus.HEURISTIC)
    assert len(res.assignments) >= 1


@pytest.mark.asyncio
async def test_dispatch_no_responders_available(db_session):
    resource_agent = ResourceAgent(db_session)
    incident = VerifiedIncident(
        cluster_id="cluster_empty",
        lat=28.665,
        lon=77.235,
        timestamp=datetime.now(UTC),
        confidence=0.8,
        severity=Priority.P1,
    )
    orchestrator = OrchestratorAgent(resource_agent, db_session)
    res = await orchestrator.dispatch_incident(incident)

    assert res.status == DispatchStatus.NO_RESPONDERS
    assert len(res.assignments) == 0


@pytest.mark.asyncio
async def test_capability_constraint_medical(db_session):
    resource_agent = ResourceAgent(db_session)
    # R1 has logistics, R2 has medical
    _ = await resource_agent.register_responder(
        ResponderCreate(
            name="Logistics",
            capabilities=[ResponderCapability.LOGISTICS],
            capacity=3,
            lat=28.66,
            lon=77.23,
        )
    )
    r2 = await resource_agent.register_responder(
        ResponderCreate(
            name="Medical",
            capabilities=[ResponderCapability.MEDICAL],
            capacity=3,
            lat=28.66,
            lon=77.23,
        )
    )

    incident = VerifiedIncident(
        cluster_id="cluster_med",
        lat=28.66,
        lon=77.23,
        timestamp=datetime.now(UTC),
        confidence=0.9,
        severity=Priority.P2,
        needs=NeedsProfile(medical=True),
    )

    orchestrator = OrchestratorAgent(resource_agent, db_session)
    res = await orchestrator.dispatch_incident(incident)

    assigned_ids = [a.responder_id for a in res.assignments]
    assert r2.id in assigned_ids


def test_eta_same_location():
    incident = VerifiedIncident(
        cluster_id="inc",
        lat=28.66,
        lon=77.23,
        timestamp=datetime.now(UTC),
        confidence=0.9,
    )
    resp = Responder(id="r1", name="R1", lat=28.66, lon=77.23)
    eta = _eta_seconds(incident, resp)
    assert eta == 0.0


@pytest.mark.asyncio
async def test_build_cost_matrix_shape(db_session):
    resource_agent = ResourceAgent(db_session)
    orchestrator = OrchestratorAgent(resource_agent, db_session)

    incidents = [
        VerifiedIncident(
            cluster_id="inc1",
            lat=28.6,
            lon=77.2,
            timestamp=datetime.now(UTC),
            confidence=0.9,
            severity=Priority.P1,
        ),
        VerifiedIncident(
            cluster_id="inc2",
            lat=28.7,
            lon=77.3,
            timestamp=datetime.now(UTC),
            confidence=0.8,
            severity=Priority.P3,
        ),
    ]
    responders = [
        Responder(id="r1", name="R1", lat=28.6, lon=77.2),
        Responder(id="r2", name="R2", lat=28.7, lon=77.3),
        Responder(id="r3", name="R3", lat=28.8, lon=77.4),
    ]

    matrix = orchestrator._build_cost_matrix(incidents, responders)
    assert len(matrix) == 2
    assert len(matrix[0]) == 3
    assert len(matrix[1]) == 3


@pytest.mark.asyncio
async def test_optimize_multi_incident(db_session):
    resource_agent = ResourceAgent(db_session)
    await resource_agent.register_responder(
        ResponderCreate(
            name="R1",
            capabilities=[ResponderCapability.MEDICAL],
            capacity=2,
            lat=28.66,
            lon=77.23,
        )
    )
    await resource_agent.register_responder(
        ResponderCreate(
            name="R2",
            capabilities=[ResponderCapability.RESCUE],
            capacity=2,
            lat=28.67,
            lon=77.24,
        )
    )

    responders = await resource_agent.list_responders()

    incidents = [
        VerifiedIncident(
            cluster_id="inc_1",
            lat=28.66,
            lon=77.23,
            timestamp=datetime.now(UTC),
            confidence=0.9,
            severity=Priority.P2,
            needs=NeedsProfile(medical=True),
        ),
        VerifiedIncident(
            cluster_id="inc_2",
            lat=28.67,
            lon=77.24,
            timestamp=datetime.now(UTC),
            confidence=0.8,
            severity=Priority.P3,
            needs=NeedsProfile(rescue=True),
        ),
    ]

    orchestrator = OrchestratorAgent(resource_agent, db_session)
    assignments = await orchestrator.optimize(incidents, responders)

    assert len(assignments) >= 2
    cluster_ids = [a.cluster_id for a in assignments]
    assert "inc_1" in cluster_ids
    assert "inc_2" in cluster_ids
