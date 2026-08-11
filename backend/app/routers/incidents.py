from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query

from app.agents.vector_store import get_vector_store
from app.agents.verification import get_verification_agent
from app.agents.victim import get_victim_agent
from app.schemas import (
    AssessRequest,
    ProtoIncident,
    SeverityAssessment,
    SourceType,
    VerifiedIncident,
)

router = APIRouter()


@router.get("/search/semantic", summary="Semantic search for incidents")
async def search_incidents_semantic(
    q: str = Query(..., description="Query text"),
    limit: int = Query(10, description="Max results"),
    min_score: float = Query(0.0, description="Minimum similarity score [0..1]"),
) -> dict:
    """
    Search incidents by semantic similarity using LangChain embeddings & Qdrant.
    """
    store = get_vector_store()
    results = await store.search_similar(query_text=q, limit=limit, min_score=min_score)

    incidents = []
    for doc, score in results:
        payload = dict(doc.metadata) if hasattr(doc, "metadata") else {}
        payload.pop("_id", None)
        payload.pop("_collection_name", None)
        if hasattr(doc, "page_content") and "text" not in payload:
            payload["text"] = doc.page_content
        payload["similarity_score"] = float(score)
        incidents.append(payload)

    return {
        "query": q,
        "count": len(incidents),
        "incidents": incidents,
    }


@router.post("/verify", response_model=VerifiedIncident, summary="Verify a proto incident")
async def verify_proto_incident(proto: ProtoIncident) -> VerifiedIncident:
    """
    Run the VerificationAgent 3D clustering & deduplication pipeline on a ProtoIncident.
    """
    agent = get_verification_agent()
    return await agent.verify(proto)


@router.post(
    "/{proto_id}/verify", response_model=VerifiedIncident, summary="Verify an ingested report by ID"
)
async def verify_incident_by_id(proto_id: str) -> VerifiedIncident:
    """
    Fetch a proto incident by ID from Qdrant vector store and run the
    VerificationAgent 3D clustering & deduplication pipeline on it.
    """
    store = get_vector_store()
    payload = await store.get_by_proto_id(proto_id)
    if not payload:
        raise HTTPException(status_code=404, detail=f"Proto incident {proto_id} not found")

    src_str = payload.get("source", "sms")
    try:
        source = SourceType(src_str)
    except ValueError:
        source = SourceType.SMS

    ts_epoch = payload.get("timestamp_epoch")
    ts = datetime.fromtimestamp(ts_epoch, tz=UTC) if ts_epoch else datetime.now(UTC)

    proto = ProtoIncident(
        id=payload.get("proto_id", proto_id),
        source=source,
        text=payload.get("text", ""),
        lat=payload.get("lat"),
        lon=payload.get("lon"),
        address=payload.get("address"),
        timestamp=ts,
    )

    agent = get_verification_agent()
    return await agent.verify(proto)


@router.get("/{proto_id}", summary="Get incident by proto ID")
async def get_incident(proto_id: str) -> dict:
    """
    Fetch a proto incident by ID from Qdrant vector store.
    """
    store = get_vector_store()
    incident = await store.get_by_proto_id(proto_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {proto_id} not found")
    return incident


@router.get("/", summary="Geo query for nearby incidents")
async def query_incidents(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    radius: float = Query(5000.0, description="Radius in metres"),
    limit: int = Query(50, description="Max results"),
) -> dict:
    """
    Return proto incidents within `radius` metres of (lat, lon).
    """
    store = get_vector_store()
    incidents = await store.search_nearby(lat=lat, lon=lon, radius_m=radius, limit=limit)
    return {
        "lat": lat,
        "lon": lon,
        "radius_m": radius,
        "count": len(incidents),
        "incidents": incidents,
    }


@router.post(
    "/{cluster_id}/assess",
    response_model=SeverityAssessment,
    summary="Assess severity & needs for a verified incident cluster",
)
async def assess_incident(cluster_id: str, body: AssessRequest) -> SeverityAssessment:
    """
    Run the VictimAgent needs-extraction and multi-factor severity scoring
    pipeline on a verified incident cluster.

    The request body mirrors a ``VerifiedIncident`` and adds an optional
    ``text`` field containing the original report text used for bilingual
    keyword extraction.

    Returns a ``SeverityAssessment`` with:
    - ``needs``          — structured boolean profile (medical, shelter, …)
    - ``severity_score`` — 0.0–1.0 computed by the multi-factor model
    - ``priority``       — P1 (critical) … P4 (low)
    - ``factors``        — per-factor breakdown for transparency
    """
    if body.cluster_id != cluster_id:
        raise HTTPException(
            status_code=422,
            detail=(
                f"cluster_id in URL ('{cluster_id}') does not match "
                f"cluster_id in body ('{body.cluster_id}')."
            ),
        )

    # Reconstruct a VerifiedIncident from the request body
    incident = VerifiedIncident(
        cluster_id=body.cluster_id,
        source_provenance=body.source_provenance,
        lat=body.lat,
        lon=body.lon,
        timestamp=body.timestamp,
        confidence=body.confidence,
        severity=body.severity,
        needs=body.needs,
        media_urls=body.media_urls,
        status=body.status,
    )

    agent = get_victim_agent()
    return await agent.assess(incident, text=body.text)
