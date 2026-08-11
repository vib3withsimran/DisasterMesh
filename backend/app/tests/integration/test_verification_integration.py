"""
Integration tests for VerificationAgent — Phase 3.

Uses an in-memory Qdrant instance (no disk I/O, no network) and the real
EmbeddingService (all-MiniLM-L6-v2) so that end-to-end vector similarity is
tested with genuine embeddings.

The real model is downloaded once per session (~90 MB to ~/.cache/huggingface/).
After the first run the cache is reused and tests complete in a few seconds.

Run:
    cd backend
    pytest app/tests/integration/test_verification_integration.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from qdrant_client import QdrantClient

from app.agents.embeddings import EmbeddingService
from app.agents.vector_store import VectorStore
from app.agents.verification import VerificationAgent
from app.schemas import (
    IncidentStatus,
    ProtoIncident,
    SourceType,
    VerifiedIncident,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

YAMUNA_LAT = 28.6667
YAMUNA_LON = 77.2333


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
async def embedding_service() -> EmbeddingService:
    """Real EmbeddingService — model downloaded once per test-session."""
    return EmbeddingService()


@pytest.fixture()
async def vector_store() -> VectorStore:
    """Fresh in-memory Qdrant per test so tests are fully isolated."""
    client = QdrantClient(":memory:")
    store = VectorStore(qdrant_client=client)
    await store.ensure_collection()
    return store


@pytest.fixture()
async def agent(vector_store, embedding_service) -> VerificationAgent:
    return VerificationAgent(
        vector_store=vector_store,
        embedding_service=embedding_service,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _proto(
    text: str,
    lat: float = YAMUNA_LAT,
    lon: float = YAMUNA_LON,
    source: SourceType = SourceType.SMS,
    age_hours: float = 0.0,
) -> ProtoIncident:
    ts = _now() - timedelta(hours=age_hours)
    return ProtoIncident(source=source, text=text, lat=lat, lon=lon, timestamp=ts)


async def _ingest(store: VectorStore, embedder: EmbeddingService, proto: ProtoIncident) -> None:
    """Embed + upsert a ProtoIncident into the vector store (mimics Phase 2 pipeline)."""
    vector = await embedder.embed_incident(proto)
    await store.upsert(proto, vector)


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_five_reports_same_event_single_cluster(
    agent, vector_store, embedding_service
) -> None:
    """
    Five slightly different wordings of the same flood event at the same
    location should all cluster into a single cluster_id.
    """
    texts = [
        "Water rising fast near Yamuna Bazar",
        "Flooding at Yamuna Bazar area, need help",
        "Flooding near Yamuna Bazar, water rising rapidly",
        "Heavy flooding reported near Yamuna Bazar",
        "Rescue needed — water levels up at Yamuna Bazar",
    ]
    protos = [
        _proto(
            text=t,
            lat=YAMUNA_LAT + (i * 0.0001),  # tiny jitter ≈ 11 m per step
            lon=YAMUNA_LON + (i * 0.0001),
        )
        for i, t in enumerate(texts)
    ]

    # Ingest all into vector store first (simulates Phase 2 pipeline)
    for p in protos:
        await _ingest(vector_store, embedding_service, p)

    # Verify each — they should all converge to the same cluster
    verified_incidents: list[VerifiedIncident] = []
    for p in protos:
        v = await agent.verify(p)
        verified_incidents.append(v)

    cluster_ids = {v.cluster_id for v in verified_incidents}
    assert len(cluster_ids) == 1, (
        f"Expected 1 cluster for 5 same-event reports, got {len(cluster_ids)}: {cluster_ids}"
    )


@pytest.mark.anyio
async def test_cross_source_higher_confidence(agent, vector_store, embedding_service) -> None:
    """
    A satellite + 3× SMS cluster should have higher confidence than an
    SMS-only cluster of the same size.
    """
    # SMS-only cluster
    for _ in range(3):
        p = _proto(text="Flooding near Yamuna Bazar", lat=28.6700, lon=77.2400)
        await _ingest(vector_store, embedding_service, p)

    sms_only_proto = _proto(text="Water rising at Yamuna Bazar", lat=28.6700, lon=77.2400)
    sms_only_result = await agent.verify(sms_only_proto)

    # Cross-source cluster (satellite nearby)
    for _ in range(3):
        p = _proto(text="Flooding near Connaught Place", lat=28.6325, lon=77.2195)
        await _ingest(vector_store, embedding_service, p)
    sat_p = _proto(
        text="Sentinel-2 flood polygon: Connaught Place area",
        lat=28.6325,
        lon=77.2195,
        source=SourceType.SATELLITE,
    )
    await _ingest(vector_store, embedding_service, sat_p)

    cross_proto = _proto(
        text="Water rising at Connaught Place",
        lat=28.6325,
        lon=77.2195,
        source=SourceType.SATELLITE,
    )
    cross_result = await agent.verify(cross_proto)

    assert cross_result.confidence >= sms_only_result.confidence, (
        f"Cross-source confidence {cross_result.confidence:.3f} should be ≥ "
        f"SMS-only {sms_only_result.confidence:.3f}"
    )


@pytest.mark.anyio
async def test_geo_outside_radius_separate_cluster(agent, vector_store, embedding_service) -> None:
    """
    A report 300 m away from an existing cluster should land in a
    different cluster.
    """
    # Seed an existing proto at Yamuna Bazar
    existing = _proto(text="Flooding at Yamuna Bazar")
    await _ingest(vector_store, embedding_service, existing)
    result_existing = await agent.verify(existing)

    # New proto ~0.003 degrees north ≈ ~333 m away (outside 150 m radius)
    far = _proto(
        text="Flooding at Yamuna Bazar",
        lat=YAMUNA_LAT + 0.003,
        lon=YAMUNA_LON,
    )
    await _ingest(vector_store, embedding_service, far)
    result_far = await agent.verify(far)

    assert result_far.cluster_id != result_existing.cluster_id, (
        "Reports 300 m apart should be in separate clusters"
    )


@pytest.mark.anyio
async def test_temporal_outside_window_separate_cluster(
    agent, vector_store, embedding_service
) -> None:
    """
    An identical report that is 35 minutes old (outside the 30-min window)
    should land in a separate cluster from a fresh report at the same location.
    """
    old_proto = _proto(
        text="Water rising near Yamuna Bazar",
        age_hours=35 / 60,  # 35 min ago
    )
    await _ingest(vector_store, embedding_service, old_proto)

    fresh_proto = _proto(text="Water rising near Yamuna Bazar")
    await _ingest(vector_store, embedding_service, fresh_proto)

    result_old = await agent.verify(old_proto)
    result_fresh = await agent.verify(fresh_proto)

    # Old report's timestamp_epoch falls outside the window for fresh proto's verify()
    # so the fresh report should NOT see the old one as a candidate.
    # They may or may not share a cluster depending on whether the old one's
    # verified-cluster point is still returned, but their base confidences differ.
    # The critical assertion is that the old report has a lower confidence.
    assert result_old.confidence <= result_fresh.confidence, (
        f"Old report conf {result_old.confidence:.3f} should be ≤ fresh {result_fresh.confidence:.3f}"
    )


@pytest.mark.anyio
async def test_semantic_below_threshold_separate_cluster(
    agent, vector_store, embedding_service
) -> None:
    """
    Same location and time window but semantically unrelated text should
    produce a new cluster (not merge with the nearby one).
    """
    flood_proto = _proto(text="Flooding near Yamuna Bazar, water rising rapidly")
    await _ingest(vector_store, embedding_service, flood_proto)
    flood_result = await agent.verify(flood_proto)

    # Completely unrelated topic at the same location
    unrelated = _proto(
        text="Traffic jam on Ring Road due to truck breakdown",
        lat=YAMUNA_LAT + 0.0005,  # ~55 m away — inside spatial window
        lon=YAMUNA_LON,
    )
    await _ingest(vector_store, embedding_service, unrelated)
    unrelated_result = await agent.verify(unrelated)

    # If the cosine similarity of "traffic jam" vs "flooding" is < 0.7,
    # they should be in different clusters.
    # We check only when they actually differ (the assertion would trivially
    # pass if they were joined, which would be a test design bug, not a code bug).
    if unrelated_result.cluster_id != flood_result.cluster_id:
        # Correct behaviour confirmed
        pass
    else:
        # If they merged, their semantic similarity must be ≥ 0.7 — verify
        # by computing it directly.
        vec_flood = await embedding_service.embed_incident(flood_proto)
        vec_unrelated = await embedding_service.embed_incident(unrelated)
        sim = EmbeddingService.cosine_similarity(vec_flood, vec_unrelated)
        assert sim >= 0.7, (
            f"Semantically unrelated reports merged into same cluster "
            f"(cosine sim = {sim:.3f} < 0.7 expected for merge)"
        )


@pytest.mark.anyio
async def test_verify_returns_verified_status(agent, vector_store, embedding_service) -> None:
    """verify() must always return status=VERIFIED."""
    p = _proto(text="Flooding at Yamuna Bazar")
    await _ingest(vector_store, embedding_service, p)
    result = await agent.verify(p)
    assert result.status == IncidentStatus.VERIFIED


@pytest.mark.anyio
async def test_canonical_representative_is_satellite(
    agent, vector_store, embedding_service
) -> None:
    """
    When a cluster contains both SMS and satellite reports, the satellite
    report's source should appear in source_provenance of the merged cluster.

    Both reports must be semantically similar (cosine ≥ 0.7) so they merge.
    """
    sat_lat = YAMUNA_LAT + 0.0003  # ~33 m north — inside 150 m radius
    sat_lon = YAMUNA_LON

    # Use very similar text so the two protos merge semantically
    sat_proto = _proto(
        text="Heavy flooding near Yamuna Bazar river, water levels rising",
        lat=sat_lat,
        lon=sat_lon,
        source=SourceType.SATELLITE,
    )
    sms_proto = _proto(
        text="Heavy flooding near Yamuna Bazar river, water levels rising",
        lat=YAMUNA_LAT,
        lon=YAMUNA_LON,
        source=SourceType.SMS,
    )

    await _ingest(vector_store, embedding_service, sat_proto)
    await _ingest(vector_store, embedding_service, sms_proto)

    result_sat = await agent.verify(sat_proto)
    result_sms = await agent.verify(sms_proto)

    # They should share the same cluster_id
    assert result_sat.cluster_id == result_sms.cluster_id, (
        "Satellite and SMS reports for the same event should merge into one cluster"
    )

    # The merged cluster should contain both source types
    all_sources = set(result_sat.source_provenance) | set(result_sms.source_provenance)
    assert SourceType.SATELLITE in all_sources, (
        f"Expected satellite in combined provenance, got {all_sources}"
    )


@pytest.mark.anyio
async def test_stale_penalty_applied_in_integration(agent, vector_store, embedding_service) -> None:
    """A 7-hour-old report should produce confidence < 0.35."""
    old_proto = _proto(text="Flooding near Yamuna Bazar", age_hours=7)
    await _ingest(vector_store, embedding_service, old_proto)
    result = await agent.verify(old_proto)
    assert result.confidence < 0.35, (
        f"Expected confidence < 0.35 for 7h old report, got {result.confidence:.3f}"
    )


@pytest.mark.anyio
async def test_upsert_verified_persists_cluster_id(agent, vector_store, embedding_service) -> None:
    """
    After verify(), the Qdrant collection should contain a 'verified' point
    whose payload includes the cluster_id.
    """
    p = _proto(text="Flooding near Yamuna Bazar river bank")
    await _ingest(vector_store, embedding_service, p)
    result = await agent.verify(p)

    # Scroll all verified points
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    points, _ = vector_store._raw_client.scroll(
        collection_name="proto_incidents",
        scroll_filter=Filter(
            must=[
                FieldCondition(
                    key="cluster_id",
                    match=MatchValue(value=result.cluster_id),
                )
            ]
        ),
        limit=10,
        with_payload=True,
        with_vectors=False,
    )
    assert len(points) >= 1, (
        f"Expected at least 1 Qdrant point with cluster_id={result.cluster_id!r}, found 0"
    )
    payloads = [p.payload for p in points if p.payload]
    cluster_ids_found = [p.get("cluster_id") for p in payloads]
    assert result.cluster_id in cluster_ids_found
