"""
Unit tests for VerificationAgent — Phase 3.

All tests mock VectorStore and EmbeddingService so no Qdrant instance or
model download is required.  Tests run in isolation and finish in < 1 second
each.

Run:
    cd backend
    pytest app/tests/unit/test_verification_unit.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.verification import VerificationAgent
from app.schemas import (
    IncidentStatus,
    ProtoIncident,
    SourceType,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

YAMUNA_LAT = 28.6667
YAMUNA_LON = 77.2333

FAKE_VECTOR: list[float] = [0.1] * 384


def _proto(
    text: str = "Water rising near Yamuna Bazar",
    lat: float = YAMUNA_LAT,
    lon: float = YAMUNA_LON,
    source: SourceType = SourceType.SMS,
    age_hours: float = 0.0,
) -> ProtoIncident:
    """Return a minimal ProtoIncident for testing."""
    ts = datetime.now(UTC) - timedelta(hours=age_hours)
    return ProtoIncident(
        source=source,
        text=text,
        lat=lat,
        lon=lon,
        timestamp=ts,
    )


def _mock_agent(
    nearby_payloads: list[dict] | None = None,
    payload_vectors: list[tuple[dict, list[float]]] | None = None,
) -> VerificationAgent:
    """
    Build a VerificationAgent whose VectorStore and EmbeddingService are fully
    mocked.

    Parameters
    ----------
    nearby_payloads:
        What VectorStore.search_nearby() should return.
    payload_vectors:
        What VectorStore.get_vectors_by_filter() should return.
    """
    mock_store = MagicMock()

    async def _mock_search_nearby(*args, **kwargs):
        payloads = nearby_payloads or []
        if kwargs.get("with_vectors"):
            return [(p, FAKE_VECTOR) for p in payloads]
        return payloads

    mock_store.search_nearby = AsyncMock(side_effect=_mock_search_nearby)
    mock_store.get_vectors_by_filter = AsyncMock(return_value=payload_vectors or [])
    mock_store.upsert_verified = AsyncMock(return_value=None)

    mock_embedder = MagicMock()
    mock_embedder.embed_incident = AsyncMock(return_value=FAKE_VECTOR)
    mock_embedder.embed_text = AsyncMock(return_value=FAKE_VECTOR)

    return VerificationAgent(
        vector_store=mock_store,
        embedding_service=mock_embedder,
    )


# ── Haversine ─────────────────────────────────────────────────────────────────


def test_haversine_zero() -> None:
    """Same point → 0 m."""
    assert VerificationAgent._haversine(28.6, 77.2, 28.6, 77.2) == pytest.approx(0.0, abs=1e-6)


def test_haversine_known_distance() -> None:
    """Delhi (28.6139, 77.2090) → Agra (27.1767, 78.0081) ≈ 178 km ±10%."""
    dist = VerificationAgent._haversine(28.6139, 77.2090, 27.1767, 78.0081)
    assert 160_000 < dist < 196_000, f"Expected ~178km, got {dist:.0f}m"


def test_haversine_boundary_150m_accepted() -> None:
    """A point displaced ~140 m north should be within the 150 m window."""
    # ~0.00126 degrees latitude ≈ 140 m
    dist = VerificationAgent._haversine(28.6667, 77.2333, 28.6680, 77.2333)
    assert dist <= 150.0, f"Expected ≤150m, got {dist:.1f}m"


def test_haversine_boundary_151m_rejected() -> None:
    """A point displaced ~200 m north should be outside the 150 m window."""
    # ~0.0018 degrees latitude ≈ 200 m
    dist = VerificationAgent._haversine(28.6667, 77.2333, 28.6685, 77.2333)
    assert dist > 150.0, f"Expected >150m, got {dist:.1f}m"


# ── Stale penalty ─────────────────────────────────────────────────────────────


def test_stale_penalty_fresh() -> None:
    ts = datetime.now(UTC) - timedelta(minutes=30)
    assert VerificationAgent._stale_penalty(ts) == pytest.approx(1.0)


def test_stale_penalty_1h() -> None:
    ts = datetime.now(UTC) - timedelta(hours=1, minutes=1)
    assert VerificationAgent._stale_penalty(ts) == pytest.approx(0.75)


def test_stale_penalty_3h() -> None:
    ts = datetime.now(UTC) - timedelta(hours=3, minutes=1)
    assert VerificationAgent._stale_penalty(ts) == pytest.approx(0.50)


def test_stale_penalty_6h() -> None:
    ts = datetime.now(UTC) - timedelta(hours=7)
    assert VerificationAgent._stale_penalty(ts) == pytest.approx(0.25)


def test_stale_penalty_naive_datetime() -> None:
    """Naive datetimes (no tzinfo) should be treated as UTC without raising."""
    ts = datetime.now() - timedelta(minutes=10)  # naive, no tzinfo
    # Should not raise; penalty should be 1.0 for a fresh naive timestamp
    penalty = VerificationAgent._stale_penalty(ts)
    assert penalty == pytest.approx(1.0)


# ── Confidence scoring ────────────────────────────────────────────────────────


def test_confidence_single_sms_fresh() -> None:
    """1 fresh SMS, no cluster members → corroboration = 1/5 = 0.2."""
    agent = _mock_agent()
    proto = _proto()
    conf = agent._compute_confidence(cluster_members=[], new_proto=proto)
    # corroboration_factor = 1/5 = 0.2, cross_source_bonus = 1.0, stale = 1.0
    assert conf == pytest.approx(0.2, abs=1e-4)


def test_confidence_increases_with_more_sources() -> None:
    """Adding more cluster members raises confidence."""
    agent = _mock_agent()
    proto = _proto()
    members_1 = [{"source": "sms"}]
    members_4 = [{"source": "sms"}] * 4
    conf_1 = agent._compute_confidence(members_1, proto)
    conf_4 = agent._compute_confidence(members_4, proto)
    assert conf_4 > conf_1


def test_confidence_cross_source_bonus() -> None:
    """A satellite + SMS cluster should have higher confidence than all-SMS."""
    agent = _mock_agent()
    proto_sms = _proto(source=SourceType.SMS)
    members_same = [{"source": "sms"}] * 3
    members_cross = [{"source": "satellite"}, {"source": "sms"}, {"source": "tweet"}]
    conf_same = agent._compute_confidence(members_same, proto_sms)
    conf_cross = agent._compute_confidence(members_cross, proto_sms)
    assert conf_cross > conf_same


def test_confidence_stale_applied() -> None:
    """A 7-hour-old report should have confidence < 0.5."""
    agent = _mock_agent()
    proto = _proto(age_hours=7)
    conf = agent._compute_confidence(cluster_members=[], new_proto=proto)
    # corroboration_factor=0.2, cross_source=1.0, stale=0.25 → 0.05
    assert conf < 0.5


def test_confidence_capped_at_1() -> None:
    """With many corroborating sources, confidence must not exceed 1.0."""
    agent = _mock_agent()
    proto = _proto(source=SourceType.SATELLITE)
    many_members = [
        {"source": src}
        for src in [
            "sms",
            "tweet",
            "satellite",
            "iot_sensor",
            "news",
            "whatsapp",
            "web_form",
            "sms",
            "sms",
            "sms",
        ]
    ]
    conf = agent._compute_confidence(many_members, proto)
    assert conf <= 1.0


# ── Cluster resolution ────────────────────────────────────────────────────────


def test_cluster_no_candidates_creates_new() -> None:
    """No matching candidates → a fresh cluster_id starting with 'cluster_'."""
    agent = _mock_agent()
    result = agent._resolve_cluster([])
    assert result.cluster_id.startswith("cluster_")


def test_cluster_join_existing() -> None:
    """A single matching candidate with a cluster_id → join that cluster."""
    existing_id = f"cluster_{uuid4()}"
    matched = [({"source": "sms", "cluster_id": existing_id}, FAKE_VECTOR, 0.85)]
    agent = _mock_agent()
    result = agent._resolve_cluster(matched)
    assert result.cluster_id == existing_id


def test_cluster_picks_most_popular_cluster() -> None:
    """Two candidates from cluster_A and one from cluster_B → cluster_A wins."""
    id_a = f"cluster_{uuid4()}"
    id_b = f"cluster_{uuid4()}"
    matched = [
        ({"source": "sms", "cluster_id": id_a}, FAKE_VECTOR, 0.9),
        ({"source": "sms", "cluster_id": id_a}, FAKE_VECTOR, 0.8),
        ({"source": "sms", "cluster_id": id_b}, FAKE_VECTOR, 0.75),
    ]
    agent = _mock_agent()
    result = agent._resolve_cluster(matched)
    assert result.cluster_id == id_a


def test_cluster_candidates_without_cluster_id_create_new() -> None:
    """Candidates that have no cluster_id yet → new cluster created."""
    matched = [
        ({"source": "sms"}, FAKE_VECTOR, 0.8),
    ]
    agent = _mock_agent()
    result = agent._resolve_cluster(matched)
    assert result.cluster_id.startswith("cluster_")


# ── Canonical representative ──────────────────────────────────────────────────


def test_canonical_satellite_beats_sms() -> None:
    """A satellite cluster member should be chosen over an SMS proto."""
    agent = _mock_agent()
    proto = _proto(source=SourceType.SMS)
    sat_payload = {
        "source": "satellite",
        "lat": 28.6670,
        "lon": 77.2340,
        "timestamp_epoch": datetime.now(UTC).timestamp(),
    }
    canonical = agent._choose_canonical([sat_payload], proto)
    assert canonical["source"] == "satellite"


def test_canonical_tiebreak_by_recency() -> None:
    """Same source type → most recent timestamp_epoch wins."""
    agent = _mock_agent()
    now = datetime.now(UTC).timestamp()
    older = {"source": "sms", "lat": 28.6667, "lon": 77.2333, "timestamp_epoch": now - 900}
    newer = {"source": "sms", "lat": 28.6667, "lon": 77.2333, "timestamp_epoch": now - 60}
    proto = _proto(source=SourceType.TWEET, age_hours=0.02)
    canonical = agent._choose_canonical([older, newer], proto)
    assert canonical["timestamp_epoch"] == pytest.approx(newer["timestamp_epoch"])


def test_canonical_no_members_uses_proto() -> None:
    """No cluster members → proto itself is the canonical."""
    agent = _mock_agent()
    proto = _proto()
    canonical = agent._choose_canonical([], proto)
    assert canonical["lat"] == proto.lat
    assert canonical["lon"] == proto.lon


# ── verify() end-to-end (mocked) ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_verify_returns_verified_status() -> None:
    """verify() should always return status=VERIFIED."""
    agent = _mock_agent()
    result = await agent.verify(_proto())
    assert result.status == IncidentStatus.VERIFIED


@pytest.mark.anyio
async def test_verify_new_incident_gets_cluster_id() -> None:
    """A fresh proto with no candidates should receive a new cluster_id."""
    agent = _mock_agent(nearby_payloads=[], payload_vectors=[])
    result = await agent.verify(_proto())
    assert result.cluster_id.startswith("cluster_")


@pytest.mark.anyio
async def test_verify_dedup_same_event() -> None:
    """
    Two reports of the same event should share a cluster_id.

    Simulate: the second report finds the first in search_nearby() and they
    have cosine similarity 1.0 (same vector).
    """
    existing_cluster_id = f"cluster_{uuid4()}"
    existing_payload = {
        "proto_id": str(uuid4()),
        "source": "sms",
        "lat": YAMUNA_LAT,
        "lon": YAMUNA_LON,
        "timestamp_epoch": datetime.now(UTC).timestamp(),
        "cluster_id": existing_cluster_id,
        "point_type": "proto",
    }

    # EmbeddingService.cosine_similarity is a staticmethod — same vector → sim=1.0
    with patch(
        "app.agents.verification.EmbeddingService.cosine_similarity",
        return_value=1.0,
    ):
        agent = _mock_agent(
            nearby_payloads=[existing_payload],
            payload_vectors=[(existing_payload, FAKE_VECTOR)],
        )
        result = await agent.verify(_proto())

    assert result.cluster_id == existing_cluster_id


@pytest.mark.anyio
async def test_verify_low_similarity_creates_new_cluster() -> None:
    """
    If the only nearby candidate is an unverified proto with cosine similarity
    below threshold, a new cluster must be created.

    Note: If the nearby candidate is a VERIFIED cluster point (with cluster_id),
    it would be joined via the pre-voted path regardless of cosine similarity.
    This test simulates the case where there's only a raw proto nearby —
    not yet verified — with no cluster_id.
    """
    # A nearby proto payload WITHOUT a cluster_id (not yet verified)
    unverified_payload = {
        "proto_id": str(uuid4()),
        "source": "sms",
        "lat": YAMUNA_LAT,
        "lon": YAMUNA_LON,
        "timestamp_epoch": datetime.now(UTC).timestamp(),
        # No cluster_id — this proto hasn't been through verify() yet
        "point_type": "proto",
    }

    with patch(
        "app.agents.verification.EmbeddingService.cosine_similarity",
        return_value=0.3,  # below SIMILARITY_THRESHOLD (0.7)
    ):
        agent = _mock_agent(
            # search_nearby returns the unverified proto (no cluster_id)
            nearby_payloads=[unverified_payload],
            # get_vectors_by_filter returns its vector
            payload_vectors=[(unverified_payload, FAKE_VECTOR)],
        )
        proto = _proto(text="Something completely different")
        result = await agent.verify(proto)

    # No cluster_id in candidates, cosine sim below threshold → new cluster
    assert result.cluster_id.startswith("cluster_"), (
        f"Expected new cluster, got {result.cluster_id}"
    )


@pytest.mark.anyio
async def test_verify_old_report_low_confidence() -> None:
    """A 7-hour-old report should produce confidence < 0.5."""
    agent = _mock_agent()
    old_proto = _proto(age_hours=7)
    result = await agent.verify(old_proto)
    assert result.confidence < 0.5


@pytest.mark.anyio
async def test_verify_no_coords_creates_lone_cluster() -> None:
    """
    A ProtoIncident without lat/lon cannot participate in spatial clustering
    and should receive a lone cluster with low confidence.
    """
    mock_store = MagicMock()
    mock_store.upsert_verified = AsyncMock(return_value=None)

    mock_embedder = MagicMock()
    mock_embedder.embed_text = AsyncMock(return_value=FAKE_VECTOR)

    agent = VerificationAgent(vector_store=mock_store, embedding_service=mock_embedder)
    proto = ProtoIncident(
        source=SourceType.SMS,
        text="Flooding somewhere",
        lat=None,
        lon=None,
    )
    result = await agent.verify(proto)
    assert result.cluster_id.startswith("cluster_")
    assert result.confidence < 0.5
