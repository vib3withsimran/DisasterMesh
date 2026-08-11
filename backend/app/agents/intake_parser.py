"""
Intake Parser Agent — LLM Smart Intake Layer (Phase 4.5).

Uses LangChain's ChatGroq with .with_structured_output(ParsedIntake) to parse
unstructured, multilingual (English, Hindi, Hinglish, mixed) crisis reports into
structured ParsedIntake objects.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import SecretStr

from app.schemas import ParsedIntake

# Ensure .env is explicitly loaded into os.environ
load_dotenv()

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a crisis report parser for DisasterMesh, an emergency response coordination system.
Your job is to analyze unstructured disaster/crisis reports submitted by citizens or social media posts in ANY language (English, Hindi, Hinglish, regional dialects, or mixed text).

Extract the following structured information accurately:
1. address: The location name, landmark, neighbourhood, city, or address mentioned (e.g. "Yamuna Bazar, Delhi", "Connaught Place", "sector 62 noida"). Null if no location name is mentioned.
2. lat / lon: Explicit numerical geographic coordinates if directly provided in the text (e.g. "lat 28.66, lon 77.23"). Null if coordinates are not explicitly written as numbers.
3. language: Detected language code ("hi" for Hindi, "en" for English, "hinglish" for Hindi written in Latin script, or appropriate code).
4. incident_type: Primary classification of the disaster ("flood", "fire", "building_collapse", "earthquake", "medical_emergency", "landslide", "storm", or "other").
5. needs: Boolean profile flagging what aid is required:
   - medical: True if injuries, bleeding, ambulance, hospital, or doctor needed.
   - shelter: True if homeless, displaced, shelter, or tent needed.
   - evacuation: True if evacuation, fleeing, or immediate removal needed.
   - rescue: True if trapped, stuck, underwater, under rubble, or SOS rescue needed.
   - water: True if drinking water or severe flooding water supply issue mentioned.
   - food: True if hunger, food, rations needed.
6. urgency_level: Integer from 1 (low/informational) to 5 (extreme SOS/immediate life threat).
7. time_reference: Time indicator string if mentioned (e.g. "since 2 hours ago", "this morning", "just now"). Null if absent.
8. cleaned_text: A concise, normalized English translation / summary of the crisis report.

Be extremely empathetic and precise. Never fabricate location names or coordinates that were not stated or implied in the text.
"""

# ── Tuning knobs ──────────────────────────────────────────────────────────────
LLM_TIMEOUT_S = 20.0  # per-attempt timeout for the Groq call
MAX_RETRIES = 3  # total attempts, including the first
BASE_BACKOFF_S = 0.5  # base for exponential backoff
MAX_BACKOFF_S = 8.0  # cap so a stuck dependency doesn't stall forever
MAX_INPUT_CHARS = 8000  # guard against absurdly large payloads driving cost/latency


class IntakeParsingError(RuntimeError):
    """Raised when the intake parser cannot produce a ParsedIntake after retries."""


class IntakeParserAgent:
    """Parses free-text crisis reports into structured ParsedIntake using ChatGroq."""

    def __init__(self, api_key: str | None = None, model_name: str | None = None) -> None:
        self.explicit_api_key = api_key
        self.explicit_model_name = model_name
        self._cache_key: tuple[str, str] | None = None
        self._structured_llm: Any | None = None

    def _get_api_key(self) -> str:
        if self.explicit_api_key is not None:
            return self.explicit_api_key.strip()
        env_val = os.getenv("GROQ_API_KEY")
        if env_val is not None:
            return env_val.strip()
        from app.config import get_settings

        return get_settings().groq_api_key.strip()

    def _get_model_name(self) -> str:
        if self.explicit_model_name is not None:
            return self.explicit_model_name.strip()
        env_val = os.getenv("GROQ_MODEL")
        if env_val is not None:
            return env_val.strip()
        from app.config import get_settings

        return (get_settings().groq_model or "llama-3.3-70b-versatile").strip()

    def is_available(self) -> bool:
        """Return True if GROQ_API_KEY is configured."""
        return bool(self._get_api_key())

    def _get_structured_llm(self, key: str, model_name: str) -> Any:
        """
        Return a cached structured-output LLM client for (key, model_name),
        building it once and reusing it across calls.
        """
        cache_key = (key, model_name)
        if self._structured_llm is not None and self._cache_key == cache_key:
            return self._structured_llm

        llm = ChatGroq(
            api_key=SecretStr(key),
            model=model_name,
            temperature=0.0,
            timeout=LLM_TIMEOUT_S,
            max_retries=0,  # we handle retries ourselves, with our own backoff/jitter
        )
        structured_llm = llm.with_structured_output(ParsedIntake)

        self._cache_key = cache_key
        self._structured_llm = structured_llm
        return structured_llm

    async def parse(self, raw_text: str) -> ParsedIntake:
        """
        Parse raw unstructured text using Groq LLM via LangChain.

        Retries transient failures up to MAX_RETRIES times with exponential
        backoff and jitter. Does NOT retry on missing configuration.

        Returns
        -------
        ParsedIntake

        Raises
        ------
        RuntimeError
            If GROQ_API_KEY is not configured.
        IntakeParsingError
            If the LLM call fails on every retry attempt.
        """
        if not raw_text or not raw_text.strip():
            raise ValueError("raw_text must be non-empty")

        text = raw_text.strip()
        if len(text) > MAX_INPUT_CHARS:
            logger.warning(
                "IntakeParserAgent input truncated from %d to %d chars", len(text), MAX_INPUT_CHARS
            )
            text = text[:MAX_INPUT_CHARS]

        key = self._get_api_key()
        if not key:
            raise RuntimeError("GROQ_API_KEY is not configured in environment")

        model_name = self._get_model_name()
        structured_llm = self._get_structured_llm(key, model_name)

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f'Report text to parse:\n"""{text}"""'),
        ]

        logger.info(
            "IntakeParserAgent parsing text (len=%d) via Groq model=%s", len(text), model_name
        )

        last_err: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = await structured_llm.ainvoke(messages)
                if isinstance(result, ParsedIntake):
                    return result
                return ParsedIntake.model_validate(result)
            except Exception as err:
                last_err = err
                is_last_attempt = attempt == MAX_RETRIES
                logger.warning(
                    "IntakeParserAgent LLM call failed (attempt %d/%d): %s",
                    attempt,
                    MAX_RETRIES,
                    err,
                )
                if is_last_attempt:
                    break
                backoff = min(BASE_BACKOFF_S * (2 ** (attempt - 1)), MAX_BACKOFF_S)
                jitter = random.uniform(0, backoff * 0.25)
                await asyncio.sleep(backoff + jitter)

        raise IntakeParsingError(
            f"IntakeParserAgent failed after {MAX_RETRIES} attempts: {last_err}"
        ) from last_err


_intake_parser: IntakeParserAgent | None = None


def get_intake_parser() -> IntakeParserAgent:
    """Return the shared IntakeParserAgent singleton."""
    global _intake_parser
    if _intake_parser is None:
        _intake_parser = IntakeParserAgent()
    return _intake_parser
