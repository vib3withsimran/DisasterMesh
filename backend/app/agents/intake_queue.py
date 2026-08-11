"""
Intake Queue — Redis-backed retry queue for pending LLM intake parsing tasks (Phase 4.5).

If Groq API call fails or is rate-limited, raw reports are queued here and retried
by a background worker every 30 seconds. If Redis is unavailable, an in-memory queue
acts as fallback.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from app.agents.intake_parser import get_intake_parser

logger = logging.getLogger(__name__)

_QUEUE_KEY = "disastermesh:intake:pending_queue"
_MAX_RETRIES = 5

_intake_queue: IntakeQueue | None = None


def get_intake_queue() -> IntakeQueue:
    """Return the shared IntakeQueue singleton."""
    global _intake_queue
    if _intake_queue is None:
        _intake_queue = IntakeQueue()
    return _intake_queue


class IntakeQueue:
    """Queue for retrying failed LLM intake parsing requests."""

    def __init__(self, redis_url: str | None = None) -> None:
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379").strip()
        self._in_memory_queue: list[dict[str, Any]] = []

    async def enqueue(self, message_id: str, raw_payload: dict[str, Any], retries: int = 0) -> None:
        """Enqueue a report item for background LLM parsing retry."""
        item = {
            "message_id": message_id,
            "raw_payload": raw_payload,
            "retries": retries,
        }

        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(self.redis_url, socket_timeout=2.0)
            await client.rpush(_QUEUE_KEY, json.dumps(item))
            await client.aclose()
            logger.info("Enqueued intake item %s to Redis queue (retries=%d)", message_id, retries)
        except Exception as err:
            logger.warning("Redis enqueue failed (%s), storing in in-memory queue fallback", err)
            self._in_memory_queue.append(item)

    async def process_pending(self) -> int:
        """
        Process pending queued intake items.

        Attempt to parse each item via IntakeParserAgent. If successful, pass
        the resulting report through the ingestion pipeline. If parsing fails
        and retries < 5, re-enqueue.

        Returns
        -------
        int
            Number of successfully processed items.
        """
        parser = get_intake_parser()
        if not parser.is_available():
            # Groq still not available, skip processing turn
            return 0

        items_to_process: list[dict[str, Any]] = []

        # 1. Pop from Redis if available
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(self.redis_url, socket_timeout=2.0)
            while True:
                raw_item = await client.lpop(_QUEUE_KEY)
                if not raw_item:
                    break
                if isinstance(raw_item, (str, bytes)):
                    items_to_process.append(json.loads(raw_item))
            await client.aclose()
        except Exception as err:
            logger.debug("Redis queue pop skipped/failed: %s", err)

        # 2. Drain in-memory queue
        if self._in_memory_queue:
            items_to_process.extend(self._in_memory_queue)
            self._in_memory_queue.clear()

        if not items_to_process:
            return 0

        logger.info("IntakeQueue processing %d pending intake items", len(items_to_process))
        processed_count = 0

        from app.agents.situational import get_situational_agent

        situational_agent = get_situational_agent()

        for item in items_to_process:
            msg_id = item.get("message_id", "")
            raw_payload = item.get("raw_payload", {})
            retries = item.get("retries", 0)
            raw_text = raw_payload.get("text", "")

            try:
                parsed = await parser.parse(raw_text)
                logger.info(
                    "Successfully retried LLM parse for msg=%s: %s",
                    msg_id,
                    parsed.cleaned_text[:50],
                )

                # Construct ProtoIncident using parsed result
                proto = await situational_agent.normalize_report(
                    text=parsed.cleaned_text or raw_text,
                    source=raw_payload.get("source", "sms"),
                    lat=raw_payload.get("lat") or parsed.lat,
                    lon=raw_payload.get("lon") or parsed.lon,
                    address=raw_payload.get("address") or parsed.address,
                    media_urls=raw_payload.get("media_urls", []),
                    metadata={
                        "llm_parsed": True,
                        "language": parsed.language,
                        "incident_type": parsed.incident_type,
                        "urgency_level": parsed.urgency_level,
                        "time_reference": parsed.time_reference,
                        "extracted_needs": parsed.needs.model_dump(),
                    },
                    timestamp=raw_payload.get("timestamp"),
                )
                await situational_agent.ingest(proto)
                processed_count += 1

            except Exception as parse_err:
                logger.warning(
                    "Retry parsing failed for msg=%s (retries=%d): %s", msg_id, retries, parse_err
                )
                if retries + 1 < _MAX_RETRIES:
                    await self.enqueue(msg_id, raw_payload, retries=retries + 1)
                else:
                    logger.error(
                        "Max retries (%d) reached for msg=%s. Falling back to basic ingestion.",
                        _MAX_RETRIES,
                        msg_id,
                    )
                    # Fallback standard ingest
                    proto = await situational_agent.normalize_report(
                        text=raw_text,
                        source=raw_payload.get("source", "sms"),
                        lat=raw_payload.get("lat"),
                        lon=raw_payload.get("lon"),
                        address=raw_payload.get("address"),
                        media_urls=raw_payload.get("media_urls", []),
                        timestamp=raw_payload.get("timestamp"),
                    )
                    await situational_agent.ingest(proto)

        return processed_count
