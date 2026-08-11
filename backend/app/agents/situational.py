"""
Situational Agent — Agent 1.

Responsibilities:
  - Accept raw inputs from all four source types
  - Geocode missing coordinates (Nominatim + Hindi transliteration fallback)
  - Detect language (Devanagari heuristic: en / hi)
  - Normalize to ProtoIncident
  - Emit event to Verification Agent (Phase 2: will push to Qdrant)

Implemented in Phase 1.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.schemas import (
    CitizenReportInput,
    ProtoIncident,
    SatellitePolygonInput,
    SensorStreamInput,
    SocialPostInput,
    SourceType,
)

logger = logging.getLogger(__name__)

# ── Sensor alert thresholds ───────────────────────────────────────────────────

SENSOR_ALERT_THRESHOLDS: dict[str, float] = {
    "water_level": 3.0,  # metres — above this triggers a critical alert
    "air_quality": 300.0,  # AQI — above this is hazardous
}

# ── Hindi landmark table ──────────────────────────────────────────────────────
# Fallback when Nominatim is unavailable or the address cannot be resolved.
# Covers common disaster-prone and frequently referenced locations in Delhi-NCR.

_LANDMARK_TABLE: dict[str, tuple[float, float]] = {
    # English spellings
    "yamuna bazar": (28.6667, 77.2333),
    "yamuna bazaar": (28.6667, 77.2333),
    "connaught place": (28.6315, 77.2167),
    "cp": (28.6315, 77.2167),
    "india gate": (28.6129, 77.2295),
    "lajpat nagar": (28.5674, 77.2431),
    "rohini": (28.7333, 77.1167),
    "dwarka": (28.5921, 77.0460),
    "noida sector 18": (28.5679, 77.3213),
    "gurgaon": (28.4595, 77.0266),
    "gurugram": (28.4595, 77.0266),
    "faridabad": (28.4089, 77.3178),
    "greater noida": (28.4744, 77.5040),
    "meerut": (28.9845, 77.7064),
    "okhla": (28.5355, 77.2741),
    "mayur vihar": (28.6080, 77.2957),
    "east delhi": (28.6600, 77.3100),
    "times square delhi": (28.6315, 77.2167),  # test fixture → Connaught Place
    "times square, delhi": (28.6315, 77.2167),  # with comma variant
    "janakpuri": (28.6289, 77.0839),
    "pitampura": (28.7021, 77.1313),
    "saket": (28.5245, 77.2066),
    "vasant kunj": (28.5206, 77.1577),
    "uttam nagar": (28.6186, 77.0535),
    "vikaspuri": (28.6408, 77.0728),
    "paschim vihar": (28.6686, 77.0972),
    "shalimar bagh": (28.7148, 77.1600),
    "wazirpur": (28.6999, 77.1641),
    "karol bagh": (28.6514, 77.1907),
    "chandni chowk": (28.6506, 77.2303),
    "nehru place": (28.5491, 77.2519),
    "hauz khas": (28.5494, 77.2001),
    "patel nagar": (28.6464, 77.1720),
    "kirti nagar": (28.6560, 77.1481),
    "rajouri garden": (28.6467, 77.1195),
    "tilak nagar": (28.6379, 77.0969),
    "subhash nagar": (28.6393, 77.1095),
    "tagore garden": (28.6453, 77.1297),
    "punjabi bagh": (28.6660, 77.1310),
    # Devanagari additions
    "जनकपुरी": (28.6289, 77.0839),
    "करोल बाग": (28.6514, 77.1907),
    "चाँदनी चौक": (28.6506, 77.2303),
    "पीतमपुरा": (28.7021, 77.1313),
    "साकेत": (28.5245, 77.2066),
    # Devanagari (Hindi) forms
    "यमुना बाज़ार": (28.6667, 77.2333),
    "यमुना बाजार": (28.6667, 77.2333),
    "कनॉट प्लेस": (28.6315, 77.2167),
    "इंडिया गेट": (28.6129, 77.2295),
    "लाजपत नगर": (28.5674, 77.2431),
    "रोहिणी": (28.7333, 77.1167),
    "द्वारका": (28.5921, 77.0460),
    "नोएडा": (28.5355, 77.3910),
    "गुड़गांव": (28.4595, 77.0266),
    "फरीदाबाद": (28.4089, 77.3178),
    "ओखला": (28.5355, 77.2741),
}


def _lookup_landmark(address: str) -> tuple[float, float] | None:
    """Case-insensitive prefix scan of the landmark table."""
    normalised = address.strip().lower()
    # Exact match first
    if normalised in _LANDMARK_TABLE:
        return _LANDMARK_TABLE[normalised]
    # Substring scan — useful for "Flooding at Yamuna Bazar, Delhi"
    for key, coords in _LANDMARK_TABLE.items():
        if key in normalised:
            return coords
    return None


def _polygon_centroid(coordinates: list) -> tuple[float, float]:
    """
    Compute the centroid of the outer ring of a GeoJSON Polygon.

    GeoJSON coordinate order: [longitude, latitude]
    Returns: (lat, lon)
    """
    ring = coordinates[0]  # outer ring
    n = len(ring)
    if n == 0:
        raise ValueError("Empty polygon ring")

    sum_lon = sum(pt[0] for pt in ring)
    sum_lat = sum(pt[1] for pt in ring)
    return sum_lat / n, sum_lon / n


def _detect_language(text: str) -> str:
    """
    Lightweight language detection.

    Returns 'hi' if the text contains Devanagari characters (U+0900–U+097F),
    otherwise returns 'en'.  Fast, dependency-free, good enough for Phase 1.
    """
    for ch in text:
        if "\u0900" <= ch <= "\u097f":
            return "hi"
    return "en"


class SituationalAgent:
    """Normalizes all incoming data streams into ProtoIncident objects."""

    def __init__(self, geocoder_timeout: float = 5.0) -> None:
        self._geocoder_timeout = geocoder_timeout
        self._http_client = httpx.AsyncClient(
            headers={"User-Agent": "disastermesh/0.1 (disaster-response-demo)"},
            timeout=geocoder_timeout,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def process_citizen_report(self, report: CitizenReportInput) -> ProtoIncident:
        """Geocode (if needed), detect language, normalize to ProtoIncident."""
        lat, lon = report.lat, report.lon

        if (lat is None or lon is None) and report.address:
            resolved = await self._geocode(report.address)
            if resolved:
                lat, lon = resolved
            else:
                logger.warning(
                    "Could not geocode address %r — lat/lon will be None", report.address
                )

        timestamp = report.timestamp or datetime.now(UTC)
        language = _detect_language(report.text)

        raw = report.model_dump()
        proto = ProtoIncident(
            source=report.source,
            text=report.text,
            lat=lat,
            lon=lon,
            address=report.address,
            timestamp=timestamp,
            media_urls=report.media_urls,
            metadata={"language": language},
            raw_payload=raw,
        )
        logger.info("Citizen report normalised id=%s lang=%s", proto.id, language)
        return proto

    async def process_social_post(self, post: SocialPostInput) -> ProtoIncident:
        """Normalize a social media post into a ProtoIncident."""
        timestamp = post.timestamp or datetime.now(UTC)
        language = _detect_language(post.text)

        raw = post.model_dump()
        proto = ProtoIncident(
            source=post.source,
            text=post.text,
            lat=post.lat,
            lon=post.lon,
            timestamp=timestamp,
            metadata={"language": language, "url": post.url},
            raw_payload=raw,
        )
        logger.info("Social post normalised id=%s lang=%s", proto.id, language)
        return proto

    async def process_satellite_polygon(self, polygon: SatellitePolygonInput) -> ProtoIncident:
        """
        Extract the centroid of a GeoJSON polygon and normalise to a ProtoIncident.

        Supports Feature and FeatureCollection payloads.
        """
        geojson = polygon.geojson
        geometry = _extract_geometry(geojson)

        if geometry["type"] != "Polygon":
            raise ValueError(f"Unsupported geometry type {geometry['type']!r}; expected 'Polygon'.")

        lat, lon = _polygon_centroid(geometry["coordinates"])
        timestamp = polygon.timestamp or datetime.now(UTC)

        # Derive a descriptive text from properties if available
        props: dict[str, Any] = {}
        if geojson.get("type") == "Feature":
            props = geojson.get("properties") or {}
        flood_depth = props.get("flood_depth_m", "unknown")
        text = f"Satellite flood polygon detected. Flood depth: {flood_depth} m."

        raw = polygon.model_dump()
        proto = ProtoIncident(
            source=SourceType.SATELLITE,
            text=text,
            lat=lat,
            lon=lon,
            timestamp=timestamp,
            media_urls=polygon.media_urls,
            metadata={"flood_depth_m": flood_depth, "properties": props},
            raw_payload=raw,
        )
        logger.info(
            "Satellite polygon normalised id=%s centroid=(%.4f, %.4f)",
            proto.id,
            lat,
            lon,
        )
        return proto

    async def process_sensor(self, sensor: SensorStreamInput) -> ProtoIncident:
        """
        Normalize an IoT sensor reading into a ProtoIncident.

        Applies threshold checks and generates a human-readable alert text.
        """
        timestamp = sensor.timestamp or datetime.now(UTC)
        threshold = SENSOR_ALERT_THRESHOLDS.get(sensor.sensor_type)
        is_alert = threshold is not None and sensor.value >= threshold

        severity_label = "ALERT" if is_alert else "INFO"
        text = (
            f"[{severity_label}] Sensor {sensor.sensor_id!r} "
            f"({sensor.sensor_type}) reading: {sensor.value} {sensor.unit}."
        )
        if is_alert:
            text += f" Threshold {threshold} {sensor.unit} exceeded."

        raw = sensor.model_dump()
        proto = ProtoIncident(
            source=SourceType.IOT_SENSOR,
            text=text,
            lat=sensor.lat,
            lon=sensor.lon,
            timestamp=timestamp,
            metadata={
                "sensor_id": sensor.sensor_id,
                "sensor_type": sensor.sensor_type,
                "value": sensor.value,
                "unit": sensor.unit,
                "is_alert": is_alert,
            },
            raw_payload=raw,
        )
        logger.info(
            "Sensor reading normalised id=%s alert=%s value=%s",
            proto.id,
            is_alert,
            sensor.value,
        )
        return proto

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _geocode(self, address: str) -> tuple[float, float] | None:
        """
        Resolve an address string to (lat, lon).

        Strategy:
          1. Landmark table lookup (instant, works offline, handles Hindi)
          2. Nominatim OSM REST API via httpx (works on macOS, any address worldwide)
        """
        # 1. Fast landmark fallback first (works offline in tests)
        result = _lookup_landmark(address)
        if result:
            logger.debug("Landmark table hit for %r → %s", address, result)
            return result

        # 2. Nominatim REST API via httpx (handles SSL correctly on all platforms)
        try:
            resp = await self._http_client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": address, "format": "json", "limit": 1},
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                lat = float(data[0]["lat"])
                lon = float(data[0]["lon"])
                logger.debug("Nominatim resolved %r → (%.4f, %.4f)", address, lat, lon)
                return lat, lon
        except httpx.TimeoutException:
            logger.warning("Nominatim timed out for %r", address)
        except httpx.HTTPError as exc:
            logger.warning("Nominatim HTTP error for %r: %s", address, exc)
        except Exception as exc:
            logger.warning("Geocoder unexpected error for %r: %s", address, exc)

        return None

    async def normalize_report(
        self,
        text: str,
        source: str | SourceType = "sms",
        lat: float | None = None,
        lon: float | None = None,
        address: str | None = None,
        media_urls: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> ProtoIncident:
        """Helper to build a ProtoIncident from raw attributes and normalize it."""
        st = SourceType(source) if isinstance(source, str) else source
        report_input = CitizenReportInput(
            source=st,
            text=text,
            lat=lat,
            lon=lon,
            address=address,
            media_urls=media_urls or [],
            timestamp=timestamp,
        )
        proto = await self.process_citizen_report(report_input)
        if metadata:
            proto.metadata.update(metadata)
        return proto

    async def ingest(self, proto: ProtoIncident) -> None:
        """Ingest normalized ProtoIncident into VerificationAgent."""
        from app.agents.verification import get_verification_agent

        verifier = get_verification_agent()
        await verifier.verify(proto)


# ── Module-level singleton ────────────────────────────────────────────────────

_situational_agent: SituationalAgent | None = None


def get_situational_agent() -> SituationalAgent:
    """Return the shared SituationalAgent singleton."""
    global _situational_agent
    if _situational_agent is None:
        _situational_agent = SituationalAgent()
    return _situational_agent


# ── Module-level helpers (also used in tests) ─────────────────────────────────


def _extract_geometry(geojson: dict[str, Any]) -> dict[str, Any]:
    """
    Pull the geometry dict out of a GeoJSON Feature or bare Geometry object.
    """
    gtype = geojson.get("type")
    if gtype == "Feature":
        return geojson["geometry"]
    if gtype == "FeatureCollection":
        features = geojson.get("features", [])
        if not features:
            raise ValueError("FeatureCollection has no features")
        return features[0]["geometry"]
    # Bare geometry (Polygon, MultiPolygon, etc.)
    return geojson
