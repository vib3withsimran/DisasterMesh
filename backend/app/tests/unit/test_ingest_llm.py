"""
Unit/integration tests for LLM Smart Intake in ingest router — Phase 4.5.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import NeedsProfile, ParsedIntake

client = TestClient(app)


def test_ingest_report_without_llm_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """When GROQ_API_KEY is not set, ingest_citizen_report operates in legacy keyword mode."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    response = client.post(
        "/ingest/report",
        json={
            "source": "sms",
            "text": "Water rising fast near Yamuna Bazar",
            "lat": 28.6667,
            "lon": 77.2333,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "received"
    assert data["lat"] == 28.6667
    assert data["lon"] == 77.2333


def test_ingest_report_with_llm_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """When GROQ_API_KEY is set, report is parsed by LLM and metadata enriched."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_mock_key")

    mock_parsed = ParsedIntake(
        address="Yamuna Bazar, Delhi",
        lat=28.6667,
        lon=77.2333,
        language="hinglish",
        incident_type="flood",
        needs=NeedsProfile(rescue=True, water=True),
        urgency_level=4,
        cleaned_text="Flooding at Yamuna Bazar, rescue needed",
    )

    with patch(
        "app.agents.intake_parser.IntakeParserAgent.parse", new_callable=AsyncMock
    ) as mock_parse:
        mock_parse.return_value = mock_parsed

        response = client.post(
            "/ingest/report",
            json={
                "source": "sms",
                "text": "bhai yamuna bazar mein pani bhar gaya phanse hain",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "received"
        # Resolved lat/lon from LLM parsed address/coords
        assert data["lat"] == 28.6667
        assert data["lon"] == 77.2333


def test_ingest_report_gps_overrides_llm_coords(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit device GPS coordinates (report.lat/lon) override coordinates from LLM."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_mock_key")

    mock_parsed = ParsedIntake(
        address="Yamuna Bazar, Delhi",
        lat=29.0000,  # wrong/approx coords from text
        lon=78.0000,
        language="en",
        incident_type="flood",
        cleaned_text="Flood at location",
    )

    with patch(
        "app.agents.intake_parser.IntakeParserAgent.parse", new_callable=AsyncMock
    ) as mock_parse:
        mock_parse.return_value = mock_parsed

        # User's device GPS gives exact location (28.5, 77.1)
        response = client.post(
            "/ingest/report",
            json={
                "source": "web_form",
                "text": "Emergency flood",
                "lat": 28.5,
                "lon": 77.1,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["lat"] == 28.5
        assert data["lon"] == 77.1
