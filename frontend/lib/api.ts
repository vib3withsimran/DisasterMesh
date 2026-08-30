/**
 * DisasterMesh API client.
 *
 * All fetches go through this module so the base URL is configurable
 * via NEXT_PUBLIC_API_URL (defaults to localhost:8000).
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────

export type SourceType =
  | "sms"
  | "whatsapp"
  | "web_form"
  | "tweet"
  | "satellite"
  | "iot_sensor"
  | "news";

export type IncidentStatus =
  | "REPORTED"
  | "VERIFIED"
  | "ASSIGNED"
  | "EN_ROUTE"
  | "ON_SCENE"
  | "RESOLVED";

export type Priority = "P1" | "P2" | "P3" | "P4";

export type ResponderStatus = "available" | "assigned" | "en_route" | "on_scene";

export interface NeedsProfile {
  medical: boolean;
  shelter: boolean;
  evacuation: boolean;
  rescue: boolean;
  water: boolean;
  food: boolean;
}

export interface Incident {
  cluster_id: string;
  source_provenance: SourceType[];
  lat: number;
  lon: number;
  timestamp: string;
  confidence: number;
  severity: Priority;
  needs: NeedsProfile;
  media_urls: string[];
  status: IncidentStatus;
}

export interface Responder {
  id: string;
  name: string;
  team_type: string;
  capabilities: string[];
  team_size: number;
  capacity: number;
  lat: number;
  lon: number;
  available: boolean;
  status: ResponderStatus;
  assigned_incident_id: string | null;
  eta_minutes: number | null;
}

export interface Assignment {
  id: string;
  cluster_id: string;
  responder_id: string;
  eta_seconds: number;
  capability_match_score: number;
  optimization_method: string;
  assigned_at: string;
}

export interface DispatchResult {
  cluster_id: string;
  status: string;
  assignments: Assignment[];
  min_eta_seconds: number;
  total_capacity: number;
  solver_status: string;
  reason: string;
}

export interface SituationalSummary {
  cluster_id: string;
  status: IncidentStatus;
  severity: Priority;
  confidence: number;
  lat: number;
  lon: number;
  timestamp: string;
  needs: NeedsProfile;
  source_provenance: SourceType[];
  assigned_responders: {
    responder_id: string;
    responder_name: string;
    eta_seconds: number;
    capability_match_score: number;
  }[];
  generated_at: string;
  human_summary: string;
}

export interface WsEvent {
  event: string;
  cluster_id: string;
  old_status?: string;
  new_status?: string;
  timestamp: string;
}

// ── Fetch helpers ──────────────────────────────────────────────────────────

async function apiGet<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(path, API_BASE);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, String(v)));
  }
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

// ── API methods ────────────────────────────────────────────────────────────

/** Fetch all incidents near a location (default: Kathmandu, Nepal — 500 km radius). */
export async function fetchIncidents(
  lat = 27.7172,
  lon = 85.324,
  radius = 500_000,
  limit = 100,
): Promise<{ incidents: Incident[]; count: number }> {
  return apiGet("/incidents/", { lat, lon, radius, limit });
}

/** Fetch all responders. */
export async function fetchResponders(status?: string): Promise<Responder[]> {
  const params: Record<string, string> = {};
  if (status) params.status = status;
  return apiGet("/responders", params);
}

/** Dispatch responders to an incident cluster. */
export async function dispatchIncident(clusterId: string): Promise<DispatchResult> {
  return apiPost(`/dispatch/${clusterId}`);
}

/** Fetch situational summary for an incident. */
export async function fetchSummary(clusterId: string): Promise<SituationalSummary> {
  return apiGet(`/incidents/${clusterId}/summary`);
}

/** Health check. */
export async function healthCheck(): Promise<{ status: string; version: string }> {
  return apiGet("/health");
}
