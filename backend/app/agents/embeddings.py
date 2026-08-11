"""
Embedding Service — Phase 2.

Uses LangChain's HuggingFaceEmbeddings wrapper around
sentence-transformers/all-MiniLM-L6-v2 (384-dim, free, local, no API key).

Advantages of the LangChain interface:
- Swap providers later (Google, OpenAI) by changing one line in get_embeddings().
- Built-in async support via aembed_query / aembed_documents.
- Consistent interface used by later phases (Phase 4 LLM extraction).

Key design:
- Model loaded once as a module-level singleton.
- encode() is CPU-bound; offloaded to a thread pool so the event loop
  is never blocked.
- Geo-aware embedding: "text near lat,lon" nudges spatially co-located
  reports closer in the vector space, aiding Phase 3 dedup clustering.
"""

from __future__ import annotations

import asyncio
import logging

import numpy as np
from langchain_huggingface import HuggingFaceEmbeddings

from app.schemas import ProtoIncident

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # fixed for this model


# ── Singleton LangChain embeddings ────────────────────────────────────────────

_lc_embeddings: HuggingFaceEmbeddings | None = None


def get_langchain_embeddings() -> HuggingFaceEmbeddings:
    """
    Return the shared LangChain HuggingFaceEmbeddings singleton.

    First call downloads ~90 MB to ~/.cache/huggingface/ (one-time).
    Subsequent calls return the cached instance in <1 ms.
    """
    global _lc_embeddings
    if _lc_embeddings is None:
        logger.info(
            "Loading LangChain HuggingFaceEmbeddings model %r (first call may download ~90 MB)",
            MODEL_NAME,
        )
        _lc_embeddings = HuggingFaceEmbeddings(
            model_name=MODEL_NAME,
            encode_kwargs={"normalize_embeddings": True},  # cosine-ready vectors
        )
        logger.info("Embedding model loaded — dim=%d", EMBEDDING_DIM)
    return _lc_embeddings


# ── Service ───────────────────────────────────────────────────────────────────


class EmbeddingService:
    """
    Async embedding service built on LangChain's HuggingFaceEmbeddings.

    All public methods are async and safe to call from FastAPI route handlers.
    The CPU-bound encode step is offloaded to a thread pool executor so the
    event loop is never blocked.
    """

    def __init__(self) -> None:
        self._lc = get_langchain_embeddings()

    async def embed_text(self, text: str) -> list[float]:
        """
        Encode a single text string into a 384-dim float list.

        Uses LangChain's aembed_query() which handles async correctly.
        """
        loop = asyncio.get_event_loop()

        # SentenceTransformer inference is CPU-bound. Running many concurrent
        # inference calls causes CPU contention and is slower than serializing
        # the small inference workload.
        async with _embedding_semaphore:
            vector: list[float] = await loop.run_in_executor(
                None,
                self._lc.embed_query,
                text,
            )

        return vector

    async def embed_incident(self, proto: ProtoIncident) -> list[float]:
        """
        Embed a ProtoIncident using text + optional location context.

        Appending "near lat,lon" creates geo-aware vectors — semantically
        similar reports at the same location cluster more tightly.
        This is the key input to Phase 3 dedup clustering.
        """
        if proto.lat is not None and proto.lon is not None:
            combined = f"{proto.text} near {proto.lat:.4f},{proto.lon:.4f}"
        else:
            combined = proto.text
        return await self.embed_text(combined)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed multiple texts in a single batch call (more efficient than
        calling embed_text() in a loop for large batches).
        """
        loop = asyncio.get_event_loop()
        vectors: list[list[float]] = await loop.run_in_executor(
            None, self._lc.embed_documents, texts
        )
        return vectors

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """
        Cosine similarity between two vectors.

        Since normalize_embeddings=True, dot product == cosine similarity.
        Used by Phase 3 VerificationAgent for semantic dedup.
        """
        va = np.array(a, dtype=np.float32)
        vb = np.array(b, dtype=np.float32)
        denom = np.linalg.norm(va) * np.linalg.norm(vb)
        if denom < 1e-8:
            return 0.0
        return float(np.dot(va, vb) / denom)


# ── Module-level singleton ────────────────────────────────────────────────────

_embedding_service: EmbeddingService | None = None
_embedding_semaphore = asyncio.Semaphore(1)


def get_embedding_service() -> EmbeddingService:
    """Return the shared EmbeddingService singleton."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
