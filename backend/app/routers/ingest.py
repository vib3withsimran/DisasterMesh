"""Ingestion router — accepts reports from all source types."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.embeddings import get_embedding_service
from app.agents.intake_parser import get_intake_parser
from app.agents.intake_queue import get_intake_queue
from app.agents.situational import SituationalAgent
from app.agents.vector_store import get_vector_store
from app.db import get_db
from app.models import AuditLog, RawIngestionRecord
from app.schemas import (
    CitizenReportInput,
    IngestResponse,
    ProtoIncident,
    SatellitePolygonInput,
    SensorStreamInput,
    SocialPostInput,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Singleton agent — re-used across requests (geocoder client is stateless & thread-safe)
_situational_agent = SituationalAgent()


async def _persist(
    db: AsyncSession,
    record_id: str,
    source_type: str,
    raw_payload: dict,
    proto_dict: dict,
    language: str,
) -> None:
    """Save RawIngestionRecord + AuditLog entry inside the current session."""
    record = RawIngestionRecord(
        id=record_id,
        source_type=source_type,
        raw_payload=raw_payload,
        text=proto_dict.get("text", ""),
        lat=proto_dict.get("lat"),
        lon=proto_dict.get("lon"),
        address=proto_dict.get("address"),
        language=language,
        media_urls=proto_dict.get("media_urls", []),
        normalized_payload=proto_dict,
        created_at=datetime.now(UTC),
    )
    audit = AuditLog(
        action="ingest",
        entity_type="ProtoIncident",
        entity_id=record_id,
        details={"source_type": source_type},
    )
    db.add(record)
    db.add(audit)
    # commit happens automatically in get_db() on success


async def _index_in_vector_store(proto: ProtoIncident) -> None:
    """Embed proto incident and upsert to Qdrant vector store."""
    try:
        embedder = get_embedding_service()
        store = get_vector_store()

        vector = await embedder.embed_incident(proto)
        await store.upsert(proto, vector)

    except Exception as exc:
        logger.warning(
            "Failed to index proto incident %s in Qdrant: %s",
            proto.id,
            exc,
        )


@router.post("/report", response_model=IngestResponse, summary="Citizen report")
async def ingest_citizen_report(
    report: CitizenReportInput,
    db: AsyncSession = Depends(get_db),
) -> IngestResponse:
    """
    Accept a citizen report (SMS / WhatsApp / web form).

    If GROQ_API_KEY is configured, passes the free-text to the IntakeParserAgent (LLM layer)
    which extracts location address, language, incident type, needs, urgency level, etc.

    Rule: Device GPS coordinates (report.lat, report.lon) ALWAYS override LLM-extracted coordinates.

    Falls back gracefully to standard geocoding & keyword processing if LLM is unavailable or fails,
    and enqueues failed parsing requests to Redis retry queue.
    """
    parser = get_intake_parser()
    queue = get_intake_queue()

    if parser.is_available():
        try:
            parsed = await parser.parse(report.text)
            logger.info(
                "LLM Smart Intake parsed report: addr=%s lang=%s urgency=%d",
                parsed.address,
                parsed.language,
                parsed.urgency_level,
            )

            # Determine coordinates: GPS coords > LLM explicit coords > geocoded address
            lat, lon = report.lat, report.lon
            if (lat is None or lon is None) and (parsed.lat is not None and parsed.lon is not None):
                lat, lon = parsed.lat, parsed.lon

            address = report.address or parsed.address
            if (lat is None or lon is None) and address:
                resolved = await _situational_agent._geocode(address)
                if resolved:
                    lat, lon = resolved

            ts = report.timestamp or datetime.now(UTC)
            proto = ProtoIncident(
                source=report.source,
                text=parsed.cleaned_text or report.text,
                lat=lat,
                lon=lon,
                address=address,
                timestamp=ts,
                media_urls=report.media_urls,
                metadata={
                    "language": parsed.language,
                    "incident_type": parsed.incident_type,
                    "urgency_level": parsed.urgency_level,
                    "time_reference": parsed.time_reference,
                    "extracted_needs": parsed.needs.model_dump(),
                    "llm_parsed": True,
                },
                raw_payload=report.model_dump(),
            )
            language = parsed.language
        except Exception as err:
            logger.warning(
                "IntakeParserAgent failed (%s); processing via default pipeline and queuing retry",
                err,
            )
            proto = await _situational_agent.process_citizen_report(report)
            language = proto.metadata.get("language", "en")
            # Enqueue for background retry worker
            await queue.enqueue(proto.id, report.model_dump())
    else:
        proto = await _situational_agent.process_citizen_report(report)
        language = proto.metadata.get("language", "en")

    await _persist(
        db,
        proto.id,
        proto.source,
        proto.raw_payload,
        proto.model_dump(mode="json"),
        language,
    )
    await _index_in_vector_store(proto)
    logger.info(
        "Citizen report ingested id=%s (llm_parsed=%s)",
        proto.id,
        proto.metadata.get("llm_parsed", False),
    )
    return IngestResponse(message_id=proto.id, lat=proto.lat, lon=proto.lon)


@router.post("/social", response_model=IngestResponse, summary="Social post")
async def ingest_social_post(
    post: SocialPostInput,
    db: AsyncSession = Depends(get_db),
) -> IngestResponse:
    """Accept a social media post (tweet, news article)."""
    proto = await _situational_agent.process_social_post(post)
    language = proto.metadata.get("language", "en")
    await _persist(
        db,
        proto.id,
        proto.source,
        proto.raw_payload,
        proto.model_dump(mode="json"),
        language,
    )
    await _index_in_vector_store(proto)
    logger.info("Social post ingested id=%s", proto.id)
    return IngestResponse(message_id=proto.id, lat=proto.lat, lon=proto.lon)


@router.post("/satellite", response_model=IngestResponse, summary="Satellite polygon")
async def ingest_satellite_polygon(
    polygon: SatellitePolygonInput,
    db: AsyncSession = Depends(get_db),
) -> IngestResponse:
    """Accept a GeoJSON polygon from Sentinel-2 flood detection."""
    proto = await _situational_agent.process_satellite_polygon(polygon)
    await _persist(
        db,
        proto.id,
        proto.source,
        proto.raw_payload,
        proto.model_dump(mode="json"),
        "en",
    )
    await _index_in_vector_store(proto)
    logger.info("Satellite polygon ingested id=%s", proto.id)
    return IngestResponse(message_id=proto.id, lat=proto.lat, lon=proto.lon)


@router.post("/sensor", response_model=IngestResponse, summary="IoT sensor")
async def ingest_sensor_stream(
    sensor: SensorStreamInput,
    db: AsyncSession = Depends(get_db),
) -> IngestResponse:
    """Accept an IoT sensor reading (water level, air quality, etc.)."""
    proto = await _situational_agent.process_sensor(sensor)
    await _persist(
        db,
        proto.id,
        proto.source,
        proto.raw_payload,
        proto.model_dump(mode="json"),
        "en",
    )
    await _index_in_vector_store(proto)
    logger.info("Sensor reading ingested id=%s", proto.id)
    return IngestResponse(message_id=proto.id, lat=proto.lat, lon=proto.lon)
