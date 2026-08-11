"""
Orchestrator Agent — Agent 5.

Dispatch pipeline implemented as a LangGraph StateGraph.

Graph topology
--------------

    [fetch_responders]
           │
           ▼
    [run_solver]   ← OR-Tools SCIP (pywraplp)
           │
     ┌─────┴──────┐
     │ INFEASIBLE  │
     ▼             ▼
[heuristic]   [commit_assignments]
     │                │
     └────────┬───────┘
              ▼
       (DispatchResult)

Nodes
-----
fetch_responders    Query ResourceAgent for geo-filtered available responders.
run_solver          Run OR-Tools SCIP; populates `assigned_indices` + `solver_status`.
heuristic_assign    Greedy cap-score-then-ETA sort; fallback when solver fails.
commit_assignments  Persist DispatchRecords, update responder statuses, build result.

State
-----
DispatchState  TypedDict flowing through the graph.

Implemented in Phase 5.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from math import asin, cos, radians, sin, sqrt
from typing import TypedDict
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.resource import ResourceAgent, get_resource_agent
from app.models import DispatchRecord
from app.schemas import (
    Assignment,
    DispatchResult,
    DispatchStatus,
    NeedsProfile,
    Priority,
    Responder,
    ResponderCapability,
    ResponderStatus,
    StatusUpdate,
    VerifiedIncident,
)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_PRIORITY_WEIGHTS: dict[str, float] = {
    Priority.P1: 4.0,
    Priority.P2: 3.0,
    Priority.P3: 2.0,
    Priority.P4: 1.0,
}

_MIN_RESPONDERS: dict[str, int] = {
    Priority.P1: 2,
    Priority.P2: 1,
    Priority.P3: 1,
    Priority.P4: 0,
}

_SEVERITY_UNITS: dict[str, int] = {
    Priority.P1: 3,
    Priority.P2: 2,
    Priority.P3: 1,
    Priority.P4: 1,
}

# Capability-mismatch penalty (seconds equivalent added to objective cost)
_MISMATCH_PENALTY_S: float = 600.0

# OR-Tools SCIP solver wall-clock time limit
_SOLVER_TIME_LIMIT_MS: int = 500


# ── Shared helpers ────────────────────────────────────────────────────────────


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * asin(sqrt(a)) * 6_371_000


def _eta_seconds(incident: VerifiedIncident, responder: Responder) -> float:
    """Travel time in seconds (Haversine, 30 km/h = 8.333 m/s)."""
    if incident.lat is None or incident.lon is None:
        return 0.0
    dist = _haversine_m(incident.lat, incident.lon, responder.lat, responder.lon)
    return dist / 8.333


def _required_caps(incident: VerifiedIncident) -> dict[str, bool]:
    """Map incident NeedsProfile → capability requirement dict."""
    n: NeedsProfile = incident.needs
    return {
        ResponderCapability.MEDICAL: n.medical,
        ResponderCapability.RESCUE: n.rescue,
        ResponderCapability.WATER: n.water,
        ResponderCapability.LOGISTICS: n.evacuation or n.shelter,
        ResponderCapability.EVACUATION: n.evacuation,
    }


def _cap_score(responder: Responder, required: dict[str, bool]) -> float:
    """Proportion of required capabilities the responder satisfies (0.0–1.0)."""
    needed = [c for c, req in required.items() if req]
    if not needed:
        return 1.0
    resp_caps = {c.value for c in responder.capabilities}
    return sum(1 for c in needed if c in resp_caps) / len(needed)


# ── LangGraph state ───────────────────────────────────────────────────────────


class DispatchState(TypedDict, total=False):
    """
    Shared state that flows through every node of the dispatch graph.

    Each node reads what it needs and writes its outputs back into this dict.
    LangGraph merges the returned dict into the running state automatically.
    """

    # Inputs (set before graph.invoke)
    incident: VerifiedIncident
    priority: str
    resource_agent: ResourceAgent
    db: AsyncSession

    # Populated by fetch_responders
    available: list[Responder]
    req_caps: dict[str, bool]

    # Populated by run_solver or heuristic_assign
    assigned_indices: list[int]
    solver_status: str
    optimization_method: str  # "OPTIMAL" | "HEURISTIC_FALLBACK"

    # Populated by commit_assignments
    result: DispatchResult


# ── Graph nodes ───────────────────────────────────────────────────────────────


async def fetch_responders(state: DispatchState) -> DispatchState:
    """
    Node 1 — Query the ResourceAgent for available responders near the incident.

    Also pre-computes the required capability dict for downstream nodes.
    """
    incident: VerifiedIncident = state["incident"]
    resource_agent: ResourceAgent = state["resource_agent"]

    available = await resource_agent.get_available_responders(incident)
    req = _required_caps(incident)

    logger.info(
        "[fetch_responders] %d responders available for %s",
        len(available),
        incident.cluster_id,
    )
    return {"available": available, "req_caps": req}


async def run_solver(state: DispatchState) -> DispatchState:
    """
    Node 2 — Run the OR-Tools SCIP linear program.

    Decision variables x[i] ∈ {0,1} (assign responder i or not).
    Objective: minimize Σ x[i] * cost[i]
    Constraints:
      • Σ x[i] >= min_responders(priority)
      • Σ x[i]*capacity[i] >= severity_units(priority)
      • For each required cap c: Σ x[i : cap c] >= 1
    """
    incident: VerifiedIncident = state["incident"]
    available: list[Responder] = state.get("available", [])
    req: dict[str, bool] = state.get("req_caps", {})
    priority: str = state.get("priority", Priority.P4)

    if not available:
        return {
            "assigned_indices": [],
            "solver_status": "NO_RESPONDERS",
            "optimization_method": "NONE",
        }

    try:
        from ortools.linear_solver import pywraplp  # type: ignore[import]
    except ImportError:
        logger.warning("[run_solver] OR-Tools not available — will use heuristic")
        return {
            "assigned_indices": [],
            "solver_status": "IMPORT_ERROR",
            "optimization_method": "HEURISTIC_FALLBACK",
        }

    solver = pywraplp.Solver.CreateSolver("SCIP")
    if solver is None:
        return {
            "assigned_indices": [],
            "solver_status": "SOLVER_INIT_ERROR",
            "optimization_method": "HEURISTIC_FALLBACK",
        }

    solver.set_time_limit(_SOLVER_TIME_LIMIT_MS)
    n = len(available)
    pw = _PRIORITY_WEIGHTS.get(priority, 1.0)

    # Decision variables
    x = [solver.IntVar(0, 1, f"x_{i}") for i in range(n)]

    # Objective
    objective = solver.Objective()
    for i, resp in enumerate(available):
        eta_s = _eta_seconds(incident, resp)
        mismatch = (1.0 - _cap_score(resp, req)) * _MISMATCH_PENALTY_S
        objective.SetCoefficient(x[i], (eta_s / pw) + mismatch)
    objective.SetMinimization()

    # Constraint 1: minimum responders per priority
    min_r = _MIN_RESPONDERS.get(priority, 1)
    if min_r > 0:
        solver.Add(solver.Sum(x) >= min_r)

    # Constraint 2: total capacity >= severity units
    sev = _SEVERITY_UNITS.get(priority, 1)
    solver.Add(solver.Sum([x[i] * available[i].capacity for i in range(n)]) >= sev)

    # Constraint 3: each required capability covered by at least one assigned responder
    for cap_name, is_req in req.items():
        if not is_req:
            continue
        capable = [
            i for i, r in enumerate(available) if cap_name in {c.value for c in r.capabilities}
        ]
        if capable:
            solver.Add(solver.Sum([x[i] for i in capable]) >= 1)

    # Solve
    status_code = solver.Solve()
    status_map = {
        pywraplp.Solver.OPTIMAL: "OPTIMAL",
        pywraplp.Solver.FEASIBLE: "FEASIBLE",
        pywraplp.Solver.INFEASIBLE: "INFEASIBLE",
        pywraplp.Solver.UNBOUNDED: "UNBOUNDED",
        pywraplp.Solver.ABNORMAL: "ABNORMAL",
        pywraplp.Solver.NOT_SOLVED: "NOT_SOLVED",
    }
    status_str = status_map.get(status_code, "UNKNOWN")

    if status_code in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        assigned = [i for i in range(n) if x[i].solution_value() > 0.5]
        logger.info(
            "[run_solver] SCIP %s → %d responder(s) for %s",
            status_str,
            len(assigned),
            incident.cluster_id,
        )
        return {
            "assigned_indices": assigned,
            "solver_status": status_str,
            "optimization_method": "OPTIMAL",
        }

    logger.warning(
        "[run_solver] SCIP %s for %s — routing to heuristic",
        status_str,
        incident.cluster_id,
    )
    return {
        "assigned_indices": [],
        "solver_status": status_str,
        "optimization_method": "HEURISTIC_FALLBACK",
    }


async def heuristic_assign(state: DispatchState) -> DispatchState:
    """
    Node 3 (fallback) — Greedy assignment when the solver is infeasible / timed out.

    Sort candidates by: capability_score DESC, ETA ASC.
    Take the first max(min_responders, 1) candidates.
    """
    incident: VerifiedIncident = state["incident"]
    available: list[Responder] = state.get("available", [])
    req: dict[str, bool] = state.get("req_caps", {})
    priority: str = state.get("priority", Priority.P4)

    min_r = max(_MIN_RESPONDERS.get(priority, 1), 1)

    ranked = sorted(
        range(len(available)),
        key=lambda i: (-_cap_score(available[i], req), _eta_seconds(incident, available[i])),
    )
    assigned = ranked[:min_r]

    logger.info(
        "[heuristic_assign] Assigned %d responder(s) to %s",
        len(assigned),
        incident.cluster_id,
    )
    return {
        "assigned_indices": assigned,
        "optimization_method": "HEURISTIC_FALLBACK",
    }


async def commit_assignments(state: DispatchState) -> DispatchState:
    """
    Node 4 — Persist DispatchRecords, update responder statuses, build DispatchResult.

    This node is always the terminal node regardless of which path was taken.
    """
    incident: VerifiedIncident = state["incident"]
    available: list[Responder] = state.get("available", [])
    assigned_indices: list[int] = state.get("assigned_indices", [])
    req: dict[str, bool] = state.get("req_caps", {})
    solver_status: str = state.get("solver_status", "")
    opt_method: str = state.get("optimization_method", "OPTIMAL")
    resource_agent: ResourceAgent = state["resource_agent"]
    db: AsyncSession = state["db"]

    if not assigned_indices:
        status = DispatchStatus.NO_RESPONDERS if not available else DispatchStatus.SOLVER_INFEASIBLE
        reason = (
            "No responders available"
            if not available
            else "No responders could be assigned (solver infeasible + heuristic empty)"
        )
        result = DispatchResult(
            cluster_id=incident.cluster_id,
            status=status,
            solver_status=solver_status,
            reason=reason,
        )
        return {"result": result}

    dispatch_status = (
        DispatchStatus.ASSIGNED if opt_method == "OPTIMAL" else DispatchStatus.HEURISTIC
    )

    assignments: list[Assignment] = []
    total_capacity = 0

    for idx in assigned_indices:
        resp = available[idx]
        eta_s = _eta_seconds(incident, resp)
        score = _cap_score(resp, req)

        a = Assignment(
            id=str(uuid4()),
            cluster_id=incident.cluster_id,
            responder_id=resp.id,
            eta_seconds=eta_s,
            capability_match_score=score,
            optimization_method=opt_method,
            assigned_at=datetime.now(UTC),
        )
        assignments.append(a)
        total_capacity += resp.capacity

        # Persist audit record
        db.add(
            DispatchRecord(
                id=a.id,
                cluster_id=incident.cluster_id,
                responder_id=resp.id,
                eta_seconds=eta_s,
                capability_match_score=score,
                optimization_method=opt_method,
                status="ASSIGNED",
                assigned_at=a.assigned_at,
            )
        )

        # Update responder live status
        await resource_agent.update_responder_status(
            resp.id,
            StatusUpdate(
                status=ResponderStatus.ASSIGNED,
                incident_id=incident.cluster_id,
                eta_minutes=int(eta_s / 60) if eta_s > 0 else None,
            ),
        )

    await db.flush()

    min_eta = min(a.eta_seconds for a in assignments) if assignments else 0.0

    result = DispatchResult(
        cluster_id=incident.cluster_id,
        status=dispatch_status,
        assignments=assignments,
        min_eta_seconds=min_eta,
        total_capacity=total_capacity,
        solver_status=solver_status,
    )

    logger.info(
        "[commit_assignments] %s → %d assigned, min_ETA=%.0fs, method=%s",
        incident.cluster_id,
        len(assignments),
        min_eta,
        opt_method,
    )
    return {"result": result}


# ── Edge router ───────────────────────────────────────────────────────────────


def _route_after_solver(state: DispatchState) -> str:
    """
    Conditional edge after run_solver.

    Routes to:
      "heuristic_assign"   if the solver found no solution
      "commit_assignments" if the solver succeeded
    """
    if not state.get("assigned_indices"):
        return "heuristic_assign"
    return "commit_assignments"


# ── Graph construction ────────────────────────────────────────────────────────


def _build_dispatch_graph():
    """
    Build and compile the LangGraph StateGraph for the dispatch pipeline.

    Called once at module import; the compiled graph is reused for every
    dispatch_incident() call.
    """
    from langgraph.graph import StateGraph  # type: ignore[import]

    builder = StateGraph(DispatchState)

    # Register nodes
    builder.add_node("fetch_responders", fetch_responders)
    builder.add_node("run_solver", run_solver)
    builder.add_node("heuristic_assign", heuristic_assign)
    builder.add_node("commit_assignments", commit_assignments)

    # Entry point
    builder.set_entry_point("fetch_responders")

    # Linear edge: fetch → solver
    builder.add_edge("fetch_responders", "run_solver")

    # Conditional edge: solver → (heuristic | commit)
    builder.add_conditional_edges(
        "run_solver",
        _route_after_solver,
        {
            "heuristic_assign": "heuristic_assign",
            "commit_assignments": "commit_assignments",
        },
    )

    # Heuristic always leads to commit
    builder.add_edge("heuristic_assign", "commit_assignments")

    # commit_assignments is the terminal node
    builder.set_finish_point("commit_assignments")

    return builder.compile()


# Compile once at import time (no cost — just wires the graph)
_dispatch_graph = _build_dispatch_graph()


# ── Orchestrator Agent ────────────────────────────────────────────────────────


class OrchestratorAgent:
    """
    Dispatch optimizer.

    Uses a LangGraph StateGraph to manage the dispatch workflow:
      fetch_responders → run_solver → [heuristic_assign →] commit_assignments

    OR-Tools SCIP handles the combinatorial optimization inside ``run_solver``.
    LangGraph manages state flow, conditional branching, and makes each step
    independently inspectable and replaceable.
    """

    def __init__(self, resource_agent: ResourceAgent, db: AsyncSession) -> None:
        self.resource_agent = resource_agent
        self.db = db

    async def dispatch_incident(
        self,
        incident: VerifiedIncident,
        priority: str | None = None,
    ) -> DispatchResult:
        """
        Run the LangGraph dispatch pipeline for *incident*.

        Parameters
        ----------
        incident : verified, assessed incident to dispatch for.
        priority : optional override; defaults to incident.severity.

        Returns
        -------
        DispatchResult with assignments, ETA, solver status, and dispatch status.
        """
        p = priority or incident.severity or Priority.P4

        initial_state: DispatchState = {
            "incident": incident,
            "priority": p,
            "resource_agent": self.resource_agent,
            "db": self.db,
        }

        final_state: DispatchState = await _dispatch_graph.ainvoke(initial_state)
        return final_state["result"]

    async def optimize(
        self,
        incidents: list[VerifiedIncident],
        responders: list[Responder],
    ) -> list[Assignment]:
        """
        Batch multi-incident dispatch.

        Runs the full LangGraph pipeline for each incident independently and
        returns a flat list of all produced Assignments.

        Note: each incident dispatches against the full *responders* pool.
        Responder deconfliction (preventing double-assignment) is handled by
        the ResourceAgent's status-update step inside ``commit_assignments``,
        which marks each assigned responder as "assigned" before the next
        incident is processed.
        """
        all_assignments: list[Assignment] = []
        for incident in incidents:
            result = await self.dispatch_incident(incident)
            all_assignments.extend(result.assignments)
        return all_assignments

    def _build_cost_matrix(
        self,
        incidents: list[VerifiedIncident],
        responders: list[Responder],
    ) -> list[list[float]]:
        """
        Utility: return len(incidents) × len(responders) cost matrix.

        cost[i][j] = ETA[i][j] / priority_weight[i]
                     + (1 - cap_score[i][j]) * MISMATCH_PENALTY_S

        Used by tests and can be used for pre-analysis before invoking the graph.
        """
        matrix: list[list[float]] = []
        for incident in incidents:
            pw = _PRIORITY_WEIGHTS.get(incident.severity or Priority.P4, 1.0)
            req = _required_caps(incident)
            row: list[float] = [
                (_eta_seconds(incident, r) / pw) + (1.0 - _cap_score(r, req)) * _MISMATCH_PENALTY_S
                for r in responders
            ]
            matrix.append(row)
        return matrix


# ── Singleton factory ─────────────────────────────────────────────────────────


def get_orchestrator_agent(db: AsyncSession) -> OrchestratorAgent:
    """Return an OrchestratorAgent bound to *db* (a per-request AsyncSession)."""
    return OrchestratorAgent(get_resource_agent(db), db)
