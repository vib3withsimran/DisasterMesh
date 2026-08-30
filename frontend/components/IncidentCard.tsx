"use client";

import type { Incident } from "@/lib/api";
import { useState } from "react";
import { dispatchIncident, fetchSummary, type DispatchResult, type SituationalSummary } from "@/lib/api";

const PRIORITY_STYLES: Record<string, { bg: string; border: string; text: string }> = {
  P1: { bg: "bg-red-500/10", border: "border-red-500/30", text: "text-red-400" },
  P2: { bg: "bg-orange-500/10", border: "border-orange-500/30", text: "text-orange-400" },
  P3: { bg: "bg-yellow-500/10", border: "border-yellow-500/30", text: "text-yellow-400" },
  P4: { bg: "bg-slate-500/10", border: "border-slate-500/30", text: "text-slate-400" },
};

const STATUS_DOT: Record<string, string> = {
  REPORTED: "bg-blue-400",
  VERIFIED: "bg-purple-400",
  ASSIGNED: "bg-orange-400",
  EN_ROUTE: "bg-yellow-400",
  ON_SCENE: "bg-green-400",
  RESOLVED: "bg-slate-400",
};

const SOURCE_LABELS: Record<string, string> = {
  sms: "SMS",
  whatsapp: "WhatsApp",
  web_form: "Web",
  tweet: "Twitter",
  satellite: "Satellite",
  iot_sensor: "IoT",
  news: "News",
};

interface IncidentCardProps {
  incident: Incident;
  onDispatch?: (result: DispatchResult) => void;
}

export default function IncidentCard({ incident, onDispatch }: IncidentCardProps) {
  const [dispatching, setDispatching] = useState(false);
  const [dispatchResult, setDispatchResult] = useState<DispatchResult | null>(null);
  const [summary, setSummary] = useState<SituationalSummary | null>(null);
  const [loadingSummary, setLoadingSummary] = useState(false);

  const handleDispatch = async () => {
    setDispatching(true);
    try {
      const result = await dispatchIncident(incident.cluster_id);
      setDispatchResult(result);
      onDispatch?.(result);
    } catch (err) {
      console.error("Dispatch failed:", err);
    } finally {
      setDispatching(false);
    }
  };

  const handleSummary = async () => {
    setLoadingSummary(true);
    try {
      const s = await fetchSummary(incident.cluster_id);
      setSummary(s);
    } catch (err) {
      console.error("Summary failed:", err);
    } finally {
      setLoadingSummary(false);
    }
  };

  const needs = incident.needs;
  const activeNeeds = Object.entries(needs)
    .filter(([, v]) => v)
    .map(([k]) => k);

  const pStyle = PRIORITY_STYLES[incident.severity] || PRIORITY_STYLES.P4;
  const dot = STATUS_DOT[incident.status] || "bg-slate-400";

  return (
    <div className="p-4 space-y-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[10px] font-mono truncate" style={{ color: "var(--text-muted)" }}>
            {incident.cluster_id}
          </p>
          <p className="text-[11px] mt-1" style={{ color: "var(--text-secondary)" }}>
            {new Date(incident.timestamp).toLocaleString()}
          </p>
        </div>
        <div className="flex gap-1.5 flex-shrink-0">
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${pStyle.bg} ${pStyle.border} ${pStyle.text}`}>
            {incident.severity}
          </span>
          <span className="flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded bg-slate-800/50 border border-slate-700/50" style={{ color: "var(--text-secondary)" }}>
            <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
            {incident.status}
          </span>
        </div>
      </div>

      {/* Confidence bar */}
      <div>
        <div className="flex justify-between text-[10px] mb-1" style={{ color: "var(--text-muted)" }}>
          <span>Confidence</span>
          <span className="font-mono">{(incident.confidence * 100).toFixed(0)}%</span>
        </div>
        <div className="w-full rounded-full h-1" style={{ background: "var(--bg-elevated)" }}>
          <div
            className="h-1 rounded-full transition-all duration-500"
            style={{
              width: `${incident.confidence * 100}%`,
              background: incident.confidence > 0.7 ? "var(--accent-green)" : incident.confidence > 0.4 ? "var(--accent-yellow)" : "var(--accent-red)",
            }}
          />
        </div>
      </div>

      {/* Location */}
      <div className="flex items-center gap-2 text-[11px]" style={{ color: "var(--text-secondary)" }}>
        <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
          <circle cx="12" cy="10" r="3" />
        </svg>
        <span className="font-mono">{incident.lat.toFixed(4)}, {incident.lon.toFixed(4)}</span>
      </div>

      {/* Sources */}
      <div className="flex flex-wrap gap-1">
        {incident.source_provenance.map((src) => (
          <span
            key={src}
            className="text-[10px] px-1.5 py-0.5 rounded border bg-slate-800/50"
            style={{ color: "var(--text-muted)", borderColor: "var(--border-subtle)" }}
          >
            {SOURCE_LABELS[src] ?? src}
          </span>
        ))}
      </div>

      {/* Needs */}
      {activeNeeds.length > 0 && (
        <div>
          <p className="text-[10px] font-medium mb-1 uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Needs</p>
          <div className="flex flex-wrap gap-1">
            {activeNeeds.map((need) => (
              <span
                key={need}
                className="text-[10px] px-1.5 py-0.5 rounded border bg-red-500/10 text-red-400 border-red-500/30"
              >
                {need}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={handleDispatch}
          disabled={dispatching}
          className="flex-1 flex items-center justify-center gap-1.5 text-[11px] font-medium py-2 px-3 rounded-lg transition-all duration-150 disabled:opacity-50"
          style={{
            background: dispatching ? "var(--bg-elevated)" : "var(--accent-blue)",
            color: "white",
          }}
        >
          {dispatching ? (
            <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 12a9 9 0 11-6.219-8.56" />
            </svg>
          ) : (
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="1" y="3" width="15" height="13" />
              <polygon points="16 8 20 8 23 11 23 16 16 16 16 8" />
              <circle cx="5.5" cy="18.5" r="2.5" />
              <circle cx="18.5" cy="18.5" r="2.5" />
            </svg>
          )}
          {dispatching ? "Dispatching..." : "Dispatch"}
        </button>
        <button
          onClick={handleSummary}
          disabled={loadingSummary}
          className="flex items-center justify-center text-[11px] py-2 px-3 rounded-lg transition-all duration-150 border disabled:opacity-50"
          style={{ borderColor: "var(--border-subtle)", color: "var(--text-secondary)" }}
        >
          {loadingSummary ? (
            <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 12a9 9 0 11-6.219-8.56" />
            </svg>
          ) : (
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
              <polyline points="14,2 14,8 20,8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <polyline points="10,9 9,9 8,9" />
            </svg>
          )}
        </button>
      </div>

      {/* Dispatch result */}
      {dispatchResult && (
        <div className="rounded-lg p-3 text-[11px] space-y-1.5" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}>
          <p className="font-medium text-green-400">
            Dispatched {dispatchResult.assignments.length} responder(s)
          </p>
          <p style={{ color: "var(--text-muted)" }}>
            Solver: {dispatchResult.solver_status} | Min ETA:{" "}
            {Math.round(dispatchResult.min_eta_seconds / 60)} min
          </p>
          {dispatchResult.assignments.map((a) => (
            <p key={a.id} className="font-mono" style={{ color: "var(--text-muted)" }}>
              {a.responder_id.slice(0, 12)}... Match:{" "}
              {(a.capability_match_score * 100).toFixed(0)}%
            </p>
          ))}
        </div>
      )}

      {/* Summary */}
      {summary && (
        <div className="rounded-lg p-3 text-[11px] space-y-2" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}>
          <p className="font-medium" style={{ color: "var(--text-secondary)" }}>Situational Summary</p>
          <pre className="whitespace-pre-wrap text-[10px] leading-relaxed font-mono" style={{ color: "var(--text-muted)" }}>
            {summary.human_summary}
          </pre>
        </div>
      )}
    </div>
  );
}
