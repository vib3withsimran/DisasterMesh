"""
Verification Agent — Agent 2.

Responsibilities:
  - Deduplicate reports using spatial (≤150 m) + temporal (≤30 min) + semantic
    (cosine ≥ 0.7) clustering
  - Compute confidence scores:
        confidence = corroboration_factor × cross_source_bonus × stale_penalty
  - Filter spam and stale reports
  - Choose a canonical representative per cluster
  - Upsert the verified incident back to Qdrant (tagged point_type="verified")

Implemented in Phase 3.

Design
------
3-D clustering:
  1. Spatial + temporal pre-filter  → VectorStore.search_nearby()
  2. Semantic filter                → cosine_similarity(new_vector, candidate_vector)
     using the stored embedding (retrieved via VectorStore.get_vectors_by_filter)
     rather than re-embedding on the fly (Option B).

Confidence formula:
    corroboration_factor  = min(1.0, n_corroborating / CORROBORATION_SATURATION)
    cross_source_bonus    = 1.0 + CROSS_SOURCE_WEIGHT * (n_distinct_types - 1)
    stale_penalty         = see _stale_penalty() for the step function
    confidence            = min(1.0, corroboration_factor
                                   × cross_source_bonus
                                   × stale_penalty)

Cluster layout in Qdrant:
  - Proto-incident points  → point_type = "proto"   (written by Phase 2 pipeline)
  - Verified-cluster points → point_type = "verified" (written by this agent)
  Both share the same "proto_incidents" collection to keep singleton lifecycle simple.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any
from uuid import uuid4

from app.agents.embeddings import EmbeddingService, get_embedding_service
from app.agents.vector_store import VectorStore, get_vector_store
from app.schemas import (
    ClusterMatchResult,
    IncidentStatus,
    NeedsProfile,
    ProtoIncident,
    SourceType,
    VerifiedIncident,
)

logger = logging.getLogger(__name__)

# ── Tuneable constants ────────────────────────────────────────────────────────

GEO_RADIUS_M: float = 150.0  # metres — spatial dedup window
TIME_WINDOW_SECONDS: float = 30 * 60  # 30 minutes — temporal dedup window
SIMILARITY_THRESHOLD: float = 0.7  # cosine — semantic dedup threshold

# Confidence scoring parameters
CORROBORATION_SATURATION: int = 5  # n sources needed for full corroboration
CROSS_SOURCE_WEIGHT: float = 0.15  # bonus per additional distinct source type

# Source priority for canonical representative selection (higher = preferred)
_SOURCE_PRIORITY: dict[SourceType, int] = {
    SourceType.SATELLITE: 4,
    SourceType.IOT_SENSOR: 3,
    SourceType.SMS: 2,
    SourceType.WHATSAPP: 2,
    SourceType.WEB_FORM: 2,
    SourceType.NEWS: 1,
    SourceType.TWEET: 1,
}


# ── VerificationAgent ─────────────────────────────────────────────────────────


class VerificationAgent:
    """
    Deduplicates and verifies proto-incidents.

    Uses three-dimensional clustering:
    - Spatial  : Haversine distance ≤ GEO_RADIUS_M  (150 m)
    - Temporal : within TIME_WINDOW_SECONDS           (30 min)
    - Semantic : cosine similarity ≥ SIMILARITY_THRESHOLD  (0.7)

    Parameters
    ----------
    vector_store:
        Shared VectorStore singleton.  Defaults to the module-level singleton
        returned by ``get_vector_store()``.
    embedding_service:
        Shared EmbeddingService singleton.  Defaults to ``get_embedding_service()``.
    geo_radius_m:
        Override the spatial dedup radius (metres).
    time_window_s:
        Override the temporal dedup window (seconds).
    similarity_threshold:
        Override the cosine similarity dedup threshold.
    """

    def __init__(
        self,
        vector_store: VectorStore | None = None,
        embedding_service: EmbeddingService | None = None,
        geo_radius_m: float = GEO_RADIUS_M,
        time_window_s: float = TIME_WINDOW_SECONDS,
        similarity_threshold: float = SIMILARITY_THRESHOLD,
    ) -> None:
        self._store = vector_store or get_vector_store()
        self._embedder = embedding_service or get_embedding_service()
        self.geo_radius_m = geo_radius_m
        self.time_window_s = time_window_s
        self.similarity_threshold = similarity_threshold

    # ── Public API ────────────────────────────────────────────────────────────

    async def verify(self, proto: ProtoIncident) -> VerifiedIncident:
        """
        Main entry point: verify + deduplicate a proto-incident.

        Steps
        -----
        1. Embed the incoming proto-incident.
        2. Retrieve geo+time-window candidates from Qdrant.
        3. Fetch stored vectors for those candidates (Option B: no re-embed).
        4. Compute cosine similarity; keep candidates ≥ SIMILARITY_THRESHOLD.
        5. Cluster: join best existing cluster or create a new one.
        6. Compute confidence score.
        7. Choose canonical representative.
        8. Upsert the VerifiedIncident back to Qdrant.
        9. Return the VerifiedIncident.

        Parameters
        ----------
        proto:
            A normalized ProtoIncident produced by SituationalAgent.

        Returns
        -------
        VerifiedIncident
            A verified, deduplicated incident with cluster_id and confidence score.
        """
        if proto.lat is None or proto.lon is None:
            # Cannot do spatial clustering without coordinates.  Create a lone
            # cluster with low confidence so downstream agents still receive it.
            logger.warning(
                "ProtoIncident %s has no coordinates — skipping spatial cluster, "
                "assigning new cluster with reduced confidence.",
                proto.id,
            )
            return await self._create_lone_cluster(proto, base_confidence=0.1)

        # Step 1: Embed
        proto_vector = await self._embedder.embed_incident(proto)

        # Step 2: Geo + time candidates with vectors
        candidate_pairs = await self._store.search_nearby(
            lat=proto.lat,
            lon=proto.lon,
            radius_m=self.geo_radius_m,
            time_window_s=self.time_window_s,
            with_vectors=True,
        )

        logger.debug(
            "verify(%s): %d geo+time candidates within %.0fm / %.0fs",
            proto.id,
            len(candidate_pairs),
            self.geo_radius_m,
            self.time_window_s,
        )

        # Step 3: Compute cosine similarity; keep candidates ≥ SIMILARITY_THRESHOLD
        matched: list[tuple[dict[str, Any], list[float], float]] = []  # (payload, vec, sim)
        for payload, vec in candidate_pairs:
            if isinstance(payload, dict) and isinstance(vec, list):
                sim = EmbeddingService.cosine_similarity(proto_vector, vec)
                if sim >= self.similarity_threshold:
                    matched.append((payload, vec, sim))

        logger.debug(
            "verify(%s): %d semantic matches (sim≥%.2f)",
            proto.id,
            len(matched),
            self.similarity_threshold,
        )

        # Step 4: Cluster
        cluster_result = self._resolve_cluster(matched)

        # Step 5: Confidence
        confidence = self._compute_confidence(
            cluster_members=[m[0] for m in matched],
            new_proto=proto,
        )

        # Step 6: Canonical representative
        canonical = self._choose_canonical(
            cluster_members=[m[0] for m in matched],
            new_proto=proto,
        )

        # Build the VerifiedIncident
        all_sources: list[SourceType] = []
        for payload in cluster_result.members:
            raw_src = payload.get("source", "")
            try:
                all_sources.append(SourceType(raw_src))
            except ValueError:
                pass
        all_sources.append(proto.source)

        verified = VerifiedIncident(
            cluster_id=cluster_result.cluster_id,
            source_provenance=list(dict.fromkeys(all_sources)),  # deduplicated, ordered
            lat=canonical["lat"],
            lon=canonical["lon"],
            timestamp=datetime.fromtimestamp(canonical["timestamp_epoch"], tz=UTC),
            confidence=confidence,
            needs=NeedsProfile(),
            media_urls=[],
            status=IncidentStatus.VERIFIED,
        )

        # Step 7: Upsert back to Qdrant
        await self._store.upsert_verified(verified, proto_vector)
        logger.info(
            "Verified cluster_id=%s confidence=%.3f sources=%s",
            verified.cluster_id,
            verified.confidence,
            [s.value for s in verified.source_provenance],
        )

        return verified

    # ── Clustering ────────────────────────────────────────────────────────────

    def _resolve_cluster(
        self,
        matched: list[tuple[dict[str, Any], list[float], float]],
    ) -> ClusterMatchResult:
        """
        Determine which cluster to join (or create a new one).

        Collect cluster_ids from all candidates that passed 3D clustering (spatial,
        temporal, AND semantic match). If any matched candidate belongs to a cluster,
        join the most frequent cluster_id. Otherwise, create a new cluster.
        """
        if not matched:
            new_id = f"cluster_{uuid4()}"
            return ClusterMatchResult(cluster_id=new_id)

        cluster_votes: list[str] = [m[0]["cluster_id"] for m in matched if m[0].get("cluster_id")]

        if cluster_votes:
            most_common_id = Counter(cluster_votes).most_common(1)[0][0]
            cluster_id = most_common_id
        else:
            cluster_id = f"cluster_{uuid4()}"

        return ClusterMatchResult(
            cluster_id=cluster_id,
            members=[m[0] for m in matched],
            member_vectors=[m[1] for m in matched],
            similarity_scores=[m[2] for m in matched],
        )

    # ── Confidence scoring ────────────────────────────────────────────────────

    def _compute_confidence(
        self,
        cluster_members: list[dict],
        new_proto: ProtoIncident,
    ) -> float:
        """
        Confidence = corroboration_factor × cross_source_bonus × stale_penalty

        corroboration_factor
            Scales with the number of corroborating sources, saturating at
            CORROBORATION_SATURATION (default 5).  A lone unverified report
            scores 1/5 = 0.20.

        cross_source_bonus
            Multi-type corroboration (e.g. satellite + SMS) is more reliable
            than the same source type repeated.  Each additional distinct source
            type adds CROSS_SOURCE_WEIGHT (default +0.15).

        stale_penalty
            Step function on age of the incoming proto-incident:
              fresh (< 1 h)  → 1.00
              1 h – 3 h      → 0.75
              3 h – 6 h      → 0.50
              ≥ 6 h          → 0.25
        """
        n_corroborating = len(cluster_members) + 1  # +1 for the new proto itself
        corroboration_factor = min(1.0, n_corroborating / CORROBORATION_SATURATION)

        # Distinct source types across cluster + new proto
        sources: set[str] = {m.get("source", "") for m in cluster_members}
        sources.add(
            new_proto.source.value if hasattr(new_proto.source, "value") else str(new_proto.source)
        )
        sources.discard("")  # remove empty strings if any
        n_distinct = len(sources)
        cross_source_bonus = 1.0 + CROSS_SOURCE_WEIGHT * (n_distinct - 1)

        penalty = self._stale_penalty(new_proto.timestamp)

        raw = corroboration_factor * cross_source_bonus * penalty
        confidence = min(1.0, raw)
        logger.debug(
            "_compute_confidence: corr=%.3f cross=%.3f stale=%.3f → %.3f",
            corroboration_factor,
            cross_source_bonus,
            penalty,
            confidence,
        )
        return round(confidence, 6)

    @staticmethod
    def _stale_penalty(timestamp: datetime) -> float:
        """
        Step-function penalty based on how old the proto-incident timestamp is.

        Age buckets
        -----------
        < 1 hour   → 1.00 (no penalty)
        1–3 hours  → 0.75
        3–6 hours  → 0.50
        ≥ 6 hours  → 0.25
        """
        now = datetime.now(UTC)
        # Make timestamp timezone-aware if it isn't already.
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        age = now - timestamp
        if age < timedelta(hours=1):
            return 1.00
        if age < timedelta(hours=3):
            return 0.75
        if age < timedelta(hours=6):
            return 0.50
        return 0.25

    # ── Canonical representative ──────────────────────────────────────────────

    def _choose_canonical(
        self,
        cluster_members: list[dict],
        new_proto: ProtoIncident,
    ) -> dict:
        """
        Choose the most authoritative / recent representative.

        Priority order: SATELLITE > IOT_SENSOR > SMS/WHATSAPP/WEB_FORM > NEWS/TWEET

        Tie-break: most recent timestamp_epoch.

        Returns
        -------
        A payload dict with at minimum ``lat``, ``lon``, and ``timestamp_epoch``
        keys.  If there are no cluster_members, the new_proto's own coordinates
        and timestamp are used.
        """
        # Build a normalised candidate list mixing existing members + new proto
        candidates: list[dict] = list(cluster_members)

        # Convert new_proto into a comparable dict
        proto_dict: dict = {
            "source": (
                new_proto.source.value
                if hasattr(new_proto.source, "value")
                else str(new_proto.source)
            ),
            "lat": new_proto.lat,
            "lon": new_proto.lon,
            "timestamp_epoch": new_proto.timestamp.timestamp(),
            "text": new_proto.text,
        }
        candidates.append(proto_dict)

        def _rank(c: dict) -> tuple[int, float]:
            src_str = c.get("source", "")
            try:
                src = SourceType(src_str)
            except ValueError:
                src = SourceType.TWEET  # fallback to lowest priority
            priority = _SOURCE_PRIORITY.get(src, 0)
            ts = c.get("timestamp_epoch", 0.0) or 0.0
            return (priority, ts)

        return max(candidates, key=_rank)

    # ── Haversine helper ──────────────────────────────────────────────────────

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Distance in metres between two lat/lon points (great-circle)."""
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        return 2 * asin(sqrt(a)) * 6_371_000

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _create_lone_cluster(
        self,
        proto: ProtoIncident,
        base_confidence: float = 0.1,
    ) -> VerifiedIncident:
        """
        Create a lone (single-member) cluster for a proto-incident that cannot
        participate in spatial clustering (e.g. missing coordinates).
        """
        penalty = self._stale_penalty(proto.timestamp)
        confidence = round(min(1.0, base_confidence * penalty), 6)

        lat = proto.lat if proto.lat is not None else 0.0
        lon = proto.lon if proto.lon is not None else 0.0

        cluster_id = f"cluster_{uuid4()}"
        verified = VerifiedIncident(
            cluster_id=cluster_id,
            source_provenance=[proto.source],
            lat=lat,
            lon=lon,
            timestamp=proto.timestamp,
            confidence=confidence,
            needs=NeedsProfile(),
            media_urls=proto.media_urls,
            status=IncidentStatus.VERIFIED,
        )

        # Embed with text only (no geo coordinates available)
        vector = await self._embedder.embed_text(proto.text)
        await self._store.upsert_verified(verified, vector)
        return verified


# ── Module-level singleton ────────────────────────────────────────────────────

_verification_agent: VerificationAgent | None = None


def get_verification_agent() -> VerificationAgent:
    """Return the shared VerificationAgent singleton."""
    global _verification_agent
    if _verification_agent is None:
        _verification_agent = VerificationAgent()
    return _verification_agent
