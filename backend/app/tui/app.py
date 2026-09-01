"""
DisasterMesh TUI Dashboard -- terminal-based live incident monitoring.

Run the backend first:
    cd backend && uvicorn app.main:app --reload --port 8000

Then launch the TUI:
    python -m app.tui

Key bindings:
    q / Ctrl+C   Quit
    r            Refresh incidents
    d            Dispatch responders to selected incident
    s            Show situational summary
    UP/DOWN      Navigate incident table
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, RichLog, Static

logger = logging.getLogger(__name__)

# -- Configuration -----------------------------------------------------------

API_BASE = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws/updates"
REFRESH_INTERVAL_S = 5.0

# Nepal center for geo queries (Kathmandu)
DEFAULT_LAT = 27.7172
DEFAULT_LON = 85.3240
DEFAULT_RADIUS_M = 500_000  # 500 km

# -- Priority colors ---------------------------------------------------------

PRIORITY_STYLES = {
    "P1": "bold white on red",
    "P2": "bold black on dark_orange",
    "P3": "bold black on yellow",
    "P4": "dim white on gray",
}

STATUS_ICONS = {
    "REPORTED": "[RP]",
    "VERIFIED": "[VF]",
    "ASSIGNED": "[AS]",
    "EN_ROUTE": "[ER]",
    "ON_SCENE": "[SC]",
    "RESOLVED": "[RS]",
}


# -- Widgets -----------------------------------------------------------------


class IncidentSummary(Static):
    """Summary bar showing total incident counts by severity."""

    counts: reactive[dict[str, int]] = reactive(
        lambda: {"P1": 0, "P2": 0, "P3": 0, "P4": 0, "total": 0}
    )

    def render(self) -> str:
        c = self.counts
        return (
            f"  Incidents:  "
            f"[bold white on red] P1:{c['P1']} [/]  "
            f"[bold black on dark_orange] P2:{c['P2']} [/]  "
            f"[bold black on yellow] P3:{c['P3']} [/]  "
            f"[dim white on gray] P4:{c['P4']} [/]  "
            f"  Total: {c['total']}"
        )


class IncidentDetail(Static):
    """Right-panel detail view for the selected incident."""

    detail_data: reactive[dict[str, Any] | None] = reactive(lambda: None)

    def render(self) -> str:
        d = self.detail_data
        if d is None:
            return (
                "  Select an incident from the table to view details.\n\n"
                "  Press [bold]d[/bold] to dispatch responders.\n"
                "  Press [bold]s[/bold] for situational summary."
            )

        cluster_id = d.get("cluster_id", "?")
        severity = d.get("severity", d.get("priority", "P4"))
        confidence = d.get("confidence", 0.0)
        status = d.get("status", "?")
        lat = d.get("lat", 0.0)
        lon = d.get("lon", 0.0)
        ts = d.get("timestamp", "?")
        sources = d.get("source_provenance", [])
        needs = d.get("needs", {})

        # Format needs
        needs_parts = []
        for need_name, need_val in needs.items():
            if need_val:
                needs_parts.append(f"  [+] {need_name}")
        needs_str = "\n".join(needs_parts) if needs_parts else "  No needs identified"

        # Format sources
        sources_str = ", ".join(sources) if sources else "?"

        lines = [
            f"  ID: {cluster_id}",
            f"  Status: [bold]{status}[/bold]",
            f"  Severity: [{PRIORITY_STYLES.get(severity, '')}]{severity}[/]",
            f"  Confidence: {confidence:.1%}",
            f"  Location: {lat:.4f}, {lon:.4f}",
            f"  Time: {ts}",
            f"  Sources: {sources_str}",
            "",
            "  -- Needs --",
            needs_str,
        ]

        # Add assignment info if present
        assignments = d.get("assignments", [])
        if assignments:
            lines.append("")
            lines.append("  -- Assigned Responders --")
            for a in assignments:
                resp_id = a.get("responder_id", "?")
                eta = a.get("eta_seconds", 0)
                eta_min = int(eta / 60) if eta else 0
                cap = a.get("capability_match_score", 0)
                lines.append(f"  >> {resp_id[:12]}... ETA:{eta_min}m Match:{cap:.0%}")

        return "\n".join(lines)


# -- Main App ----------------------------------------------------------------


class DisasterMeshTUI(App):
    """DisasterMesh terminal dashboard -- live incident monitoring."""

    TITLE = "DisasterMesh -- Incident Dashboard"
    SUB_TITLE = "Multi-Agent Disaster Response Coordination"

    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 2;
        grid-columns: 2fr 1fr;
        grid-rows: auto 1fr;
    }

    #summary-bar {
        column-span: 2;
        height: 1;
        background: $accent-darken-2;
        color: $text;
        padding: 0 1;
    }

    #incident-table {
        width: 100%;
        height: 100%;
        border: solid $accent;
    }

    #detail-panel {
        width: 100%;
        height: 100%;
        border: solid $accent;
        padding: 1 2;
        overflow-y: auto;
    }

    #event-stream {
        column-span: 2;
        height: 8;
        border: solid $accent;
        background: $surface-darken-1;
    }

    DataTable > .datatable--header {
        background: $accent-darken-1;
        color: $text;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("d", "dispatch", "Dispatch", show=True),
        Binding("s", "summary", "Summary", show=True),
    ]

    # Reactive state
    incidents: reactive[list[dict[str, Any]]] = reactive(lambda: [])
    selected_cluster_id: reactive[str | None] = reactive(lambda: None)
    ws_connected: reactive[bool] = reactive(lambda: False)

    def __init__(self, api_base: str = API_BASE, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.api_base = api_base.rstrip("/")
        self._http_client: httpx.AsyncClient | None = None
        self._refresh_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield IncidentSummary(id="summary-bar")
        with Vertical(id="incident-table"):
            yield DataTable(cursor_type="row", id="incidents-table")
        yield IncidentDetail(id="detail-panel")
        with VerticalScroll(id="event-stream"):
            yield RichLog(id="event-log", highlight=True, markup=True)
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize the table, HTTP client, and start auto-refresh."""
        self._http_client = httpx.AsyncClient(timeout=10.0)

        # Configure table columns
        table = self.query_one("#incidents-table", DataTable)
        table.add_columns(
            "Severity",
            "Status",
            "Confidence",
            "Sources",
            "Lat",
            "Lon",
            "Cluster ID",
        )

        # Initial data load
        await self._load_incidents()

        # Start auto-refresh timer
        self._refresh_timer = self.set_interval(REFRESH_INTERVAL_S, self._on_refresh_tick)

        # Start WebSocket listener
        self._listen_ws()

        # Log startup
        self._log_event("[bold green]OK[/bold green] Dashboard connected to API")

    async def on_unmount(self) -> None:
        """Clean up resources."""
        if self._refresh_timer:
            self._refresh_timer.stop()
        if self._http_client:
            await self._http_client.aclose()

    # -- Data loading ---------------------------------------------------------

    async def _api_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Make a GET request to the backend API."""
        if not self._http_client:
            return None
        try:
            resp = await self._http_client.get(f"{self.api_base}{path}", params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            self._log_event(f"[red]API error {e.response.status_code}: {path}[/red]")
            return None
        except httpx.ConnectError:
            self._log_event("[red]Cannot connect to API -- is the backend running?[/red]")
            return None
        except Exception as e:
            self._log_event(f"[red]Request failed: {e}[/red]")
            return None

    async def _api_post(self, path: str, json_data: dict[str, Any] | None = None) -> Any:
        """Make a POST request to the backend API."""
        if not self._http_client:
            return None
        try:
            resp = await self._http_client.post(f"{self.api_base}{path}", json=json_data)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            self._log_event(f"[red]API error {e.response.status_code}: {path}[/red]")
            return None
        except httpx.ConnectError:
            self._log_event("[red]Cannot connect to API -- is the backend running?[/red]")
            return None
        except Exception as e:
            self._log_event(f"[red]Request failed: {e}[/red]")
            return None

    async def _load_incidents(self) -> None:
        """Fetch incidents from the API and update the table."""
        data = await self._api_get(
            "/incidents/",
            params={
                "lat": DEFAULT_LAT,
                "lon": DEFAULT_LON,
                "radius": DEFAULT_RADIUS_M,
                "limit": 100,
            },
        )
        if data is None:
            return

        incidents = data.get("incidents", [])
        self.incidents = incidents

        # Update table
        table = self.query_one("#incidents-table", DataTable)
        table.clear()

        counts = {"P1": 0, "P2": 0, "P3": 0, "P4": 0, "total": 0}

        for inc in incidents:
            severity = inc.get("severity", inc.get("priority", "P4"))
            status = inc.get("status", "?")
            confidence = inc.get("confidence", 0.0)
            sources = inc.get("source_provenance", [])
            lat = inc.get("lat", 0.0)
            lon = inc.get("lon", 0.0)
            cluster_id = inc.get("cluster_id", "?")

            # Count by severity
            if severity in counts:
                counts[severity] += 1
            counts["total"] += 1

            # Source abbreviations
            src_short = {
                "sms": "SMS",
                "whatsapp": "WA",
                "web_form": "WEB",
                "tweet": "TWT",
                "satellite": "SAT",
                "iot_sensor": "IOT",
                "news": "NEWS",
            }
            sources_display = " ".join(src_short.get(s, s) for s in sources) if sources else "--"

            # Status icon
            status_display = f"{STATUS_ICONS.get(status, '[??]')} {status}"

            table.add_row(
                f"[{PRIORITY_STYLES.get(severity, '')}]{severity}[/]",
                status_display,
                f"{confidence:.0%}",
                sources_display,
                f"{lat:.4f}",
                f"{lon:.4f}",
                cluster_id[:20],
            )

        # Update summary bar
        summary = self.query_one("#summary-bar", IncidentSummary)
        summary.counts = counts

        # Update detail panel if an incident is selected
        if self.selected_cluster_id:
            self._update_detail_for_cluster(self.selected_cluster_id)

    def _update_detail_for_cluster(self, cluster_id: str) -> None:
        """Update the detail panel for a specific cluster ID."""
        for inc in self.incidents:
            if inc.get("cluster_id") == cluster_id:
                detail = self.query_one("#detail-panel", IncidentDetail)
                detail.detail_data = inc
                return

    # -- Auto-refresh ---------------------------------------------------------

    def _on_refresh_tick(self) -> None:
        """Periodically refresh incident data."""
        self.run_worker(self._load_incidents(), exclusive=True)

    # -- WebSocket listener ---------------------------------------------------

    @work(exclusive=True, exit_on_error=False)
    async def _listen_ws(self) -> None:
        """Connect to the WebSocket and listen for real-time events."""
        import websockets

        while True:
            try:
                async with websockets.connect(WS_URL) as ws:
                    self.ws_connected = True
                    self._log_event("[bold green]OK[/bold green] WebSocket connected")

                    async for message in ws:
                        try:
                            msg_text = message.decode() if isinstance(message, bytes) else message
                            event = json.loads(msg_text)
                            self._handle_ws_event(event)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            self._log_event(f"[yellow]WS raw: {message!r}[/yellow]")

            except Exception as e:
                self.ws_connected = False
                self._log_event(f"[yellow]WS disconnected: {e} -- retrying in 5s...[/yellow]")
                await asyncio.sleep(5)

    def _handle_ws_event(self, event: dict[str, Any]) -> None:
        """Process a WebSocket event and update the UI."""
        event_type = event.get("event", "unknown")
        cluster_id = event.get("cluster_id", "?")

        if event_type == "lifecycle_transition":
            old = event.get("old_status", "?")
            new = event.get("new_status", "?")
            ts = event.get("timestamp", "")
            icon = STATUS_ICONS.get(new, "[??]")
            self._log_event(
                f"{icon} [bold]{cluster_id}[/bold]: {old} -> [bold green]{new}[/bold green]  ({ts})"
            )
            # Refresh data to pick up changes
            self.run_worker(self._load_incidents(), exclusive=True)
        else:
            self._log_event(f"[cyan]Event: {event_type}[/cyan] -- {json.dumps(event)[:200]}")

    # -- Event handlers -------------------------------------------------------

    @on(DataTable.RowHighlighted, "#incidents-table")
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """When a row is highlighted (UP/DOWN), update the detail panel."""
        table = self.query_one("#incidents-table", DataTable)
        row_idx = event.cursor_row
        if row_idx is not None:
            row_data = table.get_row_at(row_idx)
            if row_data and len(row_data) >= 7:
                cluster_id = str(row_data[6])  # Last column is cluster_id
                self.selected_cluster_id = cluster_id
                self._update_detail_for_cluster(cluster_id)

    # -- Actions --------------------------------------------------------------

    def action_refresh(self) -> None:
        """Manually refresh incident data."""
        self._log_event("[bold]Refreshing...[/bold]")
        self.run_worker(self._load_incidents(), exclusive=True)

    def action_dispatch(self) -> None:
        """Dispatch responders to the selected incident."""
        if not self.selected_cluster_id:
            self._log_event(
                "[yellow]No incident selected -- press UP/DOWN to select one first[/yellow]"
            )
            return

        self._log_event(
            f"[bold]Dispatching responders to [cyan]{self.selected_cluster_id}[/cyan]...[/bold]"
        )
        self._dispatch_incident(self.selected_cluster_id)

    @work(exclusive=False, exit_on_error=False)
    async def _dispatch_incident(self, cluster_id: str) -> None:
        """Call the dispatch API for a specific incident."""
        result = await self._api_post(f"/dispatch/{cluster_id}")
        if result is None:
            return

        status = result.get("status", "?")
        assignments = result.get("assignments", [])
        solver = result.get("solver_status", "?")
        reason = result.get("reason", "")

        if assignments:
            resp_ids = [a.get("responder_id", "?")[:12] for a in assignments]
            self._log_event(
                f"[bold green]OK[/bold green] Dispatched {len(assignments)} responder(s) to "
                f"[cyan]{cluster_id}[/cyan]: {', '.join(resp_ids)} (solver={solver})"
            )
        else:
            self._log_event(
                f"[yellow]No responders assigned to {cluster_id}: "
                f"status={status} reason={reason}[/yellow]"
            )

        # Refresh to pick up new status
        await self._load_incidents()

    def action_summary(self) -> None:
        """Fetch and display the situational summary for the selected incident."""
        if not self.selected_cluster_id:
            self._log_event("[yellow]No incident selected[/yellow]")
            return

        self._log_event(
            f"[bold]Fetching summary for [cyan]{self.selected_cluster_id}[/cyan]...[/bold]"
        )
        self._fetch_summary(self.selected_cluster_id)

    @work(exclusive=False, exit_on_error=False)
    async def _fetch_summary(self, cluster_id: str) -> None:
        """Fetch situational summary from the API."""
        result = await self._api_get(f"/incidents/{cluster_id}/summary")
        if result is None:
            return

        human = result.get("human_summary", "No summary available")
        self._log_event(f"[bold cyan]Situational Summary:[/bold cyan]\n{human}")

    # -- Logging --------------------------------------------------------------

    def _log_event(self, message: str) -> None:
        """Append a message to the event log panel."""
        try:
            log = self.query_one("#event-log", RichLog)
            timestamp = datetime.now(UTC).strftime("%H:%M:%S")
            log.write(f"[dim]{timestamp}[/dim] {message}")
        except Exception:
            pass


# -- Entry point --------------------------------------------------------------


def main() -> None:
    """Launch the DisasterMesh TUI dashboard."""
    import argparse

    parser = argparse.ArgumentParser(description="DisasterMesh TUI Dashboard")
    parser.add_argument(
        "--api",
        default=API_BASE,
        help=f"Backend API URL (default: {API_BASE})",
    )
    args = parser.parse_args()

    app = DisasterMeshTUI(api_base=args.api)
    app.run()


if __name__ == "__main__":
    main()
