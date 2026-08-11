"""
Vector Store — Phase 2.

Uses LangChain's QdrantVectorStore wrapper so both the embedding model
and the vector store share the same LangChain interface.

Architecture:
  EmbeddingService  (langchain-huggingface)  ─┐
                                               ├─► VectorStore (langchain-qdrant)
  QdrantVectorStore (langchain-qdrant)       ─┘

Collection: "proto_incidents"
  - Vector size  : 384 (all-MiniLM-L6-v2)
  - Distance     : Cosine
  - Metadata keys: proto_id, source, lat, lon, timestamp_epoch, text, language

Geo strategy:
  LangChain's QdrantVectorStore supports metadata filtering.
  For geo radius queries we pull candidates and apply Haversine post-filtering
  in Python (correct + fast for demo scale, easy to upgrade to native Qdrant
  geo index later).

Concurrency:
  All blocking qdrant_client calls run on a dedicated bounded ThreadPoolExecutor
  (_EXECUTOR) rather than the default loop executor, so Qdrant I/O can't starve
  out other sync work sharing the process (see get_vector_store module notes).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    GeoPoint,
    GeoRadius,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    Range,
    VectorParams,
)

from app.agents.embeddings import EmbeddingService, get_embedding_service
from app.schemas import ProtoIncident, VerifiedIncident

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

COLLECTION_NAME = "proto_incidents"
VECTOR_SIZE = 384
EARTH_RADIUS_M = 6_371_000.0

# Dedicated executor for Qdrant blocking calls. Sized modestly on purpose —
# qdrant-client itself pools HTTP/gRPC connections, so this just needs enough
# workers to keep concurrent requests from queueing behind unrelated sync work
# elsewhere in the process (which is what happens if you use the default
# loop executor via run_in_executor(None, ...)). Tune MAX_WORKERS against
# your actual Qdrant connection-pool size / observed concurrency, not blindly.
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="qdrant-io")


async def _run_blocking(fn):
    """Run a blocking callable on the dedicated Qdrant executor."""
    return await asyncio.get_event_loop().run_in_executor(_EXECUTOR, fn)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two lat/lon points."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * math.asin(math.sqrt(a)) * EARTH_RADIUS_M


def _uuid_to_int(uid: str) -> int:
    """Convert a UUID string to an integer suitable as a Qdrant point ID."""
    return uuid.UUID(uid).int % (2**63)


def _cluster_id_to_point_id(cluster_id: str) -> int:
    """
    Derive a stable integer point ID from a cluster_id string
    (form: "cluster_<uuid4>"). Falls back to a hash if the suffix
    isn't a parseable UUID, so this never raises.
    """
    raw_id = cluster_id.removeprefix("cluster_")
    try:
        return uuid.UUID(raw_id).int % (2**63)
    except ValueError:
        digest = hashlib.blake2b(cluster_id.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, byteorder="big") % (2**63)


def _extract_vector(raw_vector: Any) -> list[float] | None:
    """
    Normalize a Qdrant point's `.vector` field into a plain list[float].

    Handles both unnamed-vector layout (list[float]) and named-vector
    layout (dict[str, list[float]]) by taking the first value in the
    latter case. Returns None if the shape or contents are unusable —
    callers should skip the point rather than raise, since garbage
    vectors coming back from Qdrant are a data-integrity signal, not
    something a single lookup should crash on.
    """
    if raw_vector is None:
        return None

    # Handle list case
    if isinstance(raw_vector, list):
        raw_v = raw_vector
    # Handle dict case (named vectors)
    elif isinstance(raw_vector, dict):
        if not raw_vector:
            return None
        raw_v = next(iter(raw_vector.values()))
    else:
        # Reject other types
        return None

    if not isinstance(raw_v, list) or not all(isinstance(x, (int, float)) for x in raw_v):
        return None
    return [float(x) for x in raw_v]


def _proto_to_document(proto: ProtoIncident) -> Document:
    """
    Convert a ProtoIncident to a LangChain Document.

    page_content  = the text used for embedding (set by EmbeddingService)
    metadata      = all payload fields stored in Qdrant alongside the vector
    """
    content = proto.text
    if proto.lat is not None and proto.lon is not None:
        content = f"{proto.text} near {proto.lat:.4f},{proto.lon:.4f}"

    metadata: dict[str, Any] = {
        "proto_id": proto.id,
        "source": proto.source.value if hasattr(proto.source, "value") else str(proto.source),
        "lat": proto.lat,
        "lon": proto.lon,
        "timestamp_epoch": proto.timestamp.timestamp(),
        "text": proto.text,
        "language": proto.metadata.get("language", "en"),
        "address": proto.address,
    }
    return Document(page_content=content, metadata=metadata)


# ── VectorStore ───────────────────────────────────────────────────────────────


class VectorStore:
    """
    LangChain-based vector store backed by Qdrant.

    Wraps QdrantVectorStore for upsert / similarity search and adds:
    - Geo+time radius search with Haversine post-filtering
    - proto_id lookup helper
    - Collection size helper
    """

    def __init__(
        self,
        qdrant_client: QdrantClient,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self._raw_client = qdrant_client
        self._embeddings = embedding_service or get_embedding_service()
        # QdrantVectorStore is initialised after ensure_collection() is called
        self._lc_store: QdrantVectorStore | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def ensure_collection(self) -> None:
        """
        Create the Qdrant collection if it doesn't exist, then bind
        the LangChain QdrantVectorStore to it.

        Idempotent — safe to call on every startup. NOTE: with multiple
        workers/replicas starting concurrently there's a narrow create-collection
        race (get_collection 404s for both, both call create_collection). Qdrant
        generally tolerates a duplicate create_collection with the same config as
        a no-op-ish overwrite, but if you're running multi-worker startup, prefer
        a startup lock (e.g. a Redis/DB advisory lock) around this call instead
        of relying on that behavior.
        """
        try:
            self._raw_client.get_collection(COLLECTION_NAME)
            logger.info("Qdrant collection %r already exists", COLLECTION_NAME)
        except UnexpectedResponse:
            # Genuine "collection not found" — safe to create.
            logger.info("Creating Qdrant collection %r …", COLLECTION_NAME)
            self._raw_client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=VECTOR_SIZE,
                    distance=Distance.COSINE,
                ),
            )
            # Create geo index for location field
            try:
                self._raw_client.create_payload_index(
                    collection_name=COLLECTION_NAME,
                    field_name="location",
                    field_schema=PayloadSchemaType.GEO,
                )
                logger.info("Created geo index on 'location' field")
            except Exception as e:
                logger.warning("Failed to create geo index (may already exist): %s", e)
            logger.info(
                "Created Qdrant collection %r — dim=%d cosine",
                COLLECTION_NAME,
                VECTOR_SIZE,
            )
        except Exception:
            # Anything else (connection refused, DNS failure, auth error, ...)
            # is NOT "collection doesn't exist" — don't paper over it by
            # falling through to create_collection against a client that may
            # not even be reachable. Let it propagate so startup fails loudly.
            logger.exception(
                "Failed to check Qdrant collection %r — not attempting create",
                COLLECTION_NAME,
            )
            raise

        # Bind LangChain store to the (now-existing) collection
        self._lc_store = QdrantVectorStore(
            client=self._raw_client,
            collection_name=COLLECTION_NAME,
            embedding=self._embeddings._lc,  # LangChain Embeddings object
        )
        logger.info("QdrantVectorStore bound to %r", COLLECTION_NAME)

    @property
    def _store(self) -> QdrantVectorStore:
        if self._lc_store is None:
            raise RuntimeError("VectorStore not ready. Call ensure_collection() first.")
        return self._lc_store

    # ── Write ─────────────────────────────────────────────────────────────────

    async def upsert(self, proto: ProtoIncident, vector: list[float]) -> None:
        """
        Store a ProtoIncident and its pre-computed embedding in Qdrant.
        """
        doc = _proto_to_document(proto)
        point_id = _uuid_to_int(proto.id)
        # Store page_content in metadata too for search compatibility
        payload = dict(doc.metadata)
        payload["page_content"] = doc.page_content

        # Add geo point for server-side geo filtering
        if proto.lat is not None and proto.lon is not None:
            payload["location"] = {"lat": proto.lat, "lon": proto.lon}

        point = PointStruct(id=point_id, vector=vector, payload=payload)

        await _run_blocking(
            lambda: self._raw_client.upsert(
                collection_name=COLLECTION_NAME,
                points=[point],
            )
        )
        logger.debug("Upserted proto_id=%s point_id=%d to Qdrant", proto.id, point_id)

    # ── Read ──────────────────────────────────────────────────────────────────

    async def search_similar(
        self,
        query_text: str,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[tuple[Document, float]]:
        """
        Semantic similarity search using LangChain interface.

        Returns list of (Document, score) tuples, score ∈ [0, 1].
        Used for: "find incidents similar to this query text."
        """
        results: list[tuple[Document, float]] = await _run_blocking(
            lambda: self._store.similarity_search_with_score(
                query=query_text,
                k=limit,
            )
        )
        return [(doc, score) for doc, score in results if score >= min_score]

    async def search_nearby(
        self,
        lat: float,
        lon: float,
        radius_m: float = 150.0,
        time_window_s: float | None = None,
        query_text: str | None = None,
        limit: int = 50,
        with_vectors: bool = False,
    ) -> list[dict[str, Any]] | list[tuple[dict[str, Any], list[float]]]:
        """
        Find ProtoIncident payloads (and optional vectors) within geo radius + optional time window.

        Strategy:
          Uses server-side Qdrant filtering with paginated scrolling to apply
          GeoRadius and timestamp filters directly in the database, avoiding
          client-side post-filtering limitations.

        Returns payload dicts (or (payload, vector) tuples if with_vectors=True)
        sorted by distance ascending.
        Used by Phase 3 VerificationAgent for dedup clustering.
        """

        def _do_scroll() -> list[tuple[dict[str, Any], list[float]]] | list[dict[str, Any]]:
            # Build filter conditions
            conditions = []

            # Geo filter
            conditions.append(
                FieldCondition(
                    key="location",
                    geo_radius=GeoRadius(
                        center=GeoPoint(lat=lat, lon=lon),
                        radius=radius_m,
                    ),
                )
            )

            # Time window filter
            if time_window_s is not None:
                now_epoch = datetime.now(UTC).timestamp()
                min_timestamp = now_epoch - time_window_s
                conditions.append(
                    FieldCondition(
                        key="timestamp_epoch",
                        range=Range(gte=min_timestamp),
                    )
                )

            scroll_filter = Filter(must=conditions) if conditions else None

            # Paginated scroll to retrieve all matching points
            results: list[tuple[dict[str, Any], list[float]]] = []
            results_no_vec: list[dict[str, Any]] = []
            next_offset = None

            while True:
                points, next_offset = self._raw_client.scroll(
                    collection_name=COLLECTION_NAME,
                    scroll_filter=scroll_filter,
                    limit=100,  # Page size
                    offset=next_offset,
                    with_payload=True,
                    with_vectors=with_vectors,
                )

                if not points:
                    break

                for p in points:
                    if p.payload is None:
                        continue

                    if with_vectors:
                        vec = _extract_vector(p.vector)
                        if vec is None:
                            continue
                        results.append((p.payload, vec))
                    else:
                        results_no_vec.append(p.payload)

                if next_offset is None:
                    break

            return results if with_vectors else results_no_vec

        # Execute paginated scroll
        if with_vectors:
            candidates_with_vec = await _run_blocking(_do_scroll)
            # Calculate distances and sort
            nearby_vec: list[tuple[float, dict[str, Any], list[float]]] = []
            for payload, vec in candidates_with_vec:
                p_lat = payload.get("lat")
                p_lon = payload.get("lon")
                if p_lat is not None and p_lon is not None:
                    dist = _haversine_m(lat, lon, float(p_lat), float(p_lon))
                    nearby_vec.append((dist, payload, vec))

            nearby_vec.sort(key=lambda x: x[0])
            return [(p, v) for _, p, v in nearby_vec[:limit]]
        else:
            candidates = await _run_blocking(_do_scroll)
            # Calculate distances and sort
            nearby: list[tuple[float, dict[str, Any]]] = []
            for payload in candidates:
                p_lat = payload.get("lat")
                p_lon = payload.get("lon")
                if p_lat is not None and p_lon is not None:
                    dist = _haversine_m(lat, lon, float(p_lat), float(p_lon))
                    nearby.append((dist, payload))

            nearby.sort(key=lambda x: x[0])
            return [p for _, p in nearby[:limit]]

    async def get_by_proto_id(self, proto_id: str) -> dict[str, Any] | None:
        """Fetch a payload by proto_id."""

        def _do_get():
            try:
                pid = _uuid_to_int(proto_id)
            except ValueError:
                pid = None

            if pid is not None:
                try:
                    records = self._raw_client.retrieve(
                        collection_name=COLLECTION_NAME,
                        ids=[pid],
                        with_payload=True,
                        with_vectors=False,
                    )
                    if records and records[0].payload:
                        return records[0].payload
                except Exception:
                    logger.debug(
                        "get_by_proto_id direct retrieve failed for %s", proto_id, exc_info=True
                    )

            # Fallback to scroll search by payload field
            try:
                results = self._raw_client.scroll(
                    collection_name=COLLECTION_NAME,
                    scroll_filter=Filter(
                        must=[FieldCondition(key="proto_id", match=MatchValue(value=proto_id))]
                    ),
                    limit=1,
                    with_payload=True,
                    with_vectors=False,
                )
                points = results[0]
                if points and points[0].payload:
                    return points[0].payload
            except Exception:
                logger.warning(
                    "get_by_proto_id scroll fallback failed for %s", proto_id, exc_info=True
                )

            return None

        return await _run_blocking(_do_get)

    async def get_by_cluster_id(self, cluster_id: str) -> dict[str, Any] | None:
        """
        Return the payload dict for the *verified* point with the given cluster_id.

        Attempts direct retrieval by point_id (derived from cluster_id) first,
        falling back to a scroll search by payload field.
        """

        def _do_get():
            point_id = _cluster_id_to_point_id(cluster_id)

            try:
                records = self._raw_client.retrieve(
                    collection_name=COLLECTION_NAME,
                    ids=[point_id],
                    with_payload=True,
                    with_vectors=False,
                )
                if records and records[0].payload:
                    return records[0].payload
            except Exception:
                logger.debug(
                    "get_by_cluster_id direct retrieve failed for %s", cluster_id, exc_info=True
                )

            try:
                results = self._raw_client.scroll(
                    collection_name=COLLECTION_NAME,
                    scroll_filter=Filter(
                        must=[FieldCondition(key="cluster_id", match=MatchValue(value=cluster_id))]
                    ),
                    limit=1,
                    with_payload=True,
                    with_vectors=False,
                )
                points = results[0]
                if points and points[0].payload:
                    return points[0].payload
            except Exception:
                logger.warning(
                    "get_by_cluster_id scroll fallback failed for %s", cluster_id, exc_info=True
                )

            return None

        return await _run_blocking(_do_get)

    async def collection_size(self) -> int:
        """Return the total number of points in the collection."""
        info = await _run_blocking(lambda: self._raw_client.get_collection(COLLECTION_NAME))
        return info.points_count or 0

    async def get_vectors_by_filter(
        self,
        proto_ids: list[str],
        limit: int = 50,
    ) -> list[tuple[dict[str, Any], list[float]]]:
        """
        Return ``(payload, vector)`` for every point whose ``proto_id`` payload
        field is in *proto_ids*.

        Used by :class:`~app.agents.verification.VerificationAgent` to retrieve
        the ground-truth stored embedding vectors for nearby candidates so that
        cosine similarity can be computed without re-embedding the candidate
        texts (Option B from the Phase 3 design).

        Parameters
        ----------
        proto_ids:
            List of ``proto_id`` values (UUID strings) to fetch.
        limit:
            Maximum number of points scanned per scroll page. NOTE: this bounds
            a single page, not the total result count — see the pagination loop
            below. If callers pass a huge proto_ids list expecting all of them
            back, this now honours that (paginating until proto_ids is
            exhausted or Qdrant runs out of pages) rather than silently
            truncating at `limit` like the original single-scroll version did.

        Returns
        -------
        List of ``(payload_dict, vector)`` tuples in arbitrary order.
        Only points that actually exist in Qdrant are returned — missing
        IDs are silently skipped.
        """

        def _do_fetch() -> list[tuple[dict[str, Any], list[float]]]:
            results: list[tuple[dict[str, Any], list[float]]] = []
            if not proto_ids:
                return results

            scroll_filter = Filter(
                must=[FieldCondition(key="proto_id", match=MatchAny(any=proto_ids))]
            )

            remaining_ids = set(proto_ids)
            next_offset = None
            try:
                while remaining_ids:
                    points, next_offset = self._raw_client.scroll(
                        collection_name=COLLECTION_NAME,
                        scroll_filter=scroll_filter,
                        limit=limit,
                        offset=next_offset,
                        with_payload=True,
                        with_vectors=True,
                    )
                    if not points:
                        break

                    for p in points:
                        if p.payload is None:
                            continue
                        vec = _extract_vector(p.vector)
                        if vec is None:
                            continue
                        results.append((p.payload, vec))
                        matched_id = p.payload.get("proto_id")
                        if matched_id in remaining_ids:
                            remaining_ids.discard(matched_id)

                    if next_offset is None:
                        break
            except Exception as exc:  # pragma: no cover
                logger.warning("get_vectors_by_filter failed: %s", exc)

            if remaining_ids:
                logger.debug(
                    "get_vectors_by_filter: %d/%d proto_ids not found in Qdrant",
                    len(remaining_ids),
                    len(proto_ids),
                )
            return results

        return await _run_blocking(_do_fetch)

    async def upsert_verified(
        self,
        verified: VerifiedIncident,
        vector: list[float],
    ) -> None:
        """
        Persist a :class:`~app.schemas.VerifiedIncident` back into the Qdrant
        collection so that future incoming proto-incidents can discover and join
        this cluster.

        The point is tagged ``point_type="verified"`` in its payload to
        distinguish it from raw ``ProtoIncident`` points
        (``point_type="proto"``).

        Uses the ``cluster_id`` UUID fragment as the point ID so that
        successive upserts for the same cluster overwrite the previous
        verified snapshot rather than creating duplicates.
        """
        point_id = _cluster_id_to_point_id(verified.cluster_id)

        payload: dict[str, Any] = {
            "point_type": "verified",
            "cluster_id": verified.cluster_id,
            "source_provenance": [
                s.value if hasattr(s, "value") else str(s) for s in verified.source_provenance
            ],
            "lat": verified.lat,
            "lon": verified.lon,
            "timestamp_epoch": verified.timestamp.timestamp(),
            "confidence": verified.confidence,
            "severity": str(verified.severity),
            "status": str(verified.status),
        }

        # Add geo point for server-side geo filtering
        if verified.lat is not None and verified.lon is not None:
            payload["location"] = {"lat": verified.lat, "lon": verified.lon}

        point = PointStruct(id=point_id, vector=vector, payload=payload)

        await _run_blocking(
            lambda: self._raw_client.upsert(
                collection_name=COLLECTION_NAME,
                points=[point],
            )
        )
        logger.debug(
            "Upserted verified cluster_id=%s point_id=%d to Qdrant",
            verified.cluster_id,
            point_id,
        )

    async def get_incident(self, cluster_id: str) -> dict[str, Any] | None:
        """
        Return the payload dict for a verified incident cluster.

        Thin alias for :meth:`get_by_cluster_id` — provides a clean, stable
        name for callers that only need incident lookup (e.g. the Communication
        router).

        Parameters
        ----------
        cluster_id:
            The cluster identifier, e.g. ``"cluster_abc123"``.

        Returns
        -------
        dict | None
            Qdrant payload dict, or ``None`` if not found.
        """
        return await self.get_by_cluster_id(cluster_id)

    async def upsert_incident_status(
        self,
        cluster_id: str,
        new_status: str | Any,
    ) -> None:
        """
        Patch only the ``status`` field of an existing verified incident point.

        Uses Qdrant's ``set_payload`` operation so no re-embedding is needed.
        The point is located by its integer point ID derived from *cluster_id*
        (same derivation used in :meth:`upsert_verified`).

        Parameters
        ----------
        cluster_id:
            The cluster to update, e.g. ``"cluster_abc123"``.
        new_status:
            The new :class:`~app.schemas.IncidentStatus` value (or string).
        """
        status_str = new_status.value if hasattr(new_status, "value") else str(new_status)
        point_id = _cluster_id_to_point_id(cluster_id)

        def _do_patch() -> None:
            # Try direct point ID patch first
            try:
                self._raw_client.set_payload(
                    collection_name=COLLECTION_NAME,
                    payload={"status": status_str},
                    points=[point_id],
                )
                return
            except Exception:
                logger.debug(
                    "upsert_incident_status direct patch failed for %s, trying filter fallback",
                    cluster_id,
                    exc_info=True,
                )

            # Fallback: patch by cluster_id payload filter
            try:
                self._raw_client.set_payload(
                    collection_name=COLLECTION_NAME,
                    payload={"status": status_str},
                    points=Filter(
                        must=[FieldCondition(key="cluster_id", match=MatchValue(value=cluster_id))]
                    ),
                )
            except Exception as exc:
                logger.warning(
                    "upsert_incident_status fallback failed for %s: %s",
                    cluster_id,
                    exc,
                )

        await _run_blocking(_do_patch)
        logger.info("Status patched in Qdrant: cluster_id=%s → %s", cluster_id, status_str)


# ── Module-level singleton ────────────────────────────────────────────────────

_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Return the shared VectorStore singleton (initialised in main.py lifespan)."""
    if _vector_store is None:
        raise RuntimeError(
            "VectorStore not initialised. Call init_vector_store() during app startup."
        )
    return _vector_store


async def init_vector_store(qdrant_client: QdrantClient) -> VectorStore:
    """
    Initialise the VectorStore singleton and ensure the Qdrant collection exists.
    Called once from main.py lifespan.
    """
    global _vector_store
    _vector_store = VectorStore(qdrant_client=qdrant_client)
    await _vector_store.ensure_collection()
    return _vector_store
