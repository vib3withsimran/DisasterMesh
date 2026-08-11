"""
Integration tests for the VictimAgent assess endpoint — Phase 4.

Tests the full ``POST /incidents/{cluster_id}/assess`` HTTP flow via
the FastAPI test client.  The unit conftest.py fixture (autouse) wires
in an in-memory Qdrant and SQLite DB, so no external services are needed.

Run:
    cd backend
    pytest app/tests/integration/test_victim_integration.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ── Helpers ───────────────────────────────────────────────────────────────────

CLUSTER_ID = "cluster_victim_test_01"


def _assess_body(
    *,
    cluster_id: str = CLUSTER_ID,
    text: str = "",
    sources: list[str] | None = None,
    lat: float = 28.667,
    lon: float = 77.23,
    age_hours: float = 0.0,
    confidence: float = 0.8,
) -> dict:
    ts = (datetime.now(UTC) - timedelta(hours=age_hours)).isoformat()
    return {
        "cluster_id": cluster_id,
        "source_provenance": sources or ["sms"],
        "lat": lat,
        "lon": lon,
        "timestamp": ts,
        "confidence": confidence,
        "severity": "P4",
        "needs": {
            "medical": False,
            "shelter": False,
            "evacuation": False,
            "rescue": False,
            "water": False,
            "food": False,
        },
        "media_urls": [],
        "status": "VERIFIED",
        "text": text,
    }


# ── Basic endpoint contract ───────────────────────────────────────────────────


def test_assess_endpoint_returns_200_and_schema() -> None:
    """Valid request → 200 with well-formed SeverityAssessment JSON."""
    body = _assess_body(text="flooding near river, rescue boats needed")
    response = client.post(f"/incidents/{CLUSTER_ID}/assess", json=body)

    assert response.status_code == 200, response.text
    data = response.json()

    # Required top-level fields
    assert "needs" in data
    assert "severity_score" in data
    assert "priority" in data
    assert "factors" in data

    # Types
    assert isinstance(data["severity_score"], float)
    assert data["priority"] in ("P1", "P2", "P3", "P4")
    assert 0.0 <= data["severity_score"] <= 1.0


def test_assess_endpoint_mismatched_cluster_id_returns_422() -> None:
    """cluster_id in URL ≠ cluster_id in body → 422."""
    body = _assess_body(cluster_id="cluster_OTHER")
    response = client.post(f"/incidents/{CLUSTER_ID}/assess", json=body)
    assert response.status_code == 422


def test_assess_endpoint_missing_required_fields_returns_422() -> None:
    """Missing required fields (lat, lon, timestamp) → 422."""
    response = client.post(
        f"/incidents/{CLUSTER_ID}/assess",
        json={"cluster_id": CLUSTER_ID},
    )
    assert response.status_code == 422


# ── Priority expectations ─────────────────────────────────────────────────────


def test_assess_flood_rescue_medical_in_delhi_returns_high_priority() -> None:
    """Medical + rescue text in Delhi high-density zone → P1 or P2."""
    body = _assess_body(
        text="injured people trapped, need ambulance and rescue immediately",
        sources=["sms", "tweet"],
        lat=28.667,
        lon=77.23,
    )
    response = client.post(f"/incidents/{CLUSTER_ID}/assess", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["priority"] in ("P1", "P2")
    assert data["needs"]["medical"] is True
    assert data["needs"]["rescue"] is True


def test_assess_empty_text_formula_floor() -> None:
    """
    Empty text → all needs=False, so base_needs_score=0.
    Formula: (0 + 1.0 + pop_density + 0) / 4 × 1.0 × 1.0
    With Delhi lat (0.8): (0+1.0+0.8+0)/4 = 0.45 → P2/P3 boundary area → P3.
    The keyword_multiplier default of 1.0 acts as a floor — even zero-keyword
    incidents have minimum urgency.  P4 requires score < 0.25 which is only
    achievable below formula floor in rural zones with no satellite.
    """
    body = _assess_body(text="", sources=["sms"], lat=28.667, lon=77.23)
    response = client.post(f"/incidents/{CLUSTER_ID}/assess", json=body)
    assert response.status_code == 200
    data = response.json()
    # (0 + 1.0 + 0.8 + 0) / 4 = 0.45 → P3
    assert data["priority"] == "P3"
    assert all(v is False for v in data["needs"].values())


# ── Factor breakdown ──────────────────────────────────────────────────────────


def test_assess_response_contains_factor_breakdown() -> None:
    """Response body must include all 6 scoring-factor keys."""
    body = _assess_body(text="rescue needed")
    response = client.post(f"/incidents/{CLUSTER_ID}/assess", json=body)
    assert response.status_code == 200
    factors = response.json()["factors"]

    expected = {
        "base_needs_score",
        "keyword_multiplier",
        "population_density",
        "satellite_area",
        "corroboration_bonus",
        "temporal_escalation",
    }
    assert expected.issubset(factors.keys())


def test_assess_multi_source_has_higher_score_than_single() -> None:
    """3-source cluster should score higher than a 1-source cluster (same text)."""
    text = "trapped people need rescue and evacuation"
    cid_a = "cluster_single_src"
    cid_b = "cluster_multi_src"

    r_single = client.post(
        f"/incidents/{cid_a}/assess",
        json=_assess_body(cluster_id=cid_a, text=text, sources=["sms"]),
    )
    r_multi = client.post(
        f"/incidents/{cid_b}/assess",
        json=_assess_body(cluster_id=cid_b, text=text, sources=["sms", "tweet", "satellite"]),
    )

    assert r_single.status_code == 200
    assert r_multi.status_code == 200

    score_single = r_single.json()["severity_score"]
    score_multi = r_multi.json()["severity_score"]
    assert score_multi > score_single


def test_assess_satellite_source_increases_score() -> None:
    """Including satellite in provenance triggers the satellite_area factor."""
    text = "flood water rising"
    cid_a = "cluster_no_sat"
    cid_b = "cluster_with_sat"

    r_no_sat = client.post(
        f"/incidents/{cid_a}/assess",
        json=_assess_body(cluster_id=cid_a, text=text, sources=["sms"]),
    )
    r_sat = client.post(
        f"/incidents/{cid_b}/assess",
        json=_assess_body(cluster_id=cid_b, text=text, sources=["sms", "satellite"]),
    )

    assert r_no_sat.status_code == 200
    assert r_sat.status_code == 200

    assert r_sat.json()["factors"]["satellite_area"] == pytest.approx(0.6)
    assert r_no_sat.json()["factors"]["satellite_area"] == pytest.approx(0.0)
    assert r_sat.json()["severity_score"] > r_no_sat.json()["severity_score"]
