"""
SQLAlchemy ORM models for DisasterMesh.

Tables
------
raw_ingestion_records  — every normalised ProtoIncident row, keyed by its ID.
audit_log              — immutable append-only trail: who did what, when.
responders             — live responder registry (Phase 5).
dispatch_records       — assignment audit trail (Phase 5).
communication_logs     — every outbound message sent by CommunicationAgent (Phase 6).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RawIngestionRecord(Base):
    """
    Persists the raw payload **and** the normalised ProtoIncident produced
    by the SituationalAgent for every inbound message.
    """

    __tablename__ = "raw_ingestion_records"

    # Primary key matches ProtoIncident.id (UUID string)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # Raw input as-received (JSON blob)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Normalised ProtoIncident fields (redundant with payload but queryable)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    media_urls: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Full normalised payload (for downstream agents to replay without re-parsing)
    normalized_payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<RawIngestionRecord id={self.id!r} source={self.source_type!r}>"


class AuditLog(Base):
    """
    Immutable append-only audit trail — captures who/what/when for every
    significant action in the pipeline.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.action!r} entity={self.entity_id!r}>"


# ── Phase 5: Responder Registry ───────────────────────────────────────────────


class ResponderRecord(Base):
    """
    Live responder registry entry.

    Each row represents one response team that can be dispatched to incidents.
    Location and status fields are updated in real time as responders move and
    their assignment state changes.
    """

    __tablename__ = "responders"

    # Primary key — UUID string (matches Responder.id Pydantic field)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    # Team classification and capabilities
    # team_type: broad label e.g. "medical", "rescue", "logistics", "water"
    team_type: Mapped[str] = mapped_column(String(32), nullable=False, default="rescue")
    # capabilities: JSON dict e.g. {"medical": true, "rescue": true, "water": false}
    capabilities: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    team_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # capacity: how many parallel incident-units this team can handle
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Live location
    current_lat: Mapped[float] = mapped_column(Float, nullable=False)
    current_lon: Mapped[float] = mapped_column(Float, nullable=False)
    last_location_update: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Availability & assignment state
    # status: "available" | "assigned" | "en_route" | "on_scene"
    current_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="available", index=True
    )
    assigned_incident_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    eta_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # available_from: earliest time this team can accept a new assignment
    available_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<ResponderRecord id={self.id!r} name={self.name!r} status={self.current_status!r}>"


# ── Phase 5: Dispatch Records ─────────────────────────────────────────────────


class DispatchRecord(Base):
    """
    Immutable record of each assignment made by the Orchestrator Agent.

    Created when the OR-Tools solver (or heuristic fallback) assigns a
    responder to an incident.  Used for analytics and audit.
    """

    __tablename__ = "dispatch_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cluster_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    responder_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    eta_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    capability_match_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # optimization_method: "OPTIMAL" | "HEURISTIC_FALLBACK"
    optimization_method: Mapped[str] = mapped_column(String(32), nullable=False, default="OPTIMAL")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ASSIGNED")
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<DispatchRecord id={self.id!r} cluster={self.cluster_id!r} "
            f"responder={self.responder_id!r}>"
        )


# ── Phase 6: Communication Audit Log ─────────────────────────────────────────


class CommunicationLog(Base):
    """
    Audit log of every outbound message dispatched by the CommunicationAgent.

    A row is written for each SMS / WhatsApp / mock notification sent to
    responders or citizens, and for each situational summary generated.
    ``delivery_status`` is one of ``"sent"`` | ``"failed"`` | ``"mock"``.
    """

    __tablename__ = "communication_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Which incident this communication relates to
    incident_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # Who received this message
    # recipient_type: "responder" | "citizen" | "authority"
    recipient_type: Mapped[str] = mapped_column(String(16), nullable=False)
    recipient_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # What kind of message
    # message_type: "assignment" | "status_update" | "summary" | "test"
    message_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # How it was sent
    # channel: "sms" | "whatsapp" | "mock"
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="mock")

    # The full message body
    message_body: Mapped[str] = mapped_column(Text, nullable=False)

    # When it was sent
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    # Delivery outcome
    delivery_status: Mapped[str] = mapped_column(String(16), nullable=False, default="mock")
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<CommunicationLog id={self.id!r} incident={self.incident_id!r} "
            f"type={self.message_type!r} status={self.delivery_status!r}>"
        )
