#!/usr/bin/env python3
"""
DisasterMesh Live Demo Scenario -- Nepal Flood Response.

Simulates a realistic multi-source flood crisis in Nepal flowing through the
complete 6-agent pipeline. Designed for hackathon presentations with narration
lines you can read aloud while the script runs.

Usage
-----
    # 1. Start the backend first:
    cd backend && uvicorn app.main:app --reload --port 8000

    # 2. Run the demo:
    python scripts/run_demo_scenario.py [OPTIONS]

Options
-------
    --server URL      Backend API URL (default: http://localhost:8000)
    --delay SECONDS   Pause between phases (default: 2.0)
    --verbose         Print full JSON request/response bodies
    --dry-run         Print the scenario plan without HTTP calls

Example
-------
    python scripts/run_demo_scenario.py --delay 3 --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
WHITE = "\033[97m"


def _c(text: str, *codes: str) -> str:
    return "".join(codes) + str(text) + RESET


def _safe_print(text: str) -> None:
    """Print safely on Windows terminals that can't handle Unicode."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _banner(phase: int, title: str) -> None:
    line = "-" * 68
    _safe_print("")
    _safe_print(_c(f"+{line}+", BOLD, CYAN))
    _safe_print(_c(f"|  [{_ts()}]  PHASE {phase}: {title:<57}|", BOLD, CYAN))
    _safe_print(_c(f"+{line}+", BOLD, CYAN))


def _narration(text: str) -> None:
    """Print a narration line for the presenter to read aloud."""
    _safe_print("")
    _safe_print(_c(f'  >> "{text}"', BOLD, MAGENTA))
    _safe_print("")


def _ok(msg: str) -> None:
    _safe_print(_c(f"  [OK]  {msg}", GREEN))


def _info(msg: str) -> None:
    _safe_print(_c(f"  [i]  {msg}", WHITE))


def _warn(msg: str) -> None:
    _safe_print(_c(f"  [!!]  {msg}", YELLOW))


def _err(msg: str) -> None:
    _safe_print(_c(f"  [ERR] {msg}", RED))


def _sub(msg: str) -> None:
    _safe_print(_c(f"       {msg}", DIM))


def _pause(delay: float) -> None:
    """Human-readable pause between phases."""
    if delay > 0:
        _safe_print(_c(f"\n  ...  Waiting {delay:.0f}s before next phase...\n", DIM))
        time.sleep(delay)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _post(
    server: str,
    path: str,
    body: dict[str, Any],
    verbose: bool,
    dry_run: bool,
    label: str = "",
) -> tuple[int, dict[str, Any]]:
    if dry_run:
        _info(f"[DRY-RUN] POST {path}  <- {label}")
        if verbose:
            _sub(json.dumps(body, indent=4, default=str))
        return 200, {"status": "dry_run", "message_id": "dry-run-id"}

    try:
        import httpx
    except ImportError:
        _err("httpx not installed -- run:  pip install httpx")
        sys.exit(1)

    try:
        resp = httpx.post(f"{server}{path}", json=body, timeout=15.0)
        data: dict[str, Any] = {}
        try:
            data = resp.json()
        except Exception:
            pass

        if verbose:
            _sub(f"? POST {path}")
            _sub(f"<- {resp.status_code}: {json.dumps(data, default=str)[:300]}")

        return resp.status_code, data
    except Exception as exc:
        _err(f"HTTP error on POST {path}: {exc}")
        return 0, {}


def _get(
    server: str,
    path: str,
    verbose: bool,
    dry_run: bool,
    label: str = "",
) -> tuple[int, Any]:
    if dry_run:
        _info(f"[DRY-RUN] GET  {path}  <- {label}")
        return 200, {}

    try:
        import httpx
    except ImportError:
        _err("httpx not installed")
        sys.exit(1)

    try:
        resp = httpx.get(f"{server}{path}", timeout=15.0)
        data: Any = {}
        try:
            data = resp.json()
        except Exception:
            pass
        if verbose:
            _sub(f"? GET {path}")
            _sub(f"<- {resp.status_code}: {json.dumps(data, default=str)[:300]}")
        return resp.status_code, data
    except Exception as exc:
        _err(f"HTTP error on GET {path}: {exc}")
        return 0, {}


# ---------------------------------------------------------------------------
# Timeline tracking
# ---------------------------------------------------------------------------


class Timeline:
    def __init__(self) -> None:
        self._rows: list[tuple[str, float, str, str]] = []
        self._t_start = time.perf_counter()

    def record(self, step: str, elapsed_ms: float, ok: bool, detail: str = "") -> None:
        status = _c("PASS", GREEN) if ok else _c("FAIL", RED)
        self._rows.append((step, elapsed_ms, status, detail))

    def print_summary(self) -> None:
        total_s = time.perf_counter() - self._t_start
        _safe_print("")
        _safe_print(_c("=" * 80, BOLD, CYAN))
        _safe_print(_c(f"  DEMO SCENARIO SUMMARY  --  total wall time: {total_s:.1f}s", BOLD, CYAN))
        _safe_print(_c("=" * 80, BOLD, CYAN))
        header = f"  {'Step':<45}  {'Elapsed':>10}  {'Status':<12}  Detail"
        _safe_print(_c(header, BOLD))
        _safe_print(_c("  " + "-" * 76, DIM))
        for step, elapsed_ms, status, detail in self._rows:
            row = f"  {step:<45}  {elapsed_ms:>8.1f}ms  {status}  {detail}"
            _safe_print(row)
        _safe_print(_c("=" * 80, BOLD, CYAN))
        _safe_print("")


# ---------------------------------------------------------------------------
# Main demo scenario
# ---------------------------------------------------------------------------


def run_demo(server: str, delay: float, verbose: bool, dry_run: bool) -> None:
    tl = Timeline()
    cluster_ids: list[str] = []  # noqa: F841

    # -- Phase 0: Preflight --------------------------------------------------
    _banner(0, "Preflight -- Verify Backend Is Running")
    t0 = time.perf_counter()
    status, data = _get(server, "/health", verbose, dry_run, "health check")
    elapsed = (time.perf_counter() - t0) * 1000
    ok = status == 200 or dry_run
    tl.record("Phase 0: Health check", elapsed, ok, data.get("environment", ""))
    if ok:
        _ok(
            f"Server healthy -- env={data.get('environment', '?')}  version={data.get('version', '?')}"
        )
    else:
        _err(f"Server not reachable at {server} (status={status}).  Is uvicorn running?")
        if not dry_run:
            sys.exit(1)

    _pause(delay)

    # ==========================================================================
    # PHASE 1: Seed Nepal-area responder teams
    # ==========================================================================
    _banner(1, "Seed Responder Registry -- 5 Nepal disaster response teams")
    _narration(
        "Before the disaster strikes, we have 5 response teams stationed "
        "across the Kathmandu Valley -- medical, rescue, logistics, and evacuation units."
    )

    responder_teams: list[dict[str, Any]] = [
        {
            "name": "Kathmandu Medical Response Alpha",
            "team_type": "medical",
            "capabilities": ["medical", "rescue"],
            "team_size": 8,
            "capacity": 3,
            "lat": 27.7172,
            "lon": 85.3240,
        },
        {
            "name": "NDRF Nepal Flood Rescue Bravo",
            "team_type": "rescue",
            "capabilities": ["rescue", "water"],
            "team_size": 12,
            "capacity": 4,
            "lat": 27.6810,
            "lon": 85.4300,
        },
        {
            "name": "Bhaktapur Civil Defence Charlie",
            "team_type": "logistics",
            "capabilities": ["logistics", "evacuation"],
            "team_size": 6,
            "capacity": 2,
            "lat": 27.6710,
            "lon": 85.4298,
        },
        {
            "name": "Lalitpur Emergency Medical Delta",
            "team_type": "medical",
            "capabilities": ["medical"],
            "team_size": 5,
            "capacity": 2,
            "lat": 27.6644,
            "lon": 85.3188,
        },
        {
            "name": "Pokhara Water Rescue Echo",
            "team_type": "rescue",
            "capabilities": ["water", "rescue", "evacuation"],
            "team_size": 10,
            "capacity": 3,
            "lat": 28.2096,
            "lon": 83.9856,
        },
    ]

    for team in responder_teams:
        t0 = time.perf_counter()
        status, data = _post(server, "/responders", team, verbose, dry_run, team["name"])
        elapsed = (time.perf_counter() - t0) * 1000
        ok = status == 201 or dry_run
        rid = data.get("id", "dry-run-id")
        icon = "[OK]" if ok else "[ERR]"
        _safe_print(
            f"  {icon}  Registered: {_c(team['name'], BOLD)}  id={rid[:8]}...  ({elapsed:.0f} ms)"
        )
        tl.record(f"Seed: {team['name'][:30]}", elapsed, ok)

    _pause(delay)

    # ==========================================================================
    # PHASE 2: Citizen SMS flood reports (Kathmandu valley)
    # ==========================================================================
    _banner(2, "Citizen SMS Reports -- Nepal flood emergency calls")
    _narration(
        "Citizens start calling emergency helplines and sending SMS reports. "
        "Multiple people report the same flooding from slightly different locations. "
        "Watch how our system deduplicates these into a single incident cluster."
    )

    sms_reports = [
        ("?", "Water rising fast in Bagmati river, need boats urgently!", 27.6800, 85.4200),
        ("?", "Kathmandu ma Bagmati nadi badhiyo, madad chahiye!", 27.6810, 85.4210),
        ("?", "Flooding in Lalitpur, families trapped on rooftops, rescue ASAP", 27.6644, 85.3188),
        (
            "?",
            "Bhaktapur flooded, ancient temples at risk, people need medical help",
            27.6710,
            85.4298,
        ),
        ("?", "Terai region flood, water 4 feet deep, 20 families stranded", 27.6800, 85.4250),
    ]

    for emoji, text, lat, lon in sms_reports:
        t0 = time.perf_counter()
        status, data = _post(
            server,
            "/ingest/report",
            {
                "source": "sms",
                "text": text,
                "lat": lat,
                "lon": lon,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            verbose,
            dry_run,
            "SMS report",
        )
        elapsed = (time.perf_counter() - t0) * 1000
        ok = status == 200 or dry_run
        resolved = f"lat={data.get('lat', lat):.4f} lon={data.get('lon', lon):.4f}"
        _safe_print(
            f"  {'[OK]' if ok else '[ERR]'}  {emoji}  {_c(text[:60], BOLD)}  ({elapsed:.0f}ms)  {resolved}"
        )
        tl.record(f"SMS: {text[:30]}...", elapsed, ok)

    _pause(delay)

    # ==========================================================================
    # PHASE 3: Social media posts (tweets)
    # ==========================================================================
    _banner(3, "Social Media Signals -- Twitter/X posts about Nepal floods")
    _narration(
        "Social media lights up. People are posting photos and reports from the ground. "
        "Our system picks up these tweets and cross-references them with citizen SMS reports. "
        "Notice how confidence scores increase when multiple sources corroborate."
    )

    tweets: list[dict[str, Any]] = [
        {
            "source": "tweet",
            "text": "[!] BREAKING: Kathmandu valley flooded! Bagmati river overflowing, families on rooftops. Need immediate rescue #NepalFloods #Emergency",
            "url": "https://twitter.com/NepalAlert/status/1001",
            "lat": 27.7172,
            "lon": 85.3240,
        },
        {
            "source": "tweet",
            "text": "Devastating floods in Lalitpur. Water levels rising. Local authorities overwhelmed. Please help! #NepalFlood #Rescue",
            "url": "https://twitter.com/NepalNews/status/1002",
            "lat": 27.6644,
            "lon": 85.3188,
        },
        {
            "source": "tweet",
            "text": "Bhaktapur completely submerged. Ancient heritage sites under water. People need evacuation immediately #NepalFloods2026",
            "url": "https://twitter.com/HeritageWatch/status/1003",
            "lat": 27.6710,
            "lon": 85.4298,
        },
    ]

    for tweet in tweets:
        tweet["timestamp"] = datetime.now(UTC).isoformat()
        t0 = time.perf_counter()
        status, data = _post(server, "/ingest/social", tweet, verbose, dry_run, "tweet")
        elapsed = (time.perf_counter() - t0) * 1000
        ok = status == 200 or dry_run
        _safe_print(
            f"  {'[OK]' if ok else '[ERR]'}  [TW]  {_c(tweet['text'][:55], BOLD)}  ({elapsed:.0f}ms)"
        )
        tl.record(f"Tweet: {tweet['text'][:30]}...", elapsed, ok)

    _pause(delay)

    # ==========================================================================
    # PHASE 4: Satellite + IoT sensor data
    # ==========================================================================
    _banner(4, "Satellite & IoT Sensor Data -- Sentinel-2 + water level gauge")
    _narration(
        "Sentinel-2 satellite imagery confirms flooding via NDVI analysis. "
        "Simultaneously, an IoT water level sensor in the Bagmati river triggers "
        "an alert. Three independent sources now confirm the same incident."
    )

    # 4a: Satellite polygon
    satellite = {
        "source": "satellite",
        "geojson": {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [85.3100, 27.6600],
                        [85.4400, 27.6600],
                        [85.4400, 27.7200],
                        [85.3100, 27.7200],
                        [85.3100, 27.6600],
                    ]
                ],
            },
            "properties": {
                "flood_area_km2": 12.5,
                "water_depth_m": 2.3,
                "source": "Sentinel-2 Band B08/B03 NDVI",
                "acquisition_date": datetime.now(UTC).isoformat(),
            },
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }
    t0 = time.perf_counter()
    status, data = _post(server, "/ingest/satellite", satellite, verbose, dry_run, "Sentinel-2")
    elapsed = (time.perf_counter() - t0) * 1000
    ok = status == 200 or dry_run
    tl.record("Satellite: Sentinel-2 polygon", elapsed, ok)
    if ok:
        _ok(
            f"?  Satellite polygon indexed -- centroid {data.get('lat', '?')},{data.get('lon', '?')}  ({elapsed:.0f}ms)"
        )
    else:
        _warn(f"Satellite ingest returned {status}")

    _pause(1)

    # 4b: IoT sensor
    sensor = {
        "source": "iot_sensor",
        "sensor_id": "WL-BAGMATI-001",
        "sensor_type": "water_level",
        "value": 4.8,
        "unit": "metres",
        "lat": 27.6800,
        "lon": 85.4200,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    t0 = time.perf_counter()
    status, data = _post(server, "/ingest/sensor", sensor, verbose, dry_run, "IoT sensor")
    elapsed = (time.perf_counter() - t0) * 1000
    ok = status == 200 or dry_run
    tl.record("IoT: Bagmati water gauge 4.8m", elapsed, ok)
    if ok:
        _ok(f"[W]  IoT sensor alert -- water level 4.8m (threshold 3.0m)  ({elapsed:.0f}ms)")
    else:
        _warn(f"IoT sensor ingest returned {status}")

    _pause(delay)

    # ==========================================================================
    # PHASE 5: Query incidents & dispatch
    # ==========================================================================
    _banner(5, "Incident Query & Dispatch -- OR-Tools optimization")
    _narration(
        "Now let's see what the system has figured out. We query all nearby incidents "
        "and then dispatch responders using our OR-Tools SCIP solver. "
        "The optimizer minimizes total ETA while respecting capability constraints."
    )

    # Query incidents near Kathmandu
    t0 = time.perf_counter()
    status, data = _get(
        server,
        "/incidents/?lat=27.6800&lon=85.4200&radius=500000&limit=100",
        verbose,
        dry_run,
        "nearby incidents",
    )
    elapsed = (time.perf_counter() - t0) * 1000
    ok = status == 200 or dry_run

    incidents = data.get("incidents", []) if isinstance(data, dict) else []
    n_incidents = len(incidents)
    tl.record(f"Query: {n_incidents} incidents found", elapsed, ok)

    if incidents:
        _ok(f"[P] Found {n_incidents} incident(s) in the Kathmandu Valley")
        for inc in incidents[:5]:
            cid = inc.get("cluster_id", "?")
            sev = inc.get("severity", "?")
            conf = inc.get("confidence", 0)
            _sub(f"  {sev}  confidence={conf:.0%}  cluster={cid[:20]}...")
            if cid and cid != "?":
                cluster_ids.append(cid)
    else:
        _warn("No verified incidents yet -- waiting for verification agent...")
        for attempt in range(3):
            _info(f"Waiting 5s... (attempt {attempt + 1}/3)")
            time.sleep(5)
            status, data = _get(
                server,
                "/incidents/?lat=27.6800&lon=85.4200&radius=500000&limit=100",
                verbose,
                dry_run,
                "nearby incidents (retry)",
            )
            incidents = data.get("incidents", []) if isinstance(data, dict) else []
            n_incidents = len(incidents)
            if incidents:
                _ok(f"[P] Found {n_incidents} incident(s) on retry")
                for inc in incidents[:5]:
                    cid = inc.get("cluster_id", "?")
                    sev = inc.get("severity", "?")
                    conf = inc.get("confidence", 0)
                    _sub(f"  {sev}  confidence={conf:.0%}  cluster={cid[:20]}...")
                    if cid and cid != "?":
                        cluster_ids.append(cid)
                break
        else:
            _warn("Still no verified incidents after 3 retries")

    _pause(delay)

    # Dispatch responders to each cluster
    if cluster_ids:
        _banner(5, "Dispatch -- Assigning responders to each cluster")
        _narration(
            "The OR-Tools solver assigns the best responders to each incident. "
            "It considers: distance, team capabilities, and current availability."
        )

        for cid in cluster_ids[:3]:  # dispatch to top 3
            t0 = time.perf_counter()
            status, data = _post(server, f"/dispatch/{cid}", {}, verbose, dry_run, "dispatch")
            elapsed = (time.perf_counter() - t0) * 1000
            ok = status == 200 or dry_run
            assignments = data.get("assignments", [])
            method = data.get("solver_status", data.get("status", "?"))
            tl.record(f"Dispatch {cid[:15]}...", elapsed, ok, f"{len(assignments)} responders")

            if assignments:
                _ok(
                    f"[F]  {cid[:20]}... ? {len(assignments)} responder(s) assigned  solver={method}"
                )
                for a in assignments:
                    eta_min = int(a.get("eta_seconds", 0) / 60)
                    _sub(
                        f"  ? {a.get('responder_id', '?')[:12]}...  ETA={eta_min}min  "
                        f"match={a.get('capability_match_score', 0):.0%}"
                    )
            else:
                _warn(f"  No assignments for {cid[:20]}... status={method}")

            _pause(1)
    else:
        _warn("No clusters to dispatch -- skipping dispatch phase")

    _pause(delay)

    # ==========================================================================
    # PHASE 6: Lifecycle state machine
    # ==========================================================================
    if cluster_ids:
        _banner(6, "Lifecycle Tracking -- REPORTED ? RESOLVED")
        _narration(
            "As responders move through the operation, the system tracks every "
            "state transition in real-time. Watch the frontend and TUI update live "
            "as we advance through REPORTED, VERIFIED, ASSIGNED, EN_ROUTE, ON_SCENE, and RESOLVED."
        )

        lifecycle = [
            ("VERIFIED", "Verification Agent confirmed cluster confidence ? 0.8"),
            ("ASSIGNED", "Orchestrator committed responder assignments"),
            ("EN_ROUTE", "Responders confirmed departure from staging area"),
            ("ON_SCENE", "First responder arrived at flood zone"),
            ("RESOLVED", "Incident closed -- water levels receded, area safe"),
        ]

        cid = cluster_ids[0]
        for new_status, reason in lifecycle:
            t0 = time.perf_counter()
            status, data = _post(
                server,
                f"/incidents/{cid}/status",
                {"new_status": new_status, "reason": reason},
                verbose,
                dry_run,
                f"lifecycle ? {new_status}",
            )
            elapsed = (time.perf_counter() - t0) * 1000
            ok = status == 200 or dry_run
            old = data.get("old_status", "?")
            tl.record(f"Lifecycle: {old} ? {new_status}", elapsed, ok)

            icon_map = {
                "VERIFIED": "[?]",
                "ASSIGNED": "[F]",
                "EN_ROUTE": "?",
                "ON_SCENE": "??[F]",
                "RESOLVED": "[OK]",
            }
            icon = icon_map.get(new_status, "?")
            if ok:
                _ok(f"{icon}  {old} ? {_c(new_status, BOLD)}  ({elapsed:.0f}ms)")
            else:
                _warn(f"  {new_status} transition failed: {status}")

            _pause(0.5)

    # -- Summary --------------------------------------------------------------
    tl.print_summary()
    _narration(
        "That's the full DisasterMesh pipeline! From citizen SMS reports to "
        "satellite confirmation to automated dispatch -- all in real-time. "
        "Thank you!"
    )
    _ok("DisasterMesh demo scenario complete!")
    _safe_print("")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DisasterMesh Nepal Flood Demo Scenario",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--server", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between phases")
    parser.add_argument("--verbose", action="store_true", help="Print full JSON bodies")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without HTTP calls")
    args = parser.parse_args()

    _safe_print("")
    _safe_print(_c("=" * 72, BOLD, MAGENTA))
    _safe_print(_c("  DISASTERMESH -- Nepal Flood Demo Scenario", BOLD, MAGENTA))
    _safe_print(_c(f"  Server:   {args.server}", MAGENTA))
    _safe_print(_c(f"  Delay:    {args.delay}s between phases", MAGENTA))
    _safe_print(
        _c(
            f"  Mode:     {'DRY-RUN' if args.dry_run else 'LIVE'}  |  Verbose: {args.verbose}",
            MAGENTA,
        )
    )
    _safe_print(_c("=" * 72, BOLD, MAGENTA))

    run_demo(server=args.server, delay=args.delay, verbose=args.verbose, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
