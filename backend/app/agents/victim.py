"""
Victim Agent — Agent 3.

Responsibilities:
  - Extract needs (medical, shelter, evacuation, rescue, water, food) from incident text
  - Compute multi-factor severity score (0.0 – 1.0)
  - Assign priority label (P1–P4)
  - Optionally use LLM for bilingual (Hindi/English) needs extraction

Implemented in Phase 4.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.schemas import NeedsProfile, Priority, SeverityAssessment, SourceType, VerifiedIncident

logger = logging.getLogger(__name__)

# ── Bilingual keyword → need-type mapping ─────────────────────────────────────

KEYWORD_MAP: dict[str, list[str]] = {
    "medical": [
        "injured",
        "bleeding",
        "medical",
        "ambulance",
        "hospital",
        "doctor",
        "wound",
        "घायल",
        "खून",
        "अस्पताल",
        "डॉक्टर",
    ],
    "shelter": [
        "homeless",
        "shelter",
        "tent",
        "displaced",
        "refuge",
        "safe place",
        "बेघर",
        "शरण",
        "तंबू",
    ],
    "evacuation": [
        "evacuate",
        "evacuation",
        "flee",
        "escape",
        "move out",
        "leave",
        "निकासी",
        "भागो",
        "बाहर",
    ],
    "rescue": [
        "rescue",
        "trapped",
        "stuck",
        "help",
        "save",
        "recovery",
        "बचाओ",
        "फंसे",
        "मदद",
    ],
    "water": [
        "water",
        "drinking",
        "flood",
        "पानी",
        "बाढ़",
    ],
    "food": [
        "food",
        "hungry",
        "starving",
        "खाना",
        "भूख",
    ],
}

# ── Population-density bounding boxes (demo — Delhi NCR) ─────────────────────

# High-density urban core: Delhi Metro area
_DELHI_HIGH = {
    "lat_min": 28.5,
    "lat_max": 28.8,
    "lon_min": 77.0,
    "lon_max": 77.4,
}

# Medium-density: broader NCR / peri-urban fringe
_DELHI_MED = {
    "lat_min": 28.3,
    "lat_max": 29.0,
    "lon_min": 76.8,
    "lon_max": 77.6,
}

# ── Module-level singleton ────────────────────────────────────────────────────

_victim_agent: VictimAgent | None = None


def get_victim_agent() -> VictimAgent:
    """Return the shared VictimAgent singleton."""
    global _victim_agent
    if _victim_agent is None:
        _victim_agent = VictimAgent()
    return _victim_agent


# ── Helpers ───────────────────────────────────────────────────────────────────


def _in_bbox(lat: float, lon: float, bbox: dict) -> bool:
    """Return True if (lat, lon) falls inside *bbox*."""
    return bbox["lat_min"] <= lat <= bbox["lat_max"] and bbox["lon_min"] <= lon <= bbox["lon_max"]


# ── Agent ─────────────────────────────────────────────────────────────────────


class VictimAgent:
    """Extracts needs and computes severity for verified incidents."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def assess(self, incident: VerifiedIncident, text: str = "") -> SeverityAssessment:
        """
        Assess needs and severity for a verified incident cluster.

        Parameters
        ----------
        incident:
            A ``VerifiedIncident`` produced by the VerificationAgent.
        text:
            Free-form report text for keyword extraction (bilingual).
            Falls back to an empty string — all needs will be ``False``.

        Returns
        -------
        SeverityAssessment
            Structured needs profile, severity score (0–1), priority label
            (P1–P4), and a per-factor breakdown dict.

        Severity Formula (Phase 4 spec)
        --------------------------------
        SeverityScore = min(
            1.0,
            (base_needs_score + keyword_mult + pop_density + sat_area) / 4.0
            × corroboration_bonus
            × temporal_escalation,
        )
        """
        # 1. Bilingual keyword needs extraction
        needs = self._extract_needs_keyword(text)

        # 2. Sub-factor computation
        base_needs_score = self._base_needs_score(needs)
        keyword_mult = self._keyword_multiplier(needs)
        pop_density = self._population_density_factor(incident.lat, incident.lon)
        sat_area = self._satellite_area_factor(incident)
        corroboration_bonus = self._corroboration_bonus(incident)
        temporal_escalation = self._temporal_escalation(incident)

        # 3. Severity formula
        raw = (base_needs_score + keyword_mult + pop_density + sat_area) / 4.0
        severity_score = min(1.0, raw * corroboration_bonus * temporal_escalation)

        # 4. Priority label
        priority = self._score_to_priority(severity_score)

        logger.debug(
            "VictimAgent.assess cluster=%s score=%.3f priority=%s",
            incident.cluster_id,
            severity_score,
            priority,
        )

        return SeverityAssessment(
            needs=needs,
            severity_score=round(severity_score, 4),
            priority=priority,
            factors={
                "base_needs_score": round(base_needs_score, 4),
                "keyword_multiplier": round(keyword_mult, 4),
                "population_density": round(pop_density, 4),
                "satellite_area": round(sat_area, 4),
                "corroboration_bonus": round(corroboration_bonus, 4),
                "temporal_escalation": round(temporal_escalation, 4),
            },
        )

    # ------------------------------------------------------------------
    # Needs extraction
    # ------------------------------------------------------------------

    def _extract_needs_keyword(self, text: str) -> NeedsProfile:
        """Fast bilingual keyword-based needs extraction."""
        text_lower = text.lower()
        return NeedsProfile(
            **{
                need: any(kw in text_lower for kw in keywords)
                for need, keywords in KEYWORD_MAP.items()
            }
        )

    # ------------------------------------------------------------------
    # Severity sub-factors
    # ------------------------------------------------------------------

    def _base_needs_score(self, needs: NeedsProfile) -> float:
        """
        Fraction of need flags that are True (6 total).

        Returns a value in [0.0, 1.0].
        """
        return sum(needs.model_dump().values()) / 6.0

    def _keyword_multiplier(self, needs: NeedsProfile) -> float:
        """
        Keyword severity multiplier.

        Medical + Rescue → 1.5  (life-threatening combination)
        Evacuation only  → 1.3
        Default          → 1.0
        """
        if needs.medical and needs.rescue:
            return 1.5
        if needs.evacuation:
            return 1.3
        return 1.0

    def _population_density_factor(self, lat: float, lon: float) -> float:
        """
        Population-density weight for the incident location.

        High-density urban core (Delhi Metro bbox) → 0.8
        Medium-density NCR fringe                  → 0.5
        Rural / outside known zones                → 0.2

        For production: replace with a WorldPop / LandScan raster query.
        """
        if _in_bbox(lat, lon, _DELHI_HIGH):
            return 0.8
        if _in_bbox(lat, lon, _DELHI_MED):
            return 0.5
        return 0.2

    def _satellite_area_factor(self, incident: VerifiedIncident) -> float:
        """
        Return 0.6 when a satellite source is present in the cluster's
        provenance (proxy for a large confirmed affected area), else 0.0.
        """
        return 0.6 if SourceType.SATELLITE in incident.source_provenance else 0.0

    def _corroboration_bonus(self, incident: VerifiedIncident) -> float:
        """
        Multi-source corroboration bonus: 1.0 + 0.20 × (N − 1).

        N=1 → 1.0  (single source, no bonus)
        N=2 → 1.2  (+20 %)
        N=3 → 1.4  (+40 %)
        """
        n = len(incident.source_provenance)
        return 1.0 + 0.20 * max(n - 1, 0)

    def _temporal_escalation(self, incident: VerifiedIncident) -> float:
        """
        Temporal escalation factor.

        An incident still generating active reports after 2 hours indicates
        a worsening situation → bump severity by 10 % (× 1.1).

        Fresh (≤ 2 h) → 1.0
        Old   (> 2 h) → 1.1
        """
        # Make timestamp timezone-aware for comparison
        ts = incident.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        age_hours = (datetime.now(UTC) - ts).total_seconds() / 3600
        return 1.1 if age_hours > 2.0 else 1.0

    # ------------------------------------------------------------------
    # Priority mapping
    # ------------------------------------------------------------------

    def _score_to_priority(self, score: float) -> Priority:
        """Map a severity score in [0, 1] to a P1–P4 priority label."""
        if score >= 0.75:
            return Priority.P1
        if score >= 0.5:
            return Priority.P2
        if score >= 0.25:
            return Priority.P3
        return Priority.P4
