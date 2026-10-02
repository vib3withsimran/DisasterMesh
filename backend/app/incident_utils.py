"""
DisasterMesh Incident Utilities -- Canonical normalization for incidents.

Ensures complete consistency across:
- GET /incidents/ (table & list queries)
- GET /incidents/{id}
- GET /incidents/{cluster_id}/summary (situational summary)
- POST /dispatch/{cluster_id} (responder dispatch)

Prevents conflicting fallbacks (e.g. 30% in table vs 50% in summary).
Derives realistic, dynamic metrics based on real source types and incident text
when an incident has not yet completed full agent verification.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.schemas import NeedsProfile, Priority, SourceType

# Bilingual keyword patterns for needs detection
KEYWORD_NEEDS: dict[str, list[str]] = {
    "medical": [
        "injured",
        "bleeding",
        "medical",
        "ambulance",
        "hospital",
        "doctor",
        "wound",
        "hurt",
        "casualt",
        "घायल",
        "खून",
        "अस्पताल",
        "डॉक्टर",
        "औषधि",
    ],
    "shelter": [
        "homeless",
        "shelter",
        "tent",
        "displaced",
        "refuge",
        "submerged",
        "underwater",
        "roof",
        "rooftop",
        "छत",
        "बेघर",
        "शरण",
        "तंबू",
        "डूब",
    ],
    "evacuation": [
        "evacuate",
        "evacuation",
        "flee",
        "escape",
        "stranded",
        "trapped",
        "stuck",
        "cut off",
        "families stranded",
        "निकासी",
        "भागो",
        "बाहर",
        "फंसे",
    ],
    "rescue": [
        "rescue",
        "trapped",
        "stuck",
        "help",
        "save",
        "boat",
        "boats",
        "madad",
        "नाव",
        "बचाओ",
        "फंसे",
        "मदद",
        "गुहार",
    ],
    "water": [
        "water",
        "flood",
        "flooding",
        "river",
        "overflow",
        "drown",
        "waterlogging",
        "water level",
        "gauge",
        "metres",
        "feet deep",
        "पानी",
        "बाढ़",
        "नदी",
    ],
    "food": [
        "food",
        "hungry",
        "ration",
        "starving",
        "drinking water",
        "dry food",
        "खाना",
        "भूख",
        "राशन",
        "अन्न",
    ],
}


def derive_needs_from_text(text: str) -> dict[str, bool]:
    """Extract boolean need flags from raw text using bilingual keyword matching."""
    t = text.lower()
    return {
        need: any(kw in t for kw in keywords)
        for need, keywords in KEYWORD_NEEDS.items()
    }


def derive_confidence(raw: dict[str, Any]) -> float:
    """
    Return explicit confidence if present in raw payload.
    Otherwise, derive a realistic demo score based on source provenance and corroboration.
    """
    conf = raw.get("confidence")
    if conf is not None:
        try:
            val = float(conf)
            # If valid non-zero confidence was stored, return it
            if val > 0.0:
                return round(val, 2)
        except (ValueError, TypeError):
            pass

    # Source-based realistic confidence
    sources = raw.get("source_provenance", [])
    if not sources and raw.get("source"):
        sources = [raw["source"]]

    sources_lower = [str(s.value if hasattr(s, "value") else s).lower() for s in sources]

    # Baseline confidence by source reliability
    if any("satellite" in s for s in sources_lower):
        base = 0.88
    elif any("sensor" in s or "iot" in s for s in sources_lower):
        base = 0.82
    elif any("sms" in s or "whatsapp" in s for s in sources_lower):
        base = 0.65
    elif any("tweet" in s or "social" in s for s in sources_lower):
        base = 0.55
    else:
        base = 0.60

    # Cross-source corroboration boost
    distinct = set(sources_lower)
    if len(distinct) > 1:
        base = min(0.98, base + (len(distinct) - 1) * 0.12)

    return round(base, 2)


def derive_severity(raw: dict[str, Any], needs: dict[str, bool] | None = None) -> Priority:
    """
    Return explicit severity if valid in raw payload.
    Otherwise, derive priority label (P1-P4) from needs and text urgency.
    """
    val = raw.get("severity") or raw.get("priority")
    if val:
        try:
            return Priority(str(val).upper())
        except ValueError:
            pass

    if needs is None:
        needs_raw = raw.get("needs") or {}
        needs = needs_raw if any(needs_raw.values()) else derive_needs_from_text(raw.get("text", ""))

    text = str(raw.get("text", "")).lower()

    # P1: Immediate life safety threat (medical + rescue, trapped on rooftops, elderly/children trapped)
    if (needs.get("medical") and needs.get("rescue")) or any(
        w in text for w in [
            "trapped",
            "injured",
            "bleeding",
            "critical",
            "emergency",
            "urgently",
            "rooftop",
            "families trapped",
            "swept away",
            "need boats urgently",
            "मदद चाहिए",
            "बचाओ",
        ]
    ):
        return Priority.P1

    # P2: High urgency (active flooding, evacuation needed, rapid water rise)
    if needs.get("rescue") or needs.get("evacuation") or any(
        w in text for w in [
            "rising fast",
            "submerged",
            "completely underwater",
            "water level rising",
            "flash flood",
            "danger mark",
            "impassable",
            "overflow",
            "4 feet",
        ]
    ):
        return Priority.P2

    # P3: Medium (shelter, water, food logistics)
    if needs.get("shelter") or needs.get("water") or needs.get("food"):
        return Priority.P3

    # Default to P3 for unclassified disaster incidents
    return Priority.P3


def normalize_incident_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Create a complete, fully normalized incident dictionary matching the
    frontend Incident interface and TUI requirements.
    """
    ts_epoch = raw.get("timestamp_epoch")
    if ts_epoch:
        ts = datetime.fromtimestamp(ts_epoch, tz=UTC).isoformat()
    elif "timestamp" in raw and raw["timestamp"]:
        ts_val = raw["timestamp"]
        ts = ts_val if isinstance(ts_val, str) else ts_val.isoformat()
    else:
        ts = datetime.now(UTC).isoformat()

    source = raw.get("source", "")
    provenance = raw.get("source_provenance", [])
    if not provenance and source:
        provenance = [source]

    # Needs
    needs_raw = raw.get("needs") or {}
    if not any(needs_raw.values()) and raw.get("text"):
        needs_dict = derive_needs_from_text(raw["text"])
    else:
        needs_dict = {
            "medical": bool(needs_raw.get("medical", False)),
            "shelter": bool(needs_raw.get("shelter", False)),
            "evacuation": bool(needs_raw.get("evacuation", False)),
            "rescue": bool(needs_raw.get("rescue", False)),
            "water": bool(needs_raw.get("water", False)),
            "food": bool(needs_raw.get("food", False)),
        }

    confidence = derive_confidence(raw)
    severity = derive_severity(raw, needs=needs_dict)
    status = raw.get("status", "REPORTED")

    cluster_id = raw.get("cluster_id") or raw.get("proto_id") or raw.get("id") or "incident-unknown"

    return {
        "cluster_id": str(cluster_id),
        "source_provenance": [
            s.value if hasattr(s, "value") else str(s) for s in provenance
        ],
        "lat": float(raw.get("lat") or 0.0),
        "lon": float(raw.get("lon") or 0.0),
        "timestamp": ts,
        "confidence": confidence,
        "severity": str(severity),
        "needs": needs_dict,
        "media_urls": raw.get("media_urls", []),
        "status": str(status),
        "text": raw.get("text", ""),
    }
