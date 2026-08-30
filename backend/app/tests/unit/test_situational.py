"""
Unit tests for SituationalAgent — Phase 1.

Run:
    cd backend
    pytest app/tests/unit/test_situational.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.situational import (
    SituationalAgent,
    _detect_language,
    _extract_geometry,
    _lookup_landmark,
    _polygon_centroid,
)
from app.schemas import (
    CitizenReportInput,
    ProtoIncident,
    SatellitePolygonInput,
    SensorStreamInput,
    SocialPostInput,
    SourceType,
)

# ── Language detection ────────────────────────────────────────────────────────


def test_detect_language_english() -> None:
    assert _detect_language("Water rising near Yamuna Bazar") == "en"


def test_detect_language_hindi_devanagari() -> None:
    assert _detect_language("यमुना बाज़ार के पास पानी बढ़ रहा है") == "hi"


def test_detect_language_mixed_defaults_hindi() -> None:
    # Mixed text with at least one Devanagari char → hi
    assert _detect_language("Flood near यमुना bazar") == "hi"


def test_detect_language_empty_string() -> None:
    assert _detect_language("") == "en"


# ── Landmark table ────────────────────────────────────────────────────────────


def test_landmark_exact_match() -> None:
    result = _lookup_landmark("yamuna bazar")
    assert result == (28.6667, 77.2333)


def test_landmark_case_insensitive() -> None:
    result = _lookup_landmark("YAMUNA BAZAR")
    assert result == (28.6667, 77.2333)


def test_landmark_substring_match() -> None:
    result = _lookup_landmark("Flooding at Yamuna Bazar, North Delhi")
    assert result == (28.6667, 77.2333)


def test_landmark_hindi() -> None:
    result = _lookup_landmark("यमुना बाज़ार")
    assert result is not None
    lat, lon = result
    assert abs(lat - 28.6667) < 0.01


def test_landmark_unknown_address() -> None:
    result = _lookup_landmark("Some Unknown Place XYZ 999")
    assert result is None


# ── Polygon centroid ──────────────────────────────────────────────────────────


def test_polygon_centroid_square() -> None:
    """Centroid of a closed square ring (5 points, last == first)."""
    # Coordinates are [lon, lat]
    # Ring: (77.2,28.6) (77.4,28.6) (77.4,28.8) (77.2,28.8) (77.2,28.6)
    # Shoelace centroid = true geometric center = (28.70, 77.30)
    coords = [[[77.2, 28.6], [77.4, 28.6], [77.4, 28.8], [77.2, 28.8], [77.2, 28.6]]]
    lat, lon = _polygon_centroid(coords)
    assert abs(lat - 28.70) < 1e-6
    assert abs(lon - 77.30) < 1e-6


def test_polygon_centroid_triangle() -> None:
    coords = [[[77.0, 28.0], [78.0, 28.0], [77.5, 29.0], [77.0, 28.0]]]
    lat, lon = _polygon_centroid(coords)
    # Shoelace centroid for triangle (77.0,28.0) (78.0,28.0) (77.5,29.0)
    # True centroid ≈ (28.33, 77.50)
    assert abs(lat - 28.33) < 0.01
    assert abs(lon - 77.50) < 0.01


# ── extract_geometry ──────────────────────────────────────────────────────────


def test_extract_geometry_feature() -> None:
    geojson = {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": []},
        "properties": {},
    }
    geom = _extract_geometry(geojson)
    assert geom["type"] == "Polygon"


def test_extract_geometry_bare() -> None:
    geojson = {"type": "Polygon", "coordinates": []}
    geom = _extract_geometry(geojson)
    assert geom["type"] == "Polygon"


def test_extract_geometry_feature_collection() -> None:
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": []},
                "properties": {},
            },
        ],
    }
    geom = _extract_geometry(geojson)
    assert geom["type"] == "Polygon"


# ── SituationalAgent — citizen report ────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_citizen_report_with_coords() -> None:
    agent = SituationalAgent()
    report = CitizenReportInput(
        text="Water rising near Yamuna Bazar",
        lat=28.6667,
        lon=77.2333,
    )
    proto = await agent.process_citizen_report(report)
    assert isinstance(proto, ProtoIncident)
    assert proto.lat == 28.6667
    assert proto.lon == 77.2333
    assert proto.source == SourceType.SMS
    assert proto.metadata["language"] == "en"
    assert proto.raw_payload != {}


@pytest.mark.asyncio
async def test_process_citizen_report_address_only() -> None:
    """Address-only report resolves lat/lon via landmark table (no live geocoder)."""
    agent = SituationalAgent()
    # The landmark table has "yamuna bazar" as a key — use it directly
    # to ensure offline / CI-safe operation without hitting Nominatim.
    report = CitizenReportInput(
        text="Flooding at Yamuna Bazar",
        address="Yamuna Bazar",
    )
    proto = await agent.process_citizen_report(report)
    assert proto.lat is not None
    assert proto.lon is not None
    assert abs(proto.lat - 28.6667) < 0.01
    assert abs(proto.lon - 77.2333) < 0.01


@pytest.mark.asyncio
async def test_process_citizen_report_unknown_address_geocoder_fails() -> None:
    """When geocoder returns nothing, lat/lon remain None."""
    agent = SituationalAgent()
    with patch.object(agent, "_geocode", new=AsyncMock(return_value=None)):
        report = CitizenReportInput(
            text="Flooding somewhere",
            address="Totally Unknown Place XYZ",
        )
        proto = await agent.process_citizen_report(report)
    assert proto.lat is None
    assert proto.lon is None


@pytest.mark.asyncio
async def test_process_citizen_report_hindi_language() -> None:
    agent = SituationalAgent()
    report = CitizenReportInput(
        text="यमुना बाज़ार के पास पानी बढ़ रहा है",
        lat=28.6667,
        lon=77.2333,
    )
    proto = await agent.process_citizen_report(report)
    assert proto.metadata["language"] == "hi"


# ── SituationalAgent — social post ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_social_post() -> None:
    agent = SituationalAgent()
    post = SocialPostInput(
        source=SourceType.TWEET,
        text="Massive flooding in Yamuna Bazar #Delhi #Flood",
        lat=28.6667,
        lon=77.2333,
    )
    proto = await agent.process_social_post(post)
    assert proto.source == SourceType.TWEET
    assert proto.lat == 28.6667
    assert proto.metadata["language"] == "en"


@pytest.mark.asyncio
async def test_process_social_post_no_coords() -> None:
    agent = SituationalAgent()
    post = SocialPostInput(
        text="Flooding somewhere in Delhi #Flood",
    )
    proto = await agent.process_social_post(post)
    assert proto.lat is None
    assert proto.lon is None


# ── SituationalAgent — satellite polygon ──────────────────────────────────────


@pytest.mark.asyncio
async def test_process_satellite_polygon_centroid() -> None:
    agent = SituationalAgent()
    geojson = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[77.2, 28.6], [77.4, 28.6], [77.4, 28.8], [77.2, 28.8], [77.2, 28.6]]],
        },
        "properties": {"flood_depth_m": 2.3, "confidence": 0.91},
    }
    polygon = SatellitePolygonInput(geojson=geojson)
    proto = await agent.process_satellite_polygon(polygon)
    assert proto.source == SourceType.SATELLITE
    # 5-point closed ring: shoelace centroid = true center (28.70, 77.30)
    assert abs(proto.lat - 28.70) < 1e-4
    assert abs(proto.lon - 77.30) < 1e-4
    assert "2.3" in proto.text  # flood depth in text


@pytest.mark.asyncio
async def test_process_satellite_polygon_wrong_geometry_type() -> None:
    agent = SituationalAgent()
    geojson = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [77.2, 28.6]},
        "properties": {},
    }
    polygon = SatellitePolygonInput(geojson=geojson)
    with pytest.raises(ValueError, match="Unsupported geometry type"):
        await agent.process_satellite_polygon(polygon)


# ── SituationalAgent — sensor ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_sensor_normal_reading() -> None:
    agent = SituationalAgent()
    sensor = SensorStreamInput(
        sensor_id="yamuna_gauge_001",
        sensor_type="water_level",
        value=1.5,
        unit="metres",
        lat=28.6667,
        lon=77.2333,
    )
    proto = await agent.process_sensor(sensor)
    assert proto.source == SourceType.IOT_SENSOR
    assert proto.lat == 28.6667
    assert proto.metadata["is_alert"] is False
    assert "[INFO]" in proto.text


@pytest.mark.asyncio
async def test_process_sensor_alert_threshold_exceeded() -> None:
    agent = SituationalAgent()
    sensor = SensorStreamInput(
        sensor_id="yamuna_gauge_001",
        sensor_type="water_level",
        value=4.7,  # above 3.0 m threshold
        unit="metres",
        lat=28.6667,
        lon=77.2333,
    )
    proto = await agent.process_sensor(sensor)
    assert proto.metadata["is_alert"] is True
    assert "[ALERT]" in proto.text
    assert "Threshold" in proto.text


@pytest.mark.asyncio
async def test_process_sensor_unknown_type_no_alert() -> None:
    agent = SituationalAgent()
    sensor = SensorStreamInput(
        sensor_id="temp_sensor_001",
        sensor_type="temperature",
        value=999.0,  # no threshold defined for temperature
        unit="celsius",
        lat=28.6315,
        lon=77.2167,
    )
    proto = await agent.process_sensor(sensor)
    # No threshold → is_alert should be False
    assert proto.metadata["is_alert"] is False


# ── ProtoIncident structure ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_proto_incident_has_id_and_raw_payload() -> None:
    agent = SituationalAgent()
    report = CitizenReportInput(text="Test flood", lat=28.6, lon=77.2)
    proto = await agent.process_citizen_report(report)
    assert proto.id  # non-empty UUID string
    assert isinstance(proto.raw_payload, dict)
    assert proto.timestamp.tzinfo is not None  # timezone-aware
