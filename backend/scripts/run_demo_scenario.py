#!/usr/bin/env python3
"""
DisasterMesh Live Demo Scenario Runner — Phase 7.

Simulates a realistic multi-source flood crisis event flowing through the
complete 6-agent pipeline.  Outputs richly coloured, timestamped console
logs with a summary table at the end.

Usage
-----
    # Requires the FastAPI server to be running:
    cd backend && uvicorn app.main:app --reload --port 8000

    python backend/scripts/run_demo_scenario.py [OPTIONS]

Options
-------
    --server URL    Base URL of the DisasterMesh API  (default: http://localhost:8000)
    --verbose       Print full JSON request/response bodies
    --dry-run       Print the scenario plan without making real HTTP calls

Example
-------
    python backend/scripts/run_demo_scenario.py --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# ANSI colour helpers  (no external deps — works on macOS / Linux terminals)
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


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _banner(phase: int, title: str) -> None:
    line = "─" * 68
    print()
    print(_c(f"┌{line}┐", BOLD, CYAN))
    print(_c(f"│  [{_ts()}]  PHASE {phase}: {title:<57}│", BOLD, CYAN))
    print(_c(f"└{line}┘", BOLD, CYAN))


def _ok(msg: str) -> None:
    print(_c(f"  ✅  {msg}", GREEN))


def _info(msg: str) -> None:
    print(_c(f"  ℹ️   {msg}", WHITE))


def _warn(msg: str) -> None:
    print(_c(f"  ⚠️   {msg}", YELLOW))


def _err(msg: str) -> None:
    print(_c(f"  ❌  {msg}", RED))


def _sub(msg: str) -> None:
    print(_c(f"       {msg}", DIM))


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


def _post(
    server: str,
    path: str,
    body: dict,
    verbose: bool,
    dry_run: bool,
    label: str = "",
) -> tuple[int, dict]:
    """POST body to server+path.  Returns (status_code, response_json)."""
    if dry_run:
        _info(f"[DRY-RUN] POST {path}  ← {label}")
        if verbose:
            _sub(json.dumps(body, indent=4, default=str))
        return 200, {"status": "dry_run", "message_id": "dry-run-id"}

    try:
        import httpx
    except ImportError:
        _err("httpx not installed — run:  pip install httpx")
        sys.exit(1)

    try:
        resp = httpx.post(f"{server}{path}", json=body, timeout=15.0)
        data: dict = {}
        try:
            data = resp.json()
        except Exception:
            pass

        if verbose:
            _sub(f"→ Request:  POST {path}")
            _sub(json.dumps(body, indent=4, default=str))
            _sub(f"← Response: {resp.status_code}")
            _sub(json.dumps(data, indent=4, default=str))

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
        _info(f"[DRY-RUN] GET  {path}  ← {label}")
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
            _sub(f"→ GET {path}")
            _sub(f"← {resp.status_code}: " + json.dumps(data, indent=4, default=str)[:400])
        return resp.status_code, data
    except Exception as exc:
        _err(f"HTTP error on GET {path}: {exc}")
        return 0, {}


# ---------------------------------------------------------------------------
# Timeline tracking
# ---------------------------------------------------------------------------


class Timeline:
    def __init__(self) -> None:
        self._rows: list[tuple[str, float, str, str]] = []  # (step, elapsed_ms, status, detail)
        self._t_start = time.perf_counter()

    def record(self, step: str, elapsed_ms: float, ok: bool, detail: str = "") -> None:
        status = _c("✅ PASS", GREEN) if ok else _c("❌ FAIL", RED)
        self._rows.append((step, elapsed_ms, status, detail))

    def print_summary(self) -> None:
        total_s = time.perf_counter() - self._t_start
        print()
        print(_c("═" * 80, BOLD, CYAN))
        print(_c(f"  DEMO SCENARIO SUMMARY  —  total wall time: {total_s:.1f}s", BOLD, CYAN))
        print(_c("═" * 80, BOLD, CYAN))
        header = f"  {'Step':<40}  {'Elapsed':>10}  {'Status':<12}  Detail"
        print(_c(header, BOLD))
        print(_c("  " + "─" * 76, DIM))
        for step, elapsed_ms, status, detail in self._rows:
            row = f"  {step:<40}  {elapsed_ms:>8.1f}ms  {status}  {detail}"
            print(row)
        print(_c("═" * 80, BOLD, CYAN))
        print()


# ---------------------------------------------------------------------------
# Main demo scenario
# ---------------------------------------------------------------------------


def run_demo(server: str, verbose: bool, dry_run: bool) -> None:
    tl = Timeline()
    cluster_id: str | None = None

    # ── Phase 0: Preflight ──────────────────────────────────────────────────
    _banner(0, "Preflight — verify server is up")
    t0 = time.perf_counter()
    status, data = _get(server, "/health", verbose, dry_run, "health check")
    elapsed = (time.perf_counter() - t0) * 1000
    ok = status == 200 or dry_run
    tl.record("Phase 0: Health check", elapsed, ok, data.get("environment", ""))
    if ok:
        _ok(
            f"Server healthy — env={data.get('environment', 'unknown')}  version={data.get('version', '?')}"
        )
    else:
        _err(f"Server not reachable at {server} (status={status}).  Is uvicorn running?")
        if not dry_run:
            sys.exit(1)

    # ── Phase 1: Seed responders ────────────────────────────────────────────
    _banner(1, "Seed Responder Registry — 5 diverse teams")
    responder_teams = [
        {
            "name": "Delhi Medical Response Unit Alpha",
            "team_type": "medical",
            "capabilities": ["medical", "rescue"],
            "team_size": 8,
            "capacity": 3,
            "lat": 28.6600,
            "lon": 77.2200,
        },
        {
            "name": "NDRF Flood Rescue Team Bravo",
            "team_type": "rescue",
            "capabilities": ["rescue", "water"],
            "team_size": 12,
            "capacity": 4,
            "lat": 28.6750,
            "lon": 77.2500,
        },
        {
            "name": "Civil Defence Logistics Charlie",
            "team_type": "logistics",
            "capabilities": ["logistics", "evacuation"],
            "team_size": 6,
            "capacity": 2,
            "lat": 28.6450,
            "lon": 77.1900,
        },
        {
            "name": "AIIMS Emergency Medical Delta",
            "team_type": "medical",
            "capabilities": ["medical"],
            "team_size": 5,
            "capacity": 2,
            "lat": 28.5672,
            "lon": 77.2100,
        },
        {
            "name": "Delhi Fire Service Water Echo",
            "team_type": "rescue",
            "capabilities": ["water", "rescue"],
            "team_size": 10,
            "capacity": 3,
            "lat": 28.6800,
            "lon": 77.2600,
        },
    ]
    resp_ids: list[str] = []
    all_ok = True
    for team in responder_teams:
        t0 = time.perf_counter()
        team_name = str(team["name"])
        status, data = _post(server, "/responders", team, verbose, dry_run, team_name)
        elapsed = (time.perf_counter() - t0) * 1000
        ok = status == 201 or dry_run
        all_ok = all_ok and ok
        rid = data.get("id", "dry-run-id")
        resp_ids.append(rid)
        icon = "✅" if ok else "❌"
        print(f"  {icon}  Registered: {_c(team_name, BOLD)}  id={rid[:8]}…  ({elapsed:.0f} ms)")
    tl.record("Phase 1: Seed responders (×5)", elapsed, all_ok, f"{len(resp_ids)} IDs created")

    # ── Phase 2: Citizen SMS flood reports ─────────────────────────────────
    _banner(2, "Citizen SMS Reports — 5 overlapping Yamuna Bazar flood reports")
    sms_reports = [
        ("📱", "Water rising fast near Yamuna Bazar, need boats urgently", 28.6667, 77.2333),
        (
            "📱",
            "Yamuna ka paani bahut badh gaya hai, madad chahiye — Yamuna Bazar mein",
            28.6670,
            77.2336,
        ),
        (
            "📱",
            "Flooding at Yamuna Bazar, families on rooftops, rescue needed ASAP",
            28.6665,
            77.2330,
        ),
        (
            "📱",
            "Heavy flood near Yamuna Bazaar, 3 people stuck, need medical help",
            28.6672,
            77.2339,
        ),
        (
            "📱",
            "Yamuna bazar mein paani bhar gaya, log phanse hain, naaav bhejna",
            28.6664,
            77.2332,
        ),
    ]
    msg_ids: list[str] = []
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
        mid = data.get("message_id", "dry-run")
        msg_ids.append(mid)
        resolved = f"lat={data.get('lat', lat):.4f} lon={data.get('lon', lon):.4f}"
        print(
            f"  {'✅' if ok else '❌'}  {emoji}  {_c(text[:62], BOLD)}  ({elapsed:.0f} ms)  {resolved}"
        )
    tl.record("Phase 2: Citizen SMS × 5", elapsed, True, f"{len(msg_ids)} IDs created")

    # ── Phase 3: Satellite Sentinel-2 flood polygon ─────────────────────────
    _banner(3, "Satellite Ingestion — Sentinel-2 Flood Polygon")
    sentinel_polygon = {
        "source": "satellite",
        "geojson": {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [77.2280, 28.6630],
                        [77.2420, 28.6630],
                        [77.2420, 28.6730],
                        [77.2280, 28.6730],
                        [77.2280, 28.6630],
                    ]
                ],
            },
            "properties": {
                "flood_area_km2": 3.2,
                "water_depth_m": 1.8,
                "source": "Sentinel-2 Band B08/B03",
                "acquisition_date": datetime.now(UTC).isoformat(),
            },
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }
    t0 = time.perf_counter()
    status, data = _post(
        server, "/ingest/satellite", sentinel_polygon, verbose, dry_run, "Sentinel-2 polygon"
    )
    elapsed = (time.perf_counter() - t0) * 1000
    ok = status == 200 or dry_run
    tl.record(
        "Phase 3: Satellite (Sentinel-2)",
        elapsed,
        ok,
        f"centroid={data.get('lat', '?')},{data.get('lon', '?')}",
    )
    if ok:
        _ok(
            f"🛰️  Sentinel-2 polygon indexed — centroid lat={data.get('lat', '?')} lon={data.get('lon', '?')}  ({elapsed:.0f} ms)"
        )
    else:
        _warn(f"Satellite ingest returned {status}")

    # ── Phase 4: IoT water level spike ──────────────────────────────────────
    _banner(4, "IoT Sensor — Water Level Spike (Yamuna Bazar gauge WL-004)")
    sensor_payload = {
        "source": "iot_sensor",
        "sensor_id": "WL-YAMUNA-004",
        "sensor_type": "water_level",
        "value": 4.2,
        "unit": "metres",
        "lat": 28.6658,
        "lon": 77.2341,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    t0 = time.perf_counter()
    status, data = _post(server, "/ingest/sensor", sensor_payload, verbose, dry_run, "IoT sensor")
    elapsed = (time.perf_counter() - t0) * 1000
    ok = status == 200 or dry_run
    tl.record("Phase 4: IoT sensor (water_level=4.2m)", elapsed, ok, "above 3.0m alert threshold")
    if ok:
        _ok(f"🌊  IoT sensor alert indexed — value=4.2m (threshold=3.0m)  ({elapsed:.0f} ms)")
    else:
        _warn(f"IoT sensor ingest returned {status}")

    # ── Phase 5: Social media tweet ─────────────────────────────────────────
    _banner(5, "Social Signal — Tweet about Yamuna Bazar Flooding")
    tweet_payload = {
        "source": "tweet",
        "text": "🚨 BREAKING: Yamuna Bazar completely submerged. Residents on rooftops. NDRF boats needed urgently. #YamunaFlood #Delhi",
        "url": "https://twitter.com/example/status/12345678",
        "lat": 28.6669,
        "lon": 77.2337,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    t0 = time.perf_counter()
    status, data = _post(server, "/ingest/social", tweet_payload, verbose, dry_run, "tweet")
    elapsed = (time.perf_counter() - t0) * 1000
    ok = status == 200 or dry_run
    tl.record("Phase 5: Social tweet", elapsed, ok, "")
    if ok:
        _ok(f"🐦  Tweet indexed  ({elapsed:.0f} ms)")
    else:
        _warn(f"Social ingest returned {status}")

    # ── Phase 6: Query incident cluster ────────────────────────────────────
    _banner(6, "Verify Cluster — Query Nearby Incidents via REST")
    t0 = time.perf_counter()
    status, data = _get(
        server,
        "/incidents?lat=28.6667&lon=77.2333&radius=500",
        verbose,
        dry_run,
        "nearby incidents query",
    )
    elapsed = (time.perf_counter() - t0) * 1000
    ok = status == 200 or dry_run

    if isinstance(data, list) and data:
        cluster_id = data[0].get("cluster_id")
        n_incidents = len(data)
        sources = list({item.get("source", "?") for item in data})
        tl.record(
            "Phase 6: Cluster query", elapsed, ok, f"{n_incidents} incidents, sources={sources}"
        )
        _ok(
            f"📍  Found {n_incidents} nearby incident(s)  cluster_id={cluster_id}  sources={sources}  ({elapsed:.0f} ms)"
        )
    elif dry_run:
        cluster_id = "cluster_dry-run-001"
        tl.record("Phase 6: Cluster query", elapsed, True, "[dry-run]")
        _info(f"[DRY-RUN] Would query for nearby incidents  ({elapsed:.0f} ms)")
    else:
        tl.record("Phase 6: Cluster query", elapsed, False, f"status={status}")
        _warn(f"Incident query returned {status} — pipeline may not have formed a cluster yet")

    # ── Phase 7: Dispatch via Orchestrator ──────────────────────────────────
    _banner(7, "Dispatch — OR-Tools Optimization → Assign Responders")
    if cluster_id and not dry_run:
        t0 = time.perf_counter()
        status, data = _post(server, f"/dispatch/{cluster_id}", {}, verbose, dry_run, "dispatch")
        elapsed = (time.perf_counter() - t0) * 1000
        ok = status == 200 or dry_run
        assignments = data.get("assignments", [])
        method = data.get("status", "?")
        tl.record(
            "Phase 7: OR-Tools dispatch",
            elapsed,
            ok,
            f"{len(assignments)} responders, method={method}",
        )
        if ok:
            _ok(
                f"🚒  Dispatch complete — {len(assignments)} responder(s) assigned  method={method}  ({elapsed:.0f} ms)"
            )
            for a in assignments:
                eta_min = int(a.get("eta_seconds", 0) / 60)
                _sub(
                    f"Responder {a['responder_id'][:8]}…  ETA={eta_min} min  cap_match={a.get('capability_match_score', 0):.2f}"
                )
        else:
            _warn(f"Dispatch returned {status}")
    else:
        t0 = time.perf_counter()
        status, data = _post(
            server, "/dispatch/cluster_dry-run-001", {}, verbose, dry_run, "dispatch"
        )
        elapsed = (time.perf_counter() - t0) * 1000
        tl.record("Phase 7: OR-Tools dispatch", elapsed, True, "[dry-run or no cluster]")
        _info(f"[DRY-RUN] Would dispatch for cluster_id={cluster_id}  ({elapsed:.0f} ms)")

    # ── Phase 8: Step through full lifecycle ─────────────────────────────────
    _banner(8, "Lifecycle State Machine — REPORTED → VERIFIED → … → RESOLVED")
    lifecycle_steps = [
        ("VERIFIED", "Verification Agent confirmed cluster confidence ≥ 0.8"),
        ("ASSIGNED", "Orchestrator committed responder assignments"),
        ("EN_ROUTE", "Responders confirmed departure from staging area"),
        ("ON_SCENE", "First responder arrived at Yamuna Bazar flood zone"),
        ("RESOLVED", "Incident closed by on-scene commander after water receded"),
    ]

    if cluster_id:
        for new_status, reason in lifecycle_steps:
            t0 = time.perf_counter()
            status, data = _post(
                server,
                f"/incidents/{cluster_id}/status",
                {"new_status": new_status, "reason": reason, "citizen_phone": "+919876543210"},
                verbose,
                dry_run,
                f"lifecycle → {new_status}",
            )
            elapsed = (time.perf_counter() - t0) * 1000
            ok = status == 200 or dry_run
            old = data.get("old_status", "?")
            new = data.get("new_status", new_status)
            tl.record(f"Phase 8: {old} → {new}", elapsed, ok, reason[:40])
            icon_map = {
                "VERIFIED": "🔍",
                "ASSIGNED": "🚒",
                "EN_ROUTE": "⏱️",
                "ON_SCENE": "👨‍🚒",
                "RESOLVED": "✨",
            }
            icon = icon_map.get(new_status, "➡️")
            if ok:
                _ok(f"{icon}  {old} → {_c(new, BOLD)}  ({elapsed:.0f} ms)")
            else:
                _warn(f"{new_status} transition returned {status}: {data}")
            time.sleep(0.05)  # small human-readable pause between steps
    else:
        for new_status, reason in lifecycle_steps:
            _info(f"[DRY-RUN] → {new_status}: {reason}")
            tl.record(f"Phase 8: → {new_status}", 0, True, "[dry-run]")

    # ── Summary ──────────────────────────────────────────────────────────────
    tl.print_summary()
    _ok("DisasterMesh Phase 7 demo scenario complete!")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DisasterMesh live demo scenario runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--server", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--verbose", action="store_true", help="Print full JSON bodies")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without HTTP calls")
    args = parser.parse_args()

    print()
    print(_c("=" * 72, BOLD, MAGENTA))
    print(_c("  🌐  DISASTERMESH — Live Demo Scenario Runner  (Phase 7)", BOLD, MAGENTA))
    print(_c(f"  Server: {args.server}", MAGENTA))
    print(
        _c(
            f"  Mode:   {'DRY-RUN' if args.dry_run else 'LIVE'}  |  Verbose: {args.verbose}",
            MAGENTA,
        )
    )
    print(_c("=" * 72, BOLD, MAGENTA))

    run_demo(server=args.server, verbose=args.verbose, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
