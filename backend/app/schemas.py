"""
Canonical Pydantic schemas for DisasterMesh.

These models are the shared language between all six agents.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

# ── Enums ─────────────────────────────────────────────────────────────────────


class SourceType(StrEnum):
    SMS = "sms"
    WHATSAPP = "whatsapp"
    WEB_FORM = "web_form"
    TWEET = "tweet"
    SATELLITE = "satellite"
    IOT_SENSOR = "iot_sensor"
    NEWS = "news"


class IncidentStatus(StrEnum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    ASSIGNED = "ASSIGNED"
    EN_ROUTE = "EN_ROUTE"
    ON_SCENE = "ON_SCENE"
    RESOLVED = "RESOLVED"


class Priority(StrEnum):
    P1 = "P1"  # Critical — immediate life threat
    P2 = "P2"  # High
    P3 = "P3"  # Medium
    P4 = "P4"  # Low


class ResponderStatus(StrEnum):
    """Live operational status of a responder team."""

    AVAILABLE = "available"
    ASSIGNED = "assigned"
    EN_ROUTE = "en_route"
    ON_SCENE = "on_scene"


class DispatchStatus(StrEnum):
    """Outcome status of an Orchestrator dispatch attempt."""

    ASSIGNED = "ASSIGNED"
    NO_RESPONDERS = "NO_RESPONDERS_AVAILABLE"
    SOLVER_INFEASIBLE = "SOLVER_INFEASIBLE"
    HEURISTIC = "HEURISTIC_FALLBACK"


# ── Ingestion models (input to Situational Agent) ─────────────────────────────


class ProtoIncident(BaseModel):
    """Normalized incident before verification and deduplication."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    source: SourceType
    text: str
    lat: float | None = None
    lon: float | None = None
    address: str | None = None  # fallback for geocoding
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    media_urls: list[str] = []
    metadata: dict[str, Any] = {}
    raw_payload: dict[str, Any] = {}  # original input preserved for audit


class CitizenReportInput(BaseModel):
    source: SourceType = SourceType.SMS
    text: str
    lat: float | None = None
    lon: float | None = None
    address: str | None = None
    timestamp: datetime | None = None
    media_urls: list[str] = []


class SocialPostInput(BaseModel):
    source: SourceType = SourceType.TWEET
    text: str
    url: str | None = None
    lat: float | None = None
    lon: float | None = None
    timestamp: datetime | None = None


class SatellitePolygonInput(BaseModel):
    source: SourceType = SourceType.SATELLITE
    geojson: dict[str, Any]  # GeoJSON Feature or FeatureCollection
    timestamp: datetime | None = None
    media_urls: list[str] = []


class SensorStreamInput(BaseModel):
    source: SourceType = SourceType.IOT_SENSOR
    sensor_id: str
    sensor_type: str  # e.g. "water_level", "air_quality"
    value: float
    unit: str
    lat: float
    lon: float
    timestamp: datetime | None = None


# ── Needs & severity (output of Victim Agent) ─────────────────────────────────


class NeedsProfile(BaseModel):
    medical: bool = False
    shelter: bool = False
    evacuation: bool = False
    rescue: bool = False
    water: bool = False
    food: bool = False


class ParsedIntake(BaseModel):
    """
    Structured extraction produced by the LLM Smart Intake Layer (IntakeParserAgent).

    Extracted from raw unstructured free-text in any language (English, Hindi, Hinglish, etc.).
    """

    address: str | None = Field(
        default=None,
        description="Extracted location address or landmark, e.g. 'Yamuna Bazar, Delhi'",
    )
    lat: float | None = Field(default=None, description="Explicit latitude if provided in raw text")
    lon: float | None = Field(
        default=None, description="Explicit longitude if provided in raw text"
    )
    language: str = Field(
        default="en", description="Detected language code, e.g. 'hi', 'en', 'hinglish'"
    )
    incident_type: str = Field(
        default="other",
        description="Type of incident, e.g. 'flood', 'fire', 'building_collapse', 'medical_emergency'",
    )
    needs: NeedsProfile = Field(
        default_factory=NeedsProfile, description="Extracted victim needs profile"
    )
    urgency_level: int = Field(
        default=1, ge=1, le=5, description="Urgency scale 1 (low) to 5 (extreme SOS/life threat)"
    )
    time_reference: str | None = Field(
        default=None, description="Extracted time reference string, e.g. 'since 2 hours ago'"
    )
    cleaned_text: str = Field(
        default="", description="Normalized English translation / summary of the report text"
    )


class SeverityAssessment(BaseModel):
    needs: NeedsProfile
    severity_score: float = Field(ge=0.0, le=1.0)
    priority: Priority
    factors: dict[str, float] = {}  # breakdown of scoring factors


class AssessRequest(BaseModel):
    """
    Request body for ``POST /incidents/{cluster_id}/assess``.

    Carries the full ``VerifiedIncident`` payload plus the original
    report text used for bilingual keyword extraction (since
    ``VerifiedIncident`` does not store the raw text).
    """

    cluster_id: str
    source_provenance: list[SourceType] = []
    lat: float
    lon: float
    timestamp: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    severity: Priority = Priority.P4
    needs: NeedsProfile = Field(default_factory=NeedsProfile)
    media_urls: list[str] = []
    status: IncidentStatus = IncidentStatus.VERIFIED
    text: str = ""  # free-form report text for needs extraction


# ── Verified incident (shared across agents 3–6) ──────────────────────────────


class VerifiedIncident(BaseModel):
    cluster_id: str = Field(default_factory=lambda: f"cluster_{uuid4()}")
    source_provenance: list[SourceType] = []
    lat: float
    lon: float
    timestamp: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    severity: Priority = Priority.P4
    needs: NeedsProfile = Field(default_factory=NeedsProfile)
    media_urls: list[str] = []
    status: IncidentStatus = IncidentStatus.REPORTED


# ── Responder / Resource models (Resource Agent) ──────────────────────────────


class ResponderCapability(StrEnum):
    MEDICAL = "medical"
    RESCUE = "rescue"
    WATER = "water"
    LOGISTICS = "logistics"
    EVACUATION = "evacuation"


class Responder(BaseModel):
    """Full responder representation — used by Resource Agent and API responses."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    team_type: str = "rescue"
    capabilities: list[ResponderCapability] = []
    team_size: int = 1
    capacity: int = 1
    lat: float
    lon: float
    # backward-compat alias kept alongside the richer status field
    available: bool = True
    status: ResponderStatus = ResponderStatus.AVAILABLE
    assigned_incident_id: str | None = None
    eta_minutes: int | None = None
    last_location_update: datetime | None = None
    available_from: datetime | None = None


# ── Responder CRUD request schemas (Resource Agent API) ───────────────────────


class ResponderCreate(BaseModel):
    """Request body for ``POST /responders``."""

    name: str
    team_type: str = "rescue"
    capabilities: list[ResponderCapability] = []
    team_size: int = Field(default=1, ge=1)
    capacity: int = Field(default=1, ge=1)
    lat: float
    lon: float


class LocationUpdate(BaseModel):
    """Request body for ``PUT /responders/{id}/location``."""

    lat: float
    lon: float


class StatusUpdate(BaseModel):
    """Request body for ``PUT /responders/{id}/status``."""

    status: ResponderStatus
    incident_id: str | None = None
    eta_minutes: int | None = None


# ── Dispatch / Assignment (Orchestrator Agent) ────────────────────────────────


class Assignment(BaseModel):
    """Single responder-to-incident assignment produced by the Orchestrator."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    cluster_id: str
    responder_id: str
    eta_seconds: float
    # How well the responder's capabilities match the incident needs (0.0–1.0)
    capability_match_score: float = Field(default=1.0, ge=0.0, le=1.0)
    # Which method produced this assignment
    optimization_method: str = "OPTIMAL"  # "OPTIMAL" | "HEURISTIC_FALLBACK"
    route: dict[str, Any] = {}
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DispatchResult(BaseModel):
    """Aggregated result returned by the Orchestrator for one incident."""

    cluster_id: str
    status: DispatchStatus
    assignments: list[Assignment] = []
    # Minimum ETA across all assigned responders (seconds)
    min_eta_seconds: float = 0.0
    # Sum of capacities across all assigned responders
    total_capacity: int = 0
    solver_status: str = ""
    reason: str = ""


# ── API response helpers ───────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    environment: str


class IngestResponse(BaseModel):
    status: str = "received"
    message_id: str
    lat: float | None = None  # resolved coordinates (None if geocoding failed)
    lon: float | None = None


# ── Internal carrier types (not serialized) ───────────────────────────────────


from dataclasses import dataclass, field  # noqa: E402


@dataclass
class ClusterMatchResult:
    """
    Intermediate result of the 3-D clustering step inside VerificationAgent.

    Not a Pydantic model — this is a pure in-process carrier type that is never
    serialized to JSON or stored in any database.

    Fields
    ------
    cluster_id
        The cluster to join (may be a pre-existing one or a freshly-generated
        ``cluster_{uuid4()}``).
    members
        Raw Qdrant payload dicts for every proto-incident already in the cluster.
    member_vectors
        Stored embedding vectors corresponding to ``members`` (same order).
    similarity_scores
        Cosine similarity between the incoming proto's vector and each member
        vector (same order as ``members``).
    """

    cluster_id: str
    members: list[dict] = field(default_factory=list)
    member_vectors: list[list[float]] = field(default_factory=list)
    similarity_scores: list[float] = field(default_factory=list)


# ── Phase 6: Communication Agent schemas ──────────────────────────────────────


class StatusTransitionRequest(BaseModel):
    """
    Request body for ``POST /incidents/{cluster_id}/status``.

    ``citizen_phone`` is optional — if provided the CommunicationAgent will
    send a status-update SMS to the reporter.
    """

    new_status: IncidentStatus
    reason: str | None = None
    citizen_phone: str | None = None  # E.164 format e.g. "+919876543210"


class AssignedResponderSummary(BaseModel):
    """Per-responder row inside a SituationalSummary."""

    responder_id: str
    responder_name: str
    eta_seconds: float
    capability_match_score: float


class SituationalSummary(BaseModel):
    """
    Structured, human-readable summary for incident commanders.

    Returned by ``GET /incidents/{cluster_id}/summary``.
    ``human_summary`` is a pre-formatted text block suitable for display
    in a dashboard or sending as a digest message.
    """

    cluster_id: str
    status: IncidentStatus
    severity: Priority
    confidence: float
    lat: float
    lon: float
    timestamp: datetime
    needs: NeedsProfile
    source_provenance: list[SourceType]
    assigned_responders: list[AssignedResponderSummary] = []
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    human_summary: str


class CommLogEntry(BaseModel):
    """API response shape for entries returned by ``GET /communications/logs``."""

    id: str
    incident_id: str
    recipient_type: str
    recipient_id: str
    message_type: str
    channel: str
    message_body: str
    sent_at: datetime
    delivery_status: str
    delivery_error: str | None = None

    model_config = {"from_attributes": True}
