"""
Unit tests for CommunicationAgent — Phase 6.

All tests are fully mocked — no database, no Twilio, no network calls.
Tests cover:
  - Valid & invalid lifecycle state transitions
  - Mock-mode notification dispatch
  - Twilio failure handling
  - Situational summary generation
  - Broadcast callback invocation
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.communication import (
    VALID_TRANSITIONS,
    CommunicationAgent,
    get_communication_agent,
)
from app.models import CommunicationLog, DispatchRecord
from app.schemas import (
    Assignment,
    IncidentStatus,
    NeedsProfile,
    Priority,
    SourceType,
    VerifiedIncident,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_incident(
    status: IncidentStatus = IncidentStatus.REPORTED,
    severity: Priority = Priority.P1,
) -> VerifiedIncident:
    return VerifiedIncident(
        cluster_id="cluster_test-0000",
        source_provenance=[SourceType.SMS, SourceType.SATELLITE],
        lat=28.6139,
        lon=77.2090,
        timestamp=datetime(2026, 8, 8, 7, 0, 0, tzinfo=UTC),
        confidence=0.87,
        severity=severity,
        needs=NeedsProfile(medical=True, rescue=True, evacuation=False),
        media_urls=[],
        status=status,
    )


def _make_assignment() -> Assignment:
    return Assignment(
        cluster_id="cluster_test-0000",
        responder_id="resp_001",
        eta_seconds=900.0,
        capability_match_score=1.0,
        optimization_method="OPTIMAL",
    )


# ---------------------------------------------------------------------------
# State machine tests
# ---------------------------------------------------------------------------


class TestStateMachine:
    """Verify the lifecycle transition guard."""

    def setup_method(self):
        self.agent = CommunicationAgent()

    def test_reported_to_verified(self):
        inc = _make_incident(IncidentStatus.REPORTED)
        result = self.agent.transition(inc, IncidentStatus.VERIFIED)
        assert result.status == IncidentStatus.VERIFIED

    def test_verified_to_assigned(self):
        inc = _make_incident(IncidentStatus.VERIFIED)
        result = self.agent.transition(inc, IncidentStatus.ASSIGNED)
        assert result.status == IncidentStatus.ASSIGNED

    def test_assigned_to_en_route(self):
        inc = _make_incident(IncidentStatus.ASSIGNED)
        result = self.agent.transition(inc, IncidentStatus.EN_ROUTE)
        assert result.status == IncidentStatus.EN_ROUTE

    def test_en_route_to_on_scene(self):
        inc = _make_incident(IncidentStatus.EN_ROUTE)
        result = self.agent.transition(inc, IncidentStatus.ON_SCENE)
        assert result.status == IncidentStatus.ON_SCENE

    def test_on_scene_to_resolved(self):
        inc = _make_incident(IncidentStatus.ON_SCENE)
        result = self.agent.transition(inc, IncidentStatus.RESOLVED)
        assert result.status == IncidentStatus.RESOLVED

    def test_full_chain(self):
        """Walk the entire happy path in one test."""
        agent = self.agent
        inc = _make_incident(IncidentStatus.REPORTED)
        chain = [
            IncidentStatus.VERIFIED,
            IncidentStatus.ASSIGNED,
            IncidentStatus.EN_ROUTE,
            IncidentStatus.ON_SCENE,
            IncidentStatus.RESOLVED,
        ]
        for next_status in chain:
            inc = agent.transition(inc, next_status)
        assert inc.status == IncidentStatus.RESOLVED

    def test_invalid_reported_to_resolved(self):
        """Skipping states must raise ValueError."""
        inc = _make_incident(IncidentStatus.REPORTED)
        with pytest.raises(ValueError, match="REPORTED"):
            self.agent.transition(inc, IncidentStatus.RESOLVED)

    def test_invalid_reported_to_assigned(self):
        inc = _make_incident(IncidentStatus.REPORTED)
        with pytest.raises(ValueError):
            self.agent.transition(inc, IncidentStatus.ASSIGNED)

    def test_invalid_verified_to_en_route(self):
        inc = _make_incident(IncidentStatus.VERIFIED)
        with pytest.raises(ValueError, match="EN_ROUTE"):
            self.agent.transition(inc, IncidentStatus.EN_ROUTE)

    def test_invalid_transition_from_terminal_resolved(self):
        """RESOLVED → anything must raise ValueError."""
        inc = _make_incident(IncidentStatus.RESOLVED)
        for next_status in IncidentStatus:
            if next_status != IncidentStatus.RESOLVED:
                with pytest.raises(ValueError):
                    self.agent.transition(inc, next_status)

    def test_valid_transitions_dict_completeness(self):
        """Every IncidentStatus must have an entry in VALID_TRANSITIONS."""
        for status in IncidentStatus:
            assert status in VALID_TRANSITIONS, f"Missing entry for {status} in VALID_TRANSITIONS"

    def test_transition_mutates_in_place(self):
        """transition() must return the same object (mutated), not a copy."""
        inc = _make_incident(IncidentStatus.REPORTED)
        original_id = id(inc)
        result = self.agent.transition(inc, IncidentStatus.VERIFIED)
        assert id(result) == original_id


# ---------------------------------------------------------------------------
# Notification mock-mode tests
# ---------------------------------------------------------------------------


class TestNotificationMockMode:
    """Verify notification dispatch works in demo mode (no Twilio credentials)."""

    def setup_method(self):
        self.agent = CommunicationAgent()

    @pytest.mark.asyncio
    async def test_notify_responder_mock_returns_true(self):
        """notify_responder_assignment returns True in mock mode."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        assignment = _make_assignment()
        incident = _make_incident(IncidentStatus.ASSIGNED)

        # Ensure Twilio env vars are absent
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TWILIO_ACCOUNT_SID", None)
            os.environ.pop("TWILIO_AUTH_TOKEN", None)
            os.environ.pop("TWILIO_FROM_NUMBER", None)

            result = await self.agent.notify_responder_assignment(
                assignment=assignment,
                responder_name="Alpha Team",
                responder_phone="+919876543210",
                incident=incident,
                db=db,
            )

        assert result is True
        db.add.assert_called_once()
        # The object added must be a CommunicationLog
        added_obj = db.add.call_args[0][0]
        assert isinstance(added_obj, CommunicationLog)
        assert added_obj.delivery_status == "sent"
        assert added_obj.channel == "mock"
        assert added_obj.message_type == "assignment"
        assert added_obj.recipient_type == "responder"

    @pytest.mark.asyncio
    async def test_notify_responder_message_contains_key_fields(self):
        """Assignment notification body must include ETA, severity, and coords."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        assignment = _make_assignment()  # eta_seconds=900 → 15 min
        incident = _make_incident(IncidentStatus.ASSIGNED)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TWILIO_ACCOUNT_SID", None)
            os.environ.pop("TWILIO_AUTH_TOKEN", None)
            await self.agent.notify_responder_assignment(
                assignment=assignment,
                responder_name="Alpha Team",
                responder_phone="+919876543210",
                incident=incident,
                db=db,
            )

        body = db.add.call_args[0][0].message_body
        assert "15 min" in body
        assert "P1" in body
        assert "28.6139" in body
        assert "77.2090" in body

    @pytest.mark.asyncio
    async def test_notify_citizen_mock_returns_true(self):
        """notify_citizen_status returns True in mock mode."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TWILIO_ACCOUNT_SID", None)
            os.environ.pop("TWILIO_AUTH_TOKEN", None)

            result = await self.agent.notify_citizen_status(
                phone="+919876543210",
                cluster_id="cluster_test-0000",
                new_status=IncidentStatus.EN_ROUTE,
                db=db,
                eta_min=15,
            )

        assert result is True
        added_obj = db.add.call_args[0][0]
        assert isinstance(added_obj, CommunicationLog)
        assert added_obj.delivery_status == "sent"
        assert added_obj.recipient_type == "citizen"
        assert added_obj.message_type == "status_update"

    @pytest.mark.asyncio
    async def test_all_citizen_templates_covered(self):
        """Every IncidentStatus must produce a non-empty citizen message."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TWILIO_ACCOUNT_SID", None)
            os.environ.pop("TWILIO_AUTH_TOKEN", None)

            for status in IncidentStatus:
                db.add.reset_mock()
                await self.agent.notify_citizen_status(
                    phone="+919876543210",
                    cluster_id="cluster_test-0000",
                    new_status=status,
                    db=db,
                )
                body = db.add.call_args[0][0].message_body
                assert body, f"Empty message body for status {status}"
                assert "cluster_test-0000" in body

    @pytest.mark.asyncio
    async def test_twilio_failure_logs_error_status(self):
        """When Twilio raises, delivery_status must be 'failed'."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        # Simulate Twilio credentials being present but the client raising
        with (
            patch.dict(
                os.environ,
                {
                    "TWILIO_ACCOUNT_SID": "ACtest123",
                    "TWILIO_AUTH_TOKEN": "authtest",
                    "TWILIO_FROM_NUMBER": "+15550001234",
                },
            ),
            patch("app.agents.communication.CommunicationAgent._dispatch_message") as mock_dispatch,
        ):
            mock_dispatch.return_value = (False, "sms", "Twilio error: authentication failed")

            result = await self.agent.notify_citizen_status(
                phone="+919876543210",
                cluster_id="cluster_test-0000",
                new_status=IncidentStatus.ASSIGNED,
                db=db,
            )

        assert result is False
        added_obj = db.add.call_args[0][0]
        assert added_obj.delivery_status == "failed"
        assert added_obj.delivery_error is not None


# ---------------------------------------------------------------------------
# Situational summary tests
# ---------------------------------------------------------------------------


class TestSituationalSummary:
    """Verify the structured summary generator."""

    @pytest.mark.asyncio
    async def test_summary_has_all_required_fields(self):
        agent = CommunicationAgent()
        incident = _make_incident(IncidentStatus.EN_ROUTE)

        # Mock DB session: no dispatch records found
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        summary = await agent.generate_situational_summary(incident, db)

        assert summary.cluster_id == "cluster_test-0000"
        assert summary.status == IncidentStatus.EN_ROUTE
        assert summary.severity == Priority.P1
        assert abs(summary.confidence - 0.87) < 0.001
        assert summary.lat == 28.6139
        assert summary.lon == 77.2090
        assert isinstance(summary.needs, NeedsProfile)
        assert isinstance(summary.assigned_responders, list)
        assert isinstance(summary.human_summary, str)
        assert isinstance(summary.generated_at, datetime)

    @pytest.mark.asyncio
    async def test_summary_human_text_contains_key_info(self):
        agent = CommunicationAgent()
        incident = _make_incident(IncidentStatus.ASSIGNED)

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        summary = await agent.generate_situational_summary(incident, db)

        text = summary.human_summary
        assert "cluster_test-0000" in text
        assert "P1" in text
        assert "87%" in text  # confidence formatted as percentage
        assert "ASSIGNED" in text

    @pytest.mark.asyncio
    async def test_summary_includes_assigned_responders(self):
        """When dispatch records exist, they should appear in the summary."""
        from app.models import ResponderRecord

        agent = CommunicationAgent()
        incident = _make_incident(IncidentStatus.EN_ROUTE)

        # Build mock dispatch record ORM object
        mock_dr = MagicMock(spec=DispatchRecord)
        mock_dr.responder_id = "resp_001"
        mock_dr.eta_seconds = 600.0
        mock_dr.capability_match_score = 0.9

        # Build mock responder record ORM object
        mock_rr = MagicMock(spec=ResponderRecord)
        mock_rr.name = "Alpha Team"

        db = AsyncMock()

        # First execute call → dispatch records; second → responder lookup
        mock_dispatch_result = MagicMock()
        mock_dispatch_result.scalars.return_value.all.return_value = [mock_dr]

        mock_resp_result = MagicMock()
        mock_resp_result.scalar_one_or_none.return_value = mock_rr

        db.execute = AsyncMock(side_effect=[mock_dispatch_result, mock_resp_result])

        summary = await agent.generate_situational_summary(incident, db)

        assert len(summary.assigned_responders) == 1
        ar = summary.assigned_responders[0]
        assert ar.responder_id == "resp_001"
        assert ar.responder_name == "Alpha Team"
        assert ar.eta_seconds == 600.0

    @pytest.mark.asyncio
    async def test_summary_needs_breakdown_in_text(self):
        """Needs flags should appear in the human summary text."""
        agent = CommunicationAgent()
        incident = _make_incident(IncidentStatus.VERIFIED)
        incident.needs = NeedsProfile(medical=True, rescue=True, evacuation=False, shelter=False)

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        summary = await agent.generate_situational_summary(incident, db)

        text = summary.human_summary
        assert "Medical" in text
        assert "Rescue" in text
        # Evacuation is False so it should not appear as a bullet
        assert "Evacuation" not in text


# ---------------------------------------------------------------------------
# Singleton test
# ---------------------------------------------------------------------------


def test_get_communication_agent_returns_singleton():
    a1 = get_communication_agent()
    a2 = get_communication_agent()
    assert a1 is a2
    assert isinstance(a1, CommunicationAgent)
