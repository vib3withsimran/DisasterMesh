"""
Twitter Simulation Service — DisasterMesh
==========================================

Simulates real-time Twitter/social media monitoring for the demo pipeline.

Two modes:
  1. **Mock mode** (default): Reads from demo_data/social_posts/mock_tweets.json
     and feeds them through the ingest API at configurable intervals.
  2. **Random mode**: Generates fresh disaster tweets about Nepal floods
     for a more dynamic demo.

Usage:
    python -m app.services.twitter_sim               # mock mode
    python -m app.services.twitter_sim --mode random  # random Nepal flood tweets
    python -m app.services.twitter_sim --interval 10  # feed every 10 seconds
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MOCK_TWEETS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "demo_data" / "social_posts" / "mock_tweets.json"

# Nepal flood disaster tweets
_DISASTER_TWEETS = [
    "Breaking: Massive flooding in {area}, Nepal! Water levels rising fast, families trapped on rooftops. Need immediate rescue #NepalFloods #Emergency",
    "HELP! {area} Nepal is completely submerged. People stranded without food or water for 24 hours. Any relief teams? #NepalFlood",
    "Nepal flood crisis: {area} affected badly. Old people and children need immediate evacuation. Where is the help? #NepalRelief",
    "Hindi: {area} mein bahut zyada baadh aa gayi hai. Paani ghar tak pahunch gaya hai. Koi madad karo! #बाढ़ #NepalFlood",
    "Water levels in {area} river have crossed danger mark. Entire villages underwater. NDRF teams needed urgently #NepalDisaster",
    "Flash flood warning for {area} low-lying areas in Nepal. Evacuate NOW. This is not a drill. #FloodWarning",
    "Hindi: {area} Nepal mein baadh se bahut nuksan hua hai. Log bina khana pani ke phanse huye hain. Relief bhejo! #Relief",
    "Satellite imagery confirms severe flooding in {area} Terai region. Entire neighborhoods submerged #ClimateEmergency",
    "Crowd report: 500+ people stranded at {area} Nepal. No food or water for 24 hours #HumanitarianCrisis",
    "Bridge collapsed near {area} Nepal after heavy rainfall. Rescue teams cut off from affected areas #InfrastructureFailure",
    "Electricity and communication lines down in {area} Nepal. No contact with affected villages #PowerOutage",
    "Medical emergency in {area} Nepal. Hospital flooded, patients on roofs. Need emergency medical supplies #MedicalEmergency",
    "Nepal Red Cross requesting immediate aid for {area} flood victims. Thousands displaced #RedCross",
    "Social media posts from {area} Nepal showing devastating flood damage. Entire communities underwater #SocialMedia",
    "Nepal army deployed to {area} for rescue operations. Helicopters needed for aerial rescue #NepalArmy",
]

_AREAS = [
    "Kathmandu", "Pokhara", "Lalitpur", "Bhaktapur", " Biratnagar",
    "Birgunj", "Butwal", "Dharan", "Hetauda", "Janakpur", "Nepalgunj",
    "Terai", "Chitwan", "Morang", "Sunsari", "Rupandehi", "Kailali",
    "Kanchanpur", "Jhapa", "Kaski", "Gorkha", "Nuwakot", "Sindhupalchok",
    "Dolakha", "Rasuwa", "Makwanpur", "Bara", "Parsa", "Rautahat",
]

# Nepal bounding box
_NEPAL_LAT_MIN, _NEPAL_LAT_MAX = 26.35, 30.45
_NEPAL_LON_MIN, _NEPAL_LON_MAX = 80.05, 88.20


def _generate_random_tweet() -> dict[str, Any]:
    """Generate a random realistic disaster tweet about Nepal floods."""
    area = random.choice(_AREAS)
    text = random.choice(_DISASTER_TWEETS).format(area=area)
    lat = round(random.uniform(_NEPAL_LAT_MIN, _NEPAL_LAT_MAX), 6)
    lon = round(random.uniform(_NEPAL_LON_MIN, _NEPAL_LON_MAX), 6)
    return {
        "id": f"sim_{random.randint(100000, 999999)}",
        "text": text,
        "author": f"citizen_{random.randint(1000, 9999)}",
        "created_at": datetime.now(UTC).isoformat(),
        "location": {"lat": lat, "lon": lon},
        "source": "twitter",
        "lang": "hi" if "Hindi" in text or "हिंदी" in text else "en",
    }


def load_mock_tweets() -> list[dict[str, Any]]:
    """Load mock tweets from the JSON file."""
    if MOCK_TWEETS_PATH.exists():
        with open(MOCK_TWEETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Handle both formats: direct list or {tweets: [...]}
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "tweets" in data:
                return data["tweets"]
    return []


async def feed_mock_tweets(
    api_url: str = "http://localhost:8000",
    interval: float = 5.0,
    count: int | None = None,
) -> None:
    """
    Feed mock tweets through the /ingest/report endpoint at regular intervals.

    Parameters
    ----------
    api_url:
        Backend API base URL.
    interval:
        Seconds between each tweet.
    count:
        Number of tweets to send. None = loop forever through mock data.
    """
    tweets = load_mock_tweets()
    if not tweets:
        logger.warning("No mock tweets found at %s — generating random Nepal flood tweets", MOCK_TWEETS_PATH)
        tweets = [_generate_random_tweet() for _ in range(20)]

    logger.info("Starting mock tweet feed — %d tweets, interval=%.1fs", len(tweets), interval)

    sent = 0
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            for tweet in tweets:
                if count is not None and sent >= count:
                    logger.info("Mock tweet feed complete — sent %d tweets", sent)
                    return

                text = tweet.get("text", "")
                loc = tweet.get("location", {})
                lat = loc.get("lat", 28.6139)
                lon = loc.get("lon", 77.209)

                payload = {
                    "source": "social",
                    "text": text,
                    "lat": lat,
                    "lon": lon,
                }

                try:
                    resp = await client.post(f"{api_url}/ingest/report", json=payload)
                    if resp.status_code == 200:
                        logger.info("[TWEET %d] Fed: %s... → %s", sent + 1, text[:60], resp.status_code)
                        sent += 1
                    else:
                        logger.warning("[TWEET] Failed (%d): %s", resp.status_code, resp.text[:100])
                except httpx.ConnectError:
                    logger.warning(
                        "Backend not running at %s — retrying in 5s...\n"
                        "  (Start the backend first: uvicorn app.main:app --reload --port 8000)",
                        api_url,
                    )
                    await asyncio.sleep(5)
                    continue
                except Exception as exc:
                    logger.error("[TWEET] Error: %s", exc)

                await asyncio.sleep(interval)


async def feed_random_tweets(
    api_url: str = "http://localhost:8000",
    interval: float = 5.0,
    count: int = 10,
) -> None:
    """Generate and feed random Nepal flood tweets (for fresh demo data)."""
    logger.info("Generating %d random Nepal flood tweets, interval=%.1fs", count, interval)

    async with httpx.AsyncClient(timeout=10) as client:
        for i in range(count):
            tweet = _generate_random_tweet()
            payload = {
                "source": "social",
                "text": tweet["text"],
                "lat": tweet["location"]["lat"],
                "lon": tweet["location"]["lon"],
            }

            try:
                resp = await client.post(f"{api_url}/ingest/report", json=payload)
                logger.info("[TWEET %d/%d] Fed: %s... → %s", i + 1, count, tweet["text"][:60], resp.status_code)
            except httpx.ConnectError:
                logger.error("Cannot connect to %s — is the backend running?", api_url)
                break
            except Exception as exc:
                logger.error("[TWEET] Error: %s", exc)

            await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Twitter simulation feed for DisasterMesh (Nepal floods)")
    parser.add_argument("--api", default="http://localhost:8000", help="Backend API URL")
    parser.add_argument("--mode", choices=["mock", "random"], default="mock",
                        help="mock = use mock_tweets.json, random = generate fresh Nepal flood tweets")
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between tweets")
    parser.add_argument("--count", type=int, default=None, help="Number of tweets (None=infinite)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.mode == "mock":
        asyncio.run(feed_mock_tweets(args.api, args.interval, args.count))
    else:
        asyncio.run(feed_random_tweets(args.api, args.interval, args.count or 20))
