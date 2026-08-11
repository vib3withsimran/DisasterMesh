"""
Communication Agent — Agent 6.

Responsibilities:
  - Enforce the incident lifecycle state machine:
        REPORTED → VERIFIED → ASSIGNED → EN_ROUTE → ON_SCENE → RESOLVED
  - Send SMS/WhatsApp notifications to assigned responders (with incident
    details, location, and ETA) and status-update messages to citizens.
  - Auto-detect Twilio credentials at send-time:
        credentials present → real SMS via Twilio REST API
        credentials absent  → mock mode (logs the message, no network call)
  - Store every outbound message in the ``CommunicationLog`` ORM table.
  - Generate structured, human-readable situational summaries for incident
    commanders (includes cluster_id, severity, confidence, needs breakdown,
    source provenance, assigned responders, and current status).
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CommunicationLog, DispatchRecord, ResponderRecord
from app.schemas import (
    AssignedResponderSummary,
    Assignment,
    IncidentStatus,
    SituationalSummary,
    VerifiedIncident,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifecycle state machine
# ---------------------------------------------------------------------------

#: Maps every valid ``from`` status to the list of allowed ``to`` statuses.
#: Any transition not in this mapping is illegal and raises ``ValueError``.
VALID_TRANSITIONS: dict[IncidentStatus, list[IncidentStatus]] = {
    IncidentStatus.REPORTED: [IncidentStatus.VERIFIED],
    IncidentStatus.VERIFIED: [IncidentStatus.ASSIGNED],
    IncidentStatus.ASSIGNED: [IncidentStatus.EN_ROUTE],
    IncidentStatus.EN_ROUTE: [IncidentStatus.ON_SCENE],
    IncidentStatus.ON_SCENE: [IncidentStatus.RESOLVED],
    IncidentStatus.RESOLVED: [],
}

# ---------------------------------------------------------------------------
# Citizen-facing status message templates
# ---------------------------------------------------------------------------

_CITIZEN_TEMPLATES: dict[IncidentStatus, str] = {
    IncidentStatus.REPORTED: (
        "✅ We have received your emergency report. "
        "Our teams are reviewing it now. Incident ID: {cluster_id}"
    ),
    IncidentStatus.VERIFIED: (
        "🔍 Your report has been verified and is being prioritised. Incident ID: {cluster_id}"
    ),
    IncidentStatus.ASSIGNED: (
        "🚒 Responders have been assigned to your incident and will depart shortly. "
        "Incident ID: {cluster_id}"
    ),
    IncidentStatus.EN_ROUTE: (
        "⏱️ Help is on the way! ETA: {eta_min} minutes. Incident ID: {cluster_id}"
    ),
    IncidentStatus.ON_SCENE: (
        "👨‍🚒 Responders have arrived at the scene. Incident ID: {cluster_id}"
    ),
    IncidentStatus.RESOLVED: (
        "✨ Incident {cluster_id} has been resolved. Thank you for reporting — stay safe."
    ),
}


# ---------------------------------------------------------------------------
# CommunicationAgent
# ---------------------------------------------------------------------------


class CommunicationAgent:
    """
    Handles notifications and incident lifecycle transitions.

    The agent is intentionally stateless beyond its method arguments so that
    multiple concurrent FastAPI request handlers can share a single singleton
    instance without race conditions.

    Twilio integration
    ------------------
    Checked lazily at send-time (not at construction).  When
    ``TWILIO_ACCOUNT_SID`` and ``TWILIO_AUTH_TOKEN`` are both set the agent
    sends real messages; otherwise it falls back to **mock mode** (log only).

    WhatsApp support is enabled by additionally setting
    ``TWILIO_WHATSAPP_FROM`` (the WhatsApp-enabled number, e.g.
    ``whatsapp:+14155238886``).
    """

    # ------------------------------------------------------------------
    # Public: lifecycle state machine
    # ------------------------------------------------------------------

    def transition(
        self,
        incident: VerifiedIncident,
        new_status: IncidentStatus,
    ) -> VerifiedIncident:
        """
        Apply a lifecycle state transition to *incident* (in-place).

        Parameters
        ----------
        incident:
            The ``VerifiedIncident`` whose status will be changed.
        new_status:
            The desired next status.

        Returns
        -------
        VerifiedIncident
            The same object with ``status`` mutated to *new_status*.

        Raises
        ------
        ValueError
            If *new_status* is not a valid successor of the current status,
            e.g. jumping from ``REPORTED`` directly to ``RESOLVED``.
        """
        allowed = VALID_TRANSITIONS.get(incident.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Invalid lifecycle transition: {incident.status!r} → {new_status!r}. "
                f"Allowed next states: {[s.value for s in allowed] or 'none (terminal)'}"
            )
        old_status = incident.status
        incident.status = new_status
        logger.info(
            "Incident %s lifecycle: %s → %s",
            incident.cluster_id,
            old_status,
            new_status,
        )
        return incident

    # ------------------------------------------------------------------
    # Public: notifications
    # ------------------------------------------------------------------

    async def notify_responder_assignment(
        self,
        assignment: Assignment,
        responder_name: str,
        responder_phone: str,
        incident: VerifiedIncident,
        db: AsyncSession,
    ) -> bool:
        """
        Notify a responder that they have been assigned to *incident*.

        Sends an SMS (or WhatsApp, or mock) containing:
        - Incident severity and cluster ID
        - GPS location
        - Computed ETA
        - Human-readable needs summary

        A ``CommunicationLog`` row is written regardless of delivery outcome.

        Returns
        -------
        bool
            ``True`` if the message was sent (or mocked) successfully,
            ``False`` if Twilio reported a delivery failure.
        """
        eta_min = int(assignment.eta_seconds / 60)
        needs_text = self._format_needs(incident.needs)

        body = (
            f"🚨 DISASTERMESH DISPATCH\n"
            f"Incident: {incident.cluster_id}\n"
            f"Severity: {incident.severity} | Confidence: {incident.confidence:.0%}\n"
            f"Location: {incident.lat:.5f}, {incident.lon:.5f}\n"
            f"ETA: {eta_min} min\n"
            f"Needs: {needs_text or 'General assistance'}\n"
            f"Status: {incident.status}\n"
            f"Tap to open maps: https://maps.google.com/?q={incident.lat},{incident.lon}"
        )

        success, channel, error = await self._dispatch_message(responder_phone, body)

        await self._write_log(
            db=db,
            incident_id=incident.cluster_id,
            recipient_type="responder",
            recipient_id=assignment.responder_id,
            message_type="assignment",
            channel=channel,
            message_body=body,
            delivery_status="sent" if success else "failed",
            delivery_error=error,
        )
        return success

    async def notify_citizen_status(
        self,
        phone: str,
        cluster_id: str,
        new_status: IncidentStatus,
        db: AsyncSession,
        eta_min: int | None = None,
    ) -> bool:
        """
        Send a status-update SMS to the citizen who filed the report.

        Parameters
        ----------
        phone:
            Citizen's phone number in E.164 format (e.g. ``"+919876543210"``).
        cluster_id:
            Incident cluster identifier (for reference in the message).
        new_status:
            The lifecycle state being transitioned *to*.
        db:
            Active async database session.
        eta_min:
            Minutes to arrival — only relevant for the ``EN_ROUTE`` template.

        Returns
        -------
        bool
            Delivery success flag.
        """
        template = _CITIZEN_TEMPLATES.get(new_status, "Status update for incident {cluster_id}.")
        body = template.format(cluster_id=cluster_id, eta_min=eta_min or "?")

        success, channel, error = await self._dispatch_message(phone, body)

        await self._write_log(
            db=db,
            incident_id=cluster_id,
            recipient_type="citizen",
            recipient_id=phone,
            message_type="status_update",
            channel=channel,
            message_body=body,
            delivery_status="sent" if success else "failed",
            delivery_error=error,
        )
        return success

    # ------------------------------------------------------------------
    # Public: situational summary
    # ------------------------------------------------------------------

    async def generate_situational_summary(
        self,
        incident: VerifiedIncident,
        db: AsyncSession,
    ) -> SituationalSummary:
        """
        Generate a structured, human-readable situational summary for incident
        commanders.

        Fetches all ``DispatchRecord`` rows for this cluster from the database
        and enriches them with responder names from ``ResponderRecord``.

        Parameters
        ----------
        incident:
            The ``VerifiedIncident`` to summarise.
        db:
            Active async database session.

        Returns
        -------
        SituationalSummary
            Fully populated summary including a ``human_summary`` text block.
        """
        # Fetch dispatch records for this cluster
        dispatch_rows = (
            (
                await db.execute(
                    select(DispatchRecord).where(DispatchRecord.cluster_id == incident.cluster_id)
                )
            )
            .scalars()
            .all()
        )

        # Enrich with responder names
        assigned: list[AssignedResponderSummary] = []
        for dr in dispatch_rows:
            resp_row = (
                await db.execute(
                    select(ResponderRecord).where(ResponderRecord.id == dr.responder_id)
                )
            ).scalar_one_or_none()
            assigned.append(
                AssignedResponderSummary(
                    responder_id=dr.responder_id,
                    responder_name=resp_row.name if resp_row else "(unknown)",
                    eta_seconds=dr.eta_seconds,
                    capability_match_score=dr.capability_match_score,
                )
            )

        needs = incident.needs
        needs_lines = []
        if needs.medical:
            needs_lines.append("  • Medical assistance")
        if needs.rescue:
            needs_lines.append("  • Rescue operations")
        if needs.evacuation:
            needs_lines.append("  • Evacuation support")
        if needs.shelter:
            needs_lines.append("  • Shelter provision")
        if needs.water:
            needs_lines.append("  • Water supply")
        if needs.food:
            needs_lines.append("  • Food distribution")
        needs_block = "\n".join(needs_lines) if needs_lines else "  • None identified"

        responder_lines = []
        for a in assigned:
            eta_min = int(a.eta_seconds / 60)
            responder_lines.append(
                f"  • {a.responder_name} (ID: {a.responder_id})"
                f" — ETA {eta_min} min, match {a.capability_match_score:.0%}"
            )
        responder_block = "\n".join(responder_lines) if responder_lines else "  • None assigned yet"

        now = datetime.now(UTC)
        human_summary = (
            "╔══════════════════════════════════════════╗\n"
            "║       DISASTERMESH INCIDENT SUMMARY      ║\n"
            "╚══════════════════════════════════════════╝\n"
            f"Generated : {now.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"Cluster ID: {incident.cluster_id}\n"
            f"Status    : {incident.status}\n"
            f"Severity  : {incident.severity}\n"
            f"Confidence: {incident.confidence:.0%}\n"
            f"\n"
            f"📍 Location : {incident.lat:.5f}, {incident.lon:.5f}\n"
            f"🕒 Reported : {incident.timestamp.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"📡 Sources  : {', '.join(str(s) for s in incident.source_provenance)}\n"
            f"\n"
            f"🆘 Needs:\n{needs_block}\n"
            f"\n"
            f"🚒 Assigned Responders:\n{responder_block}\n"
        )

        return SituationalSummary(
            cluster_id=incident.cluster_id,
            status=incident.status,
            severity=incident.severity,
            confidence=incident.confidence,
            lat=incident.lat,
            lon=incident.lon,
            timestamp=incident.timestamp,
            needs=incident.needs,
            source_provenance=incident.source_provenance,
            assigned_responders=assigned,
            generated_at=now,
            human_summary=human_summary,
        )

    # ------------------------------------------------------------------
    # Private: SMS / WhatsApp dispatch
    # ------------------------------------------------------------------

    async def _dispatch_message(
        self,
        to_number: str,
        body: str,
    ) -> tuple[bool, str, str | None]:
        """
        Send *body* to *to_number* via Twilio (real or WhatsApp) or mock mode.

        Returns
        -------
        tuple[bool, str, str | None]
            ``(success, channel, error_message)``
            ``channel`` is ``"sms"``, ``"whatsapp"``, or ``"mock"``.
        """
        sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        from_sms = os.getenv("TWILIO_FROM_NUMBER", "").strip()
        from_wa = os.getenv("TWILIO_WHATSAPP_FROM", "").strip()

        # ── Mock mode ────────────────────────────────────────────────
        if not (sid and token and (from_sms or from_wa)):
            logger.info(
                "[SMS MOCK] To: %s | Body:\n%s",
                to_number,
                body,
            )
            return True, "mock", None

        # ── Real Twilio ──────────────────────────────────────────────
        try:
            from twilio.rest import Client  # type: ignore[import]

            client = Client(sid, token)

            # Prefer WhatsApp if configured and number looks like WA
            if from_wa and to_number.startswith("whatsapp:"):
                msg = client.messages.create(
                    body=body,
                    from_=from_wa,
                    to=to_number,
                )
                logger.info("WhatsApp sent to %s — Twilio SID: %s", to_number, msg.sid)
                return True, "whatsapp", None
            else:
                msg = client.messages.create(
                    body=body,
                    from_=from_sms,
                    to=to_number,
                )
                logger.info("SMS sent to %s — Twilio SID: %s", to_number, msg.sid)
                return True, "sms", None

        except Exception as exc:  # noqa: BLE001
            logger.error("Twilio send failed to %s: %s", to_number, exc)
            return False, "sms", str(exc)

    # ------------------------------------------------------------------
    # Private: helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_needs(needs: Any) -> str:  # noqa: ANN401
        """Return a comma-separated human-readable needs string."""
        parts = []
        if needs.medical:
            parts.append("Medical")
        if needs.rescue:
            parts.append("Rescue")
        if needs.evacuation:
            parts.append("Evacuation")
        if needs.shelter:
            parts.append("Shelter")
        if needs.water:
            parts.append("Water")
        if needs.food:
            parts.append("Food")
        return ", ".join(parts)

    @staticmethod
    async def _write_log(
        db: AsyncSession,
        incident_id: str,
        recipient_type: str,
        recipient_id: str,
        message_type: str,
        channel: str,
        message_body: str,
        delivery_status: str,
        delivery_error: str | None,
    ) -> None:
        """Persist a ``CommunicationLog`` row and flush (but not commit)."""

        row = CommunicationLog(
            id=str(uuid4()),
            incident_id=incident_id,
            recipient_type=recipient_type,
            recipient_id=recipient_id,
            message_type=message_type,
            channel=channel,
            message_body=message_body,
            sent_at=datetime.now(UTC),
            delivery_status=delivery_status,
            delivery_error=delivery_error,
        )
        db.add(row)
        await db.flush()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_agent: CommunicationAgent | None = None


def get_communication_agent() -> CommunicationAgent:
    """Return the shared ``CommunicationAgent`` singleton."""
    global _agent  # noqa: PLW0603
    if _agent is None:
        _agent = CommunicationAgent()
    return _agent
