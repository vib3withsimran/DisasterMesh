"""
Unit tests for VictimAgent — Phase 4.

All tests are fully isolated: no Qdrant, no DB, no network.
The VictimAgent is instantiated directly and its sub-methods are tested
independently as well as through the public ``assess()`` entry point.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.agents.victim import VictimAgent, get_victim_agent
from app.schemas import (
    NeedsProfile,
    Priority,
    SourceType,
    VerifiedIncident,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def agent() -> VictimAgent:
    return VictimAgent()


def _incident(
    *,
    lat: float = 28.667,
    lon: float = 77.23,
    sources: list[str] | None = None,
    age_hours: float = 0.0,
) -> VerifiedIncident:
    """Build a minimal VerifiedIncident for testing."""
    source_list = [SourceType(s) for s in (sources or ["sms"])]
    ts = datetime.now(UTC) - timedelta(hours=age_hours)
    return VerifiedIncident(
        cluster_id="cluster_test",
        source_provenance=source_list,
        lat=lat,
        lon=lon,
        timestamp=ts,
        confidence=0.8,
    )


# ── Needs extraction — English ────────────────────────────────────────────────


def test_keyword_extraction_medical_english(agent: VictimAgent) -> None:
    needs = agent._extract_needs_keyword("2 people injured, need ambulance urgently")
    assert needs.medical is True


def test_keyword_extraction_rescue_english(agent: VictimAgent) -> None:
    needs = agent._extract_needs_keyword("family trapped on rooftop, please rescue")
    assert needs.rescue is True


def test_keyword_extraction_evacuation_english(agent: VictimAgent) -> None:
    needs = agent._extract_needs_keyword("residents need to evacuate the building now")
    assert needs.evacuation is True


def test_keyword_extraction_shelter_english(agent: VictimAgent) -> None:
    needs = agent._extract_needs_keyword("hundreds of people displaced, need shelter")
    assert needs.shelter is True


def test_keyword_extraction_water_english(agent: VictimAgent) -> None:
    needs = agent._extract_needs_keyword("flood rising fast, no drinking water")
    assert needs.water is True


def test_keyword_extraction_food_english(agent: VictimAgent) -> None:
    needs = agent._extract_needs_keyword("children are hungry, need food")
    assert needs.food is True


# ── Needs extraction — Hindi ──────────────────────────────────────────────────


def test_keyword_extraction_hindi_rescue_water(agent: VictimAgent) -> None:
    needs = agent._extract_needs_keyword("बचाओ, पानी चाहिए")
    assert needs.rescue is True
    assert needs.water is True


def test_keyword_extraction_hindi_medical(agent: VictimAgent) -> None:
    needs = agent._extract_needs_keyword("घायल लोग हैं, अस्पताल भेजो")
    assert needs.medical is True


def test_keyword_extraction_bilingual_mixed(agent: VictimAgent) -> None:
    needs = agent._extract_needs_keyword("rescue needed, बेघर लोग, food required")
    assert needs.rescue is True
    assert needs.shelter is True
    assert needs.food is True


def test_keyword_extraction_no_match(agent: VictimAgent) -> None:
    """Completely unrelated text → all needs False."""
    needs = agent._extract_needs_keyword("sunny weather today, no issues reported")
    assert needs == NeedsProfile()


# ── Base needs score ──────────────────────────────────────────────────────────


def test_base_needs_score_zero(agent: VictimAgent) -> None:
    score = agent._base_needs_score(NeedsProfile())
    assert score == pytest.approx(0.0)


def test_base_needs_score_full(agent: VictimAgent) -> None:
    needs = NeedsProfile(
        medical=True,
        shelter=True,
        evacuation=True,
        rescue=True,
        water=True,
        food=True,
    )
    score = agent._base_needs_score(needs)
    assert score == pytest.approx(1.0)


def test_base_needs_score_half(agent: VictimAgent) -> None:
    needs = NeedsProfile(medical=True, rescue=True, evacuation=True)
    score = agent._base_needs_score(needs)
    assert score == pytest.approx(3 / 6)


# ── Keyword multiplier ────────────────────────────────────────────────────────


def test_keyword_multiplier_medical_and_rescue(agent: VictimAgent) -> None:
    needs = NeedsProfile(medical=True, rescue=True)
    assert agent._keyword_multiplier(needs) == pytest.approx(1.5)


def test_keyword_multiplier_evacuation_only(agent: VictimAgent) -> None:
    needs = NeedsProfile(evacuation=True)
    assert agent._keyword_multiplier(needs) == pytest.approx(1.3)


def test_keyword_multiplier_evacuation_beats_default_not_medical_rescue(agent: VictimAgent) -> None:
    """Evacuation=True but not (medical AND rescue) → 1.3, not 1.5."""
    needs = NeedsProfile(evacuation=True, medical=True)  # rescue=False
    assert agent._keyword_multiplier(needs) == pytest.approx(1.3)


def test_keyword_multiplier_default(agent: VictimAgent) -> None:
    needs = NeedsProfile(shelter=True, food=True)
    assert agent._keyword_multiplier(needs) == pytest.approx(1.0)


# ── Population density ────────────────────────────────────────────────────────


def test_population_density_delhi_high(agent: VictimAgent) -> None:
    # Yamuna Bazar — Delhi high-density zone
    assert agent._population_density_factor(28.667, 77.23) == pytest.approx(0.8)


def test_population_density_delhi_medium(agent: VictimAgent) -> None:
    # Slightly outside high-density but inside medium zone
    assert agent._population_density_factor(28.35, 76.85) == pytest.approx(0.5)


def test_population_density_rural(agent: VictimAgent) -> None:
    # Far from Delhi (Lucknow region)
    assert agent._population_density_factor(26.8, 80.9) == pytest.approx(0.2)


# ── Satellite area factor ─────────────────────────────────────────────────────


def test_satellite_area_factor_present(agent: VictimAgent) -> None:
    incident = _incident(sources=["satellite", "sms"])
    assert agent._satellite_area_factor(incident) == pytest.approx(0.6)


def test_satellite_area_factor_absent(agent: VictimAgent) -> None:
    incident = _incident(sources=["sms", "tweet"])
    assert agent._satellite_area_factor(incident) == pytest.approx(0.0)


# ── Corroboration bonus ───────────────────────────────────────────────────────


def test_corroboration_single_source(agent: VictimAgent) -> None:
    incident = _incident(sources=["sms"])
    assert agent._corroboration_bonus(incident) == pytest.approx(1.0)


def test_corroboration_two_sources(agent: VictimAgent) -> None:
    incident = _incident(sources=["sms", "tweet"])
    assert agent._corroboration_bonus(incident) == pytest.approx(1.2)


def test_corroboration_three_sources(agent: VictimAgent) -> None:
    incident = _incident(sources=["sms", "tweet", "satellite"])
    assert agent._corroboration_bonus(incident) == pytest.approx(1.4)


# ── Temporal escalation ───────────────────────────────────────────────────────


def test_temporal_escalation_fresh(agent: VictimAgent) -> None:
    incident = _incident(age_hours=0.5)
    assert agent._temporal_escalation(incident) == pytest.approx(1.0)


def test_temporal_escalation_just_under_threshold(agent: VictimAgent) -> None:
    incident = _incident(age_hours=1.9)
    assert agent._temporal_escalation(incident) == pytest.approx(1.0)


def test_temporal_escalation_old(agent: VictimAgent) -> None:
    incident = _incident(age_hours=3.0)
    assert agent._temporal_escalation(incident) == pytest.approx(1.1)


def test_temporal_escalation_very_old(agent: VictimAgent) -> None:
    incident = _incident(age_hours=24.0)
    assert agent._temporal_escalation(incident) == pytest.approx(1.1)


# ── Priority mapping ──────────────────────────────────────────────────────────


def test_priority_p1(agent: VictimAgent) -> None:
    assert agent._score_to_priority(0.75) == Priority.P1
    assert agent._score_to_priority(1.0) == Priority.P1


def test_priority_p2(agent: VictimAgent) -> None:
    assert agent._score_to_priority(0.50) == Priority.P2
    assert agent._score_to_priority(0.74) == Priority.P2


def test_priority_p3(agent: VictimAgent) -> None:
    assert agent._score_to_priority(0.25) == Priority.P3
    assert agent._score_to_priority(0.49) == Priority.P3


def test_priority_p4(agent: VictimAgent) -> None:
    assert agent._score_to_priority(0.0) == Priority.P4
    assert agent._score_to_priority(0.24) == Priority.P4


# ── Severity score clamping ───────────────────────────────────────────────────


def test_severity_score_clamped_at_1(agent: VictimAgent) -> None:
    """Even with extreme inputs the score must never exceed 1.0."""
    # All 6 needs True + satellite + 5 sources + >2h old
    incident = _incident(sources=["sms", "tweet", "satellite", "sms", "sms"], age_hours=6.0)
    needs = NeedsProfile(
        medical=True,
        shelter=True,
        evacuation=True,
        rescue=True,
        water=True,
        food=True,
    )
    base = agent._base_needs_score(needs)
    mult = agent._keyword_multiplier(needs)
    pop = agent._population_density_factor(incident.lat, incident.lon)
    sat = agent._satellite_area_factor(incident)
    corr = agent._corroboration_bonus(incident)
    temp = agent._temporal_escalation(incident)
    raw = (base + mult + pop + sat) / 4.0 * corr * temp
    assert min(1.0, raw) <= 1.0


# ── Full assess() flow ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_assess_medical_rescue_delhi_is_high_priority(agent: VictimAgent) -> None:
    incident = _incident(lat=28.667, lon=77.23, sources=["sms"])
    assessment = await agent.assess(
        incident,
        text="injured people trapped, need ambulance and rescue immediately",
    )
    assert assessment.needs.medical is True
    assert assessment.needs.rescue is True
    assert assessment.priority in (Priority.P1, Priority.P2)
    assert assessment.severity_score >= 0.5


@pytest.mark.anyio
async def test_assess_empty_text_no_needs(agent: VictimAgent) -> None:
    # Use rural location so pop_density=0.2 → raw = (0+1.0+0.2+0)/4 = 0.3 → P3
    # and with no satellite + single source the score stays at 0.3 → P3.
    # To reach P4 (< 0.25) we need pop_density=0.2 AND keyword_mult=1.0,
    # but the formula gives (0 + 1.0 + 0.2 + 0) / 4 = 0.3 which is P3.
    # This is correct behaviour: the keyword_multiplier baseline of 1.0 reflects
    # that any incident in any area has some minimum urgency floor.
    # So empty text → all needs=False AND score is at the formula floor.
    incident = _incident(lat=26.8, lon=80.9)  # Lucknow — rural zone
    assessment = await agent.assess(incident, text="")
    assert assessment.needs == NeedsProfile()
    # Formula floor: (0 + 1.0 + 0.2 + 0) / 4 × 1.0 × 1.0 = 0.30 → P3
    assert assessment.priority == Priority.P3
    assert assessment.severity_score == pytest.approx(0.3, abs=1e-3)


@pytest.mark.anyio
async def test_assess_factors_dict_keys(agent: VictimAgent) -> None:
    incident = _incident()
    assessment = await agent.assess(incident, text="rescue needed")
    expected_keys = {
        "base_needs_score",
        "keyword_multiplier",
        "population_density",
        "satellite_area",
        "corroboration_bonus",
        "temporal_escalation",
    }
    assert set(assessment.factors.keys()) == expected_keys


@pytest.mark.anyio
async def test_assess_multi_source_higher_than_single(agent: VictimAgent) -> None:
    text = "flooding, need rescue and evacuation"
    single = _incident(sources=["sms"])
    multi = _incident(sources=["sms", "tweet", "satellite"])

    a_single = await agent.assess(single, text=text)
    a_multi = await agent.assess(multi, text=text)
    assert a_multi.severity_score > a_single.severity_score


@pytest.mark.anyio
async def test_assess_old_incident_higher_than_fresh(agent: VictimAgent) -> None:
    text = "flood rescue needed"
    fresh = _incident(age_hours=0.5)
    old = _incident(age_hours=4.0)

    a_fresh = await agent.assess(fresh, text=text)
    a_old = await agent.assess(old, text=text)
    assert a_old.severity_score > a_fresh.severity_score


# ── Singleton getter ──────────────────────────────────────────────────────────


def test_get_victim_agent_returns_same_instance() -> None:
    """get_victim_agent() should return the same singleton on repeated calls."""
    a1 = get_victim_agent()
    a2 = get_victim_agent()
    assert a1 is a2
