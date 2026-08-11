"""
Seed script — populates demo_data/ with realistic mock records.

Usage:
    cd backend
    python scripts/seed_data.py

Generates:
  demo_data/citizen_reports/mock_reports.json   — 25 SMS-style JSON (Hindi/English)
  demo_data/social_posts/mock_tweets.json        — 20 tweet-like JSON
  demo_data/satellite/flood_polygons.geojson     — 5 Sentinel-2 flood GeoJSON polygons
  demo_data/iot_sensors/sensor_readings.json     — 10 IoT sensor readings
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

BASE = Path(__file__).parent.parent.parent / "demo_data"

# Fix seed for reproducible demo datasets
random.seed(42)

# ── Locations — real Delhi-NCR flood-prone coordinates ────────────────────────

LOCATIONS: list[dict[str, Any]] = [
    {"name": "Yamuna Bazar", "lat": 28.6667, "lon": 77.2333},
    {"name": "Lal Qila Chowk", "lat": 28.6562, "lon": 77.2410},
    {"name": "Kashmere Gate", "lat": 28.6677, "lon": 77.2284},
    {"name": "ISBT Delhi", "lat": 28.6703, "lon": 77.2254},
    {"name": "Shahdara", "lat": 28.6741, "lon": 77.2896},
    {"name": "Mayur Vihar Phase 1", "lat": 28.6080, "lon": 77.2957},
    {"name": "Okhla", "lat": 28.5355, "lon": 77.2741},
    {"name": "Lajpat Nagar", "lat": 28.5674, "lon": 77.2431},
    {"name": "Noida Sector 18", "lat": 28.5679, "lon": 77.3213},
    {"name": "Connaught Place", "lat": 28.6315, "lon": 77.2167},
]

# ── Citizen report templates (bilingual) ─────────────────────────────────────

CITIZEN_TEMPLATES_EN = [
    "Water rising fast near {name}. Road blocked. Need boats urgently.",
    "Flooding at {name}. Children and elderly trapped on rooftop. Send rescue.",
    "Heavy flooding at {name}. We need medical help immediately. Someone is injured.",
    "My house near {name} is submerged. Water is up to my waist. Please evacuate us.",
    "Cars swept away at {name}. Several people stranded. Need immediate help.",
    "Water level rising quickly at {name}. Ground floor completely underwater.",
    "Flood near {name}. Elderly woman needs medical attention. No ambulance available.",
    "Flash flood at {name} junction. People stuck on buses. Send rescue teams.",
    "Drainage overflow at {name}. Sewage water entering homes. Health emergency.",
    "{name} bridge submerged. Emergency vehicles cannot pass. People cut off.",
    "Shop basement flooded at {name}. Two people trapped inside. Need rescue.",
    "Homeless shelter near {name} submerged. 40 people need evacuation.",
]

CITIZEN_TEMPLATES_HI = [
    "{name} के पास पानी बहुत तेज़ी से बढ़ रहा है। नाव की ज़रूरत है।",
    "{name} में बाढ़ आ गई है। छत पर फंसे हैं। बचाओ।",
    "{name} में बहुत पानी है। बच्चे और बुजुर्ग फंसे हैं। मदद चाहिए।",
    "मेरा घर {name} के पास डूब गया है। निकालो हमें।",
    "{name} में पानी भर गया है। मेडिकल सहायता चाहिए।",
    "{name} के पास सड़क बंद है। राशन नहीं है। मदद करो।",
    "{name} में पानी बहुत है। दवाइयाँ खत्म हो गई हैं। अस्पताल नहीं जा सकते।",
    "{name} में बाढ़। बिजली गई है। अंधेरे में फंसे हैं।",
]

# ── Social post templates ─────────────────────────────────────────────────────

SOCIAL_TEMPLATES = [
    "BREAKING: Major flooding at {name}, Delhi. Roads impassable. #DelhiFloods #Yamuna",
    "Situation at {name} critical. Water levels rising. Local authorities not responding. #DelhiFlood",
    "Massive waterlogging near {name}. Commuters stranded for hours. #DelhiRains #Flood",
    "Flood alert: {name} area has 4+ feet of water. Residents advised to move to higher ground.",
    "URGENT: {name} residents need rescue. 20+ families trapped. RT to spread awareness. #IndiaFlood",
    "Water entered homes near {name}. People on rooftops. @CMDelhi @NDRF please help. #DelhiFloods",
    "Just saw the situation at {name}. Absolutely devastating. Roads look like rivers. #DelhiRains",
    "Volunteer teams heading to {name} for rescue ops. Need boats, food, medical supplies. #DisasterRelief",
    "Water level at Yamuna dangerously high. {name} area at risk. Stay safe. #YamunaFlood",
    "Update: Rescue teams arrived at {name}. 50 people evacuated so far. @NDRF doing amazing work.",
    "LIVE: Aerial view of flooding near {name}. Situation worse than yesterday. #DelhiFlood",
    "Schools near {name} to remain closed tomorrow due to severe flooding. #DelhiRains",
    "{name} substation flooded. Power outage for 10,000+ homes. @BSES_Delhi please respond.",
    "Yamuna crossed danger mark. {name} completely inundated. Govt relief camp set up. #DelhiFlood",
    "Volunteers needed at {name} relief camp. Bring dry food, drinking water, blankets. #DelhiHelps",
]

# ── GeoJSON polygon templates — Yamuna floodplain ─────────────────────────────

SATELLITE_POLYGONS = [
    {
        "name": "Yamuna Bazar Flood Zone",
        "polygon": [
            [77.225, 28.660],
            [77.245, 28.660],
            [77.245, 28.675],
            [77.225, 28.675],
            [77.225, 28.660],
        ],
        "flood_depth_m": 1.8,
        "confidence": 0.92,
        "satellite": "Sentinel-2A",
        "band": "NDWI",
    },
    {
        "name": "Shahdara Flood Zone",
        "polygon": [
            [77.275, 28.668],
            [77.295, 28.668],
            [77.295, 28.682],
            [77.275, 28.682],
            [77.275, 28.668],
        ],
        "flood_depth_m": 2.4,
        "confidence": 0.88,
        "satellite": "Sentinel-2B",
        "band": "NDWI",
    },
    {
        "name": "Mayur Vihar Flood Zone",
        "polygon": [
            [77.288, 28.600],
            [77.308, 28.600],
            [77.308, 28.618],
            [77.288, 28.618],
            [77.288, 28.600],
        ],
        "flood_depth_m": 1.1,
        "confidence": 0.79,
        "satellite": "Sentinel-2A",
        "band": "NDWI",
    },
    {
        "name": "Okhla Flood Zone",
        "polygon": [
            [77.265, 28.528],
            [77.285, 28.528],
            [77.285, 28.544],
            [77.265, 28.544],
            [77.265, 28.528],
        ],
        "flood_depth_m": 0.9,
        "confidence": 0.83,
        "satellite": "Sentinel-2B",
        "band": "NDWI",
    },
    {
        "name": "Kashmere Gate Flood Zone",
        "polygon": [
            [77.220, 28.660],
            [77.235, 28.660],
            [77.235, 28.672],
            [77.220, 28.672],
            [77.220, 28.660],
        ],
        "flood_depth_m": 1.5,
        "confidence": 0.91,
        "satellite": "Sentinel-2A",
        "band": "NDWI",
    },
]

# ── IoT sensor configs ────────────────────────────────────────────────────────

IOT_SENSORS: list[dict[str, Any]] = [
    {
        "id": "yamuna_gauge_001",
        "type": "water_level",
        "lat": 28.6667,
        "lon": 77.2333,
        "unit": "metres",
        "base_val": 4.2,
    },
    {
        "id": "yamuna_gauge_002",
        "type": "water_level",
        "lat": 28.6741,
        "lon": 77.2896,
        "unit": "metres",
        "base_val": 3.8,
    },
    {
        "id": "yamuna_gauge_003",
        "type": "water_level",
        "lat": 28.6080,
        "lon": 77.2957,
        "unit": "metres",
        "base_val": 2.1,
    },
    {
        "id": "aq_sensor_cp_001",
        "type": "air_quality",
        "lat": 28.6315,
        "lon": 77.2167,
        "unit": "AQI",
        "base_val": 185,
    },
    {
        "id": "aq_sensor_okhla_001",
        "type": "air_quality",
        "lat": 28.5355,
        "lon": 77.2741,
        "unit": "AQI",
        "base_val": 312,
    },
    {
        "id": "yamuna_gauge_004",
        "type": "water_level",
        "lat": 28.5674,
        "lon": 77.2431,
        "unit": "metres",
        "base_val": 3.3,
    },
    {
        "id": "aq_sensor_shahdara_001",
        "type": "air_quality",
        "lat": 28.6741,
        "lon": 77.2896,
        "unit": "AQI",
        "base_val": 220,
    },
    {
        "id": "yamuna_gauge_005",
        "type": "water_level",
        "lat": 28.6562,
        "lon": 77.2410,
        "unit": "metres",
        "base_val": 5.1,
    },
    {
        "id": "aq_sensor_noida_001",
        "type": "air_quality",
        "lat": 28.5679,
        "lon": 77.3213,
        "unit": "AQI",
        "base_val": 145,
    },
    {
        "id": "yamuna_gauge_006",
        "type": "water_level",
        "lat": 28.6703,
        "lon": 77.2254,
        "unit": "metres",
        "base_val": 4.7,
    },
]


# ── Utility ───────────────────────────────────────────────────────────────────


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    count = (
        len(data)
        if isinstance(data, list)
        else (len(data.get("features", [])) if isinstance(data, dict) else 1)
    )
    print(f"  ✓ wrote {count} record(s) → {path.relative_to(BASE.parent)}")


def _jitter(val: float, amount: float = 0.001) -> float:
    """Add small random noise to a coordinate so nearby reports aren't identical."""
    return round(val + random.uniform(-amount, amount), 6)


def _ts(minutes_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


# ── Generators ────────────────────────────────────────────────────────────────


def seed_citizen_reports() -> None:
    """Generate 25 realistic Hindi/English SMS-style citizen reports."""
    records: list[dict[str, Any]] = []
    for i in range(25):
        loc = LOCATIONS[i % len(LOCATIONS)]
        # Alternate between English and Hindi reports
        if i % 3 == 2:
            template = random.choice(CITIZEN_TEMPLATES_HI)
        else:
            template = random.choice(CITIZEN_TEMPLATES_EN)

        text = template.format(name=loc["name"])
        records.append(
            {
                "id": f"sms_{i + 1:03d}",
                "source": "sms" if i % 4 != 3 else "whatsapp",
                "text": text,
                "lat": _jitter(float(loc["lat"])),
                "lon": _jitter(float(loc["lon"])),
                "timestamp": _ts(i * 4.5),  # spread over ~2 hours
                "media_urls": [],
            }
        )

    _write(BASE / "citizen_reports" / "mock_reports.json", records)


def seed_social_posts() -> None:
    """Generate 20 realistic tweet-style social media posts."""
    records: list[dict[str, Any]] = []
    for i in range(20):
        loc = LOCATIONS[i % len(LOCATIONS)]
        template = SOCIAL_TEMPLATES[i % len(SOCIAL_TEMPLATES)]
        text = template.format(name=loc["name"])
        records.append(
            {
                "id": f"tweet_{i + 1:03d}",
                "source": "tweet",
                "text": text,
                "url": f"https://twitter.com/DisasterMesh/status/{1900000000000 + i}",
                "lat": _jitter(float(loc["lat"]), 0.005) if i % 3 == 0 else None,
                "lon": _jitter(float(loc["lon"]), 0.005) if i % 3 == 0 else None,
                "timestamp": _ts(i * 6),  # spread over ~2 hours
            }
        )

    _write(BASE / "social_posts" / "mock_tweets.json", records)


def seed_satellite_polygons() -> None:
    """Generate 5 Sentinel-2 flood GeoJSON polygons."""
    features = []
    for i, sat in enumerate(SATELLITE_POLYGONS):
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [sat["polygon"]],
            },
            "properties": {
                "id": f"sentinel_{i + 1:03d}",
                "name": sat["name"],
                "flood_depth_m": sat["flood_depth_m"],
                "confidence": sat["confidence"],
                "satellite": sat["satellite"],
                "band": sat["band"],
                "timestamp": _ts(i * 60),  # polygons spread over 5 hours
            },
        }
        features.append(feature)

    geojson = {"type": "FeatureCollection", "features": features}
    _write(BASE / "satellite" / "flood_polygons.geojson", geojson)


def seed_sensor_data() -> None:
    """Generate 10 IoT sensor readings (water level + air quality)."""
    records: list[dict[str, Any]] = []
    for i, sensor in enumerate(IOT_SENSORS):
        # Add ±10% noise to base value
        noise = random.uniform(-0.1, 0.1)
        base_val = float(sensor["base_val"])
        value = round(base_val * (1 + noise), 2)
        records.append(
            {
                "id": f"sensor_{i + 1:03d}",
                "sensor_id": sensor["id"],
                "sensor_type": sensor["type"],
                "source": "iot_sensor",
                "value": value,
                "unit": sensor["unit"],
                "lat": sensor["lat"],
                "lon": sensor["lon"],
                "timestamp": _ts(i * 10),
            }
        )

    _write(BASE / "iot_sensors" / "sensor_readings.json", records)


def seed_responders() -> None:
    """Generate 8 mock responder teams with diverse capabilities."""
    teams = [
        {
            "id": "resp_001",
            "name": "NDRF Battalion 8 (Medical/Rescue)",
            "team_type": "rescue",
            "capabilities": ["medical", "rescue", "water"],
            "team_size": 12,
            "capacity": 3,
            "lat": 28.6670,
            "lon": 77.2330,
        },
        {
            "id": "resp_002",
            "name": "Delhi Fire Services Unit 4",
            "team_type": "rescue",
            "capabilities": ["rescue", "water"],
            "team_size": 8,
            "capacity": 2,
            "lat": 28.6560,
            "lon": 77.2400,
        },
        {
            "id": "resp_003",
            "name": "CATMA Medical Emergency Squad",
            "team_type": "medical",
            "capabilities": ["medical"],
            "team_size": 6,
            "capacity": 2,
            "lat": 28.6310,
            "lon": 77.2160,
        },
        {
            "id": "resp_004",
            "name": "Civil Defence Boat Task Force",
            "team_type": "water",
            "capabilities": ["rescue", "water", "evacuation"],
            "team_size": 10,
            "capacity": 4,
            "lat": 28.6700,
            "lon": 77.2250,
        },
        {
            "id": "resp_005",
            "name": "Red Cross Emergency Logistics",
            "team_type": "logistics",
            "capabilities": ["logistics", "evacuation"],
            "team_size": 15,
            "capacity": 5,
            "lat": 28.6080,
            "lon": 77.2950,
        },
        {
            "id": "resp_006",
            "name": "Army Medical Corps Unit",
            "team_type": "medical",
            "capabilities": ["medical", "rescue"],
            "team_size": 10,
            "capacity": 3,
            "lat": 28.5670,
            "lon": 77.2430,
        },
        {
            "id": "resp_007",
            "name": "SDRF Water Rescue Squad",
            "team_type": "water",
            "capabilities": ["rescue", "water"],
            "team_size": 8,
            "capacity": 2,
            "lat": 28.6740,
            "lon": 77.2890,
        },
        {
            "id": "resp_008",
            "name": "Disaster Evacuation Transport Fleet",
            "team_type": "evacuation",
            "capabilities": ["evacuation", "logistics"],
            "team_size": 20,
            "capacity": 6,
            "lat": 28.5350,
            "lon": 77.2740,
        },
    ]
    _write(BASE / "responder_registry.json", teams)


if __name__ == "__main__":
    print("🌱 Seeding demo_data/ with realistic mock records...")
    seed_citizen_reports()
    seed_social_posts()
    seed_satellite_polygons()
    seed_sensor_data()
    seed_responders()
    print("\n✅ Done. All demo_data/ files populated.")
    print("   Tip: POST these through /ingest/* to test the pipeline end-to-end.")
