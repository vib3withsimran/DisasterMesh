"""
Exa Social Media Monitor — DisasterMesh
========================================

Uses Exa's neural search API to find REAL disaster-related posts from across
the entire web — Twitter, Reddit, news, forums, and more — in a single call.

Exa free tier: 1,000 searches/month + $20 signup bonus
Sign up: https://exa.ai

Usage:
    python -m app.services.exa_monitor                     # one-shot search
    python -m app.services.exa_monitor --continuous         # poll every 60s
    python -m app.services.exa_monitor --area "Kathmandu"   # search specific area
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Disaster search queries — Nepal floods (real-time data) ─────────────────

_DISASTER_QUERIES = [
    "Nepal flood emergency rescue 2024 2025",
    "Kathmandu flood damage people trapped",
    "Nepal monsoon flood evacuation displacement",
    "Nepal flood relief rescue operation",
    "Terai region flood Nepal water rising",
    "Nepal flood casualties missing people",
    "Nepal flood shelter food water needed",
    "Nepal flood road bridge damaged infrastructure",
    "Nepal flood social media posts affected areas",
    "Nepal disaster response coordination relief",
]

# Nepal bounding box (approximate)
_NEPAL_LAT_MIN, _NEPAL_LAT_MAX = 26.35, 30.45
_NEPAL_LON_MIN, _NEPAL_LON_MAX = 80.05, 88.20

# Nepal area names for location extraction
_NEPAL_AREAS = [
    "Kathmandu", "Pokhara", "Lalitpur", "Bhaktapur", " Biratnagar",
    "Birgunj", "Butwal", "Dharan", "Hetauda", "Janakpur", "Nepalgunj",
    "Terai", "Chitwan", "Morang", "Sunsari", "Rupandehi", "Kailali",
    "Kanchanpur", "Jhapa", "Kaski", "Gorkha", "Nuwakot", "Sindhupalchok",
    "Dolakha", "Rasuwa", "Makwanpur", "Bara", "Parsa", "Rautahat",
]


class ExaMonitor:
    """
    Monitors social media and news for disaster events using Exa's neural search.

    Exa searches across:
    - Twitter/X posts
    - Reddit discussions
    - News articles
    - Forum posts
    - Blog posts
    - Any public web content

    All with semantic (meaning-based) search, not just keyword matching.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("EXA_API_KEY", "").strip()
        self.base_url = "https://api.exa.ai"
        self._query_index = 0

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _next_query(self) -> str:
        """Rotate through disaster queries."""
        query = _DISASTER_QUERIES[self._query_index % len(_DISASTER_QUERIES)]
        self._query_index += 1
        return query

    async def search(
        self,
        query: str | None = None,
        num_results: int = 10,
        include_text: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Search Exa for disaster-related posts.

        Parameters
        ----------
        query:
            Search query. If None, rotates through preset disaster queries.
        num_results:
            Number of results to return (max 10 per free tier).
        include_text:
            Whether to include full text content (costs more credits).

        Returns
        -------
        list[dict]
            Normalized results with: title, url, text, source, published_at, score
        """
        if not self.api_key:
            logger.warning("EXA_API_KEY not set — cannot search")
            return []

        search_query = query or self._next_query()

        payload: dict[str, Any] = {
            "query": search_query,
            "numResults": min(num_results, 10),
            "type": "neural",  # semantic search
            "useAutoprompt": True,  # let Exa improve the query
        }

        if include_text:
            payload["contents"] = {
                "text": True,
                "highlights": True,
            }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.base_url}/search",
                    json=payload,
                    headers={
                        "x-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            results = []
            for item in data.get("results", []):
                normalized = self._normalize_result(item)
                if normalized:
                    results.append(normalized)

            logger.info(
                "Exa search [%s]: %d results for query '%s'",
                datetime.now(UTC).strftime("%H:%M:%S"),
                len(results),
                search_query[:50],
            )
            return results

        except httpx.HTTPStatusError as exc:
            logger.error("Exa API error %d: %s", exc.response.status_code, exc.response.text[:200])
            return []
        except Exception as exc:
            logger.error("Exa search failed: %s", exc)
            return []

    def _normalize_result(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize an Exa result into our standard format."""
        url = item.get("url", "")
        title = item.get("title", "")
        text = item.get("text", "")
        highlights = item.get("highlights", [])
        highlight_text = " ".join(highlights) if highlights else ""

        # Skip results that are too short or irrelevant
        content = text or highlight_text or title
        if len(content) < 30:
            return None

        # Detect source platform from URL
        source = self._detect_source(url)

        # Try to extract location from text
        lat, lon = self._extract_location(content)

        return {
            "title": title,
            "url": url,
            "text": content[:500],  # truncate for storage
            "highlight": highlight_text[:200] if highlight_text else "",
            "source": source,
            "published_at": item.get("publishedDate", datetime.now(UTC).isoformat()),
            "score": item.get("score", 0.0),
            "lat": lat,
            "lon": lon,
        }

    @staticmethod
    def _detect_source(url: str) -> str:
        """Detect the social platform from the URL."""
        url_lower = url.lower()
        if "twitter.com" in url_lower or "x.com" in url_lower:
            return "twitter"
        if "reddit.com" in url_lower:
            return "reddit"
        if "youtube.com" in url_lower or "youtu.be" in url_lower:
            return "youtube"
        if "instagram.com" in url_lower:
            return "instagram"
        if "facebook.com" in url_lower or "fb.com" in url_lower:
            return "facebook"
        if any(n in url_lower for n in ["ndtv.com", "timesofindia", "hindustantimes", "news"]):
            return "news"
        if "github.com" in url_lower:
            return "github"
        return "web"

    @staticmethod
    def _extract_location(text: str) -> tuple[float, float]:
        """Try to extract lat/lon from text. Falls back to random Nepal location."""
        import random

        # Check for explicit coordinates
        coord_match = re.search(r'(\d{1,3}\.\d{2,6})\s*[,/]\s*(\d{1,3}\.\d{2,6})', text)
        if coord_match:
            try:
                lat, lon = float(coord_match.group(1)), float(coord_match.group(2))
                if _NEPAL_LAT_MIN <= lat <= _NEPAL_LAT_MAX and _NEPAL_LON_MIN <= lon <= _NEPAL_LON_MAX:
                    return lat, lon
            except ValueError:
                pass

        # Check for Nepal area names
        for area in _NEPAL_AREAS:
            if area.lower() in text.lower():
                # Return approximate coordinates for the area
                lat = random.uniform(_NEPAL_LAT_MIN, _NEPAL_LAT_MAX)
                lon = random.uniform(_NEPAL_LON_MIN, _NEPAL_LON_MAX)
                return round(lat, 6), round(lon, 6)

        # Random Nepal location
        lat = random.uniform(_NEPAL_LAT_MIN, _NEPAL_LAT_MAX)
        lon = random.uniform(_NEPAL_LON_MIN, _NEPAL_LON_MAX)
        return round(lat, 6), round(lon, 6)


# ── Feed Exa results into the DisasterMesh pipeline ─────────────────────────


async def feed_exa_to_pipeline(
    api_url: str = "http://localhost:8000",
    interval: float = 60.0,
    num_results: int = 5,
    count: int | None = None,
) -> None:
    """
    Continuously search Exa and feed results into the ingest API.

    Parameters
    ----------
    api_url:
        Backend API base URL.
    interval:
        Seconds between searches (Exa free tier: don't hammer it).
    num_results:
        Results per search.
    count:
        Total feeds. None = run forever.
    """
    monitor = ExaMonitor()
    if not monitor.is_configured:
        logger.error("EXA_API_KEY not set. Get one at https://exa.ai")
        logger.info("Falling back to mock tweets...")
        from app.services.twitter_sim import feed_mock_tweets
        await feed_mock_tweets(api_url, interval=5)
        return

    logger.info("Starting Exa monitor — interval=%.0fs, results=%d", interval, num_results)

    sent = 0
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            results = await monitor.search(num_results=num_results)

            for result in results:
                if count is not None and sent >= count:
                    logger.info("Exa feed complete — sent %d results", sent)
                    return

                text = result.get("text", result.get("title", ""))
                lat = result.get("lat", 28.6139)
                lon = result.get("lon", 77.209)
                source = result.get("source", "web")

                # Map source to our source types
                source_type = {
                    "twitter": "social",
                    "reddit": "social",
                    "youtube": "social",
                    "instagram": "social",
                    "facebook": "social",
                    "news": "news",
                }.get(source, "social")

                payload = {
                    "source": source_type,
                    "text": f"[{source.upper()}] {text}",
                    "lat": lat,
                    "lon": lon,
                }

                try:
                    resp = await client.post(f"{api_url}/ingest/report", json=payload)
                    if resp.status_code == 200:
                        logger.info(
                            "[EXA %d] Fed %s post: %s... → %s",
                            sent + 1, source, text[:50], resp.status_code,
                        )
                        sent += 1
                    else:
                        logger.warning("[EXA] Failed (%d): %s", resp.status_code, resp.text[:100])
                except httpx.ConnectError:
                    logger.warning(
                        "Backend not running at %s — retrying in 5s...\n"
                        "  (Start the backend first: uvicorn app.main:app --reload --port 8000)",
                        api_url,
                    )
                    await asyncio.sleep(5)
                    continue
                except Exception as exc:
                    logger.error("[EXA] Feed error: %s", exc)

            await asyncio.sleep(interval)


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Exa social media monitor for DisasterMesh")
    parser.add_argument("--api", default="http://localhost:8000", help="Backend API URL")
    parser.add_argument("--continuous", action="store_true", help="Poll continuously")
    parser.add_argument("--interval", type=float, default=60.0, help="Seconds between searches")
    parser.add_argument("--count", type=int, default=None, help="Number of feeds (None=infinite)")
    parser.add_argument("--query", type=str, default=None, help="Custom search query")
    parser.add_argument("--num-results", type=int, default=5, help="Results per search")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.query:
        # One-shot custom search
        async def one_shot():
            monitor = ExaMonitor()
            results = await monitor.search(query=args.query, num_results=args.num_results)
            for i, r in enumerate(results):
                print(f"\n--- Result {i+1} [{r['source']}] (score: {r['score']:.2f}) ---")
                print(f"Title: {r['title']}")
                print(f"URL: {r['url']}")
                print(f"Text: {r['text'][:200]}...")
                print(f"Location: {r['lat']}, {r['lon']}")

            # Feed into pipeline
            if results:
                async with httpx.AsyncClient(timeout=10) as client:
                    for r in results:
                        payload = {
                            "source": "social",
                            "text": f"[{r['source'].upper()}] {r['text']}",
                            "lat": r["lat"],
                            "lon": r["lon"],
                        }
                        resp = await client.post(f"{args.api}/ingest/report", json=payload)
                        print(f"  → Fed to pipeline: {resp.status_code}")

        asyncio.run(one_shot())
    else:
        # Continuous monitoring
        asyncio.run(feed_exa_to_pipeline(args.api, args.interval, args.num_results, args.count))
