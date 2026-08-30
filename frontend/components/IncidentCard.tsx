"use client";

import type { Incident } from "@/lib/api";
import { useState } from "react";
import { dispatchIncident, fetchSummary, type DispatchResult, type SituationalSummary } from "@/lib/api";

const PRIORITY_CLASSES: Record<string, string> = {
  P1: "bg-red-500 text-white",
  P2: "bg-orange-500 text-white",
  P3: "bg-yellow-400 text-gray-900",
  P4: "bg-gray-500 text-white",
};

const STATUS_CLASSES: Record<string, string> = {
  REPORTED: "bg-blue-100 text-blue-800",
  VERIFIED: "bg-purple-100 text-purple-800",
  ASSIGNED: "bg-orange-100 text-orange-800",
  EN_ROUTE: "bg-yellow-100 text-yellow-800",
  ON_SCENE: "bg-green-100 text-green-800",
  RESOLVED: "bg-gray-100 text-gray-800",
};

const SOURCE_ICONS: Record<string, string> = {
  sms: "📱",
  whatsapp: "💬",
  web_form: "🌐",
  tweet: "🐦",
  satellite: "🛰️",
  iot_sensor: "📡",
  news: "📰",
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

  return (
    <div className="p-4 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs text-gray-400 font-mono truncate max-w-[200px]">
            {incident.cluster_id}
          </p>
          <p className="text-sm text-gray-300 mt-1">
            {new Date(incident.timestamp).toLocaleString()}
          </p>
        </div>
        <div className="flex gap-2">
          <span
            className={`text-xs font-bold px-2 py-0.5 rounded ${PRIORITY_CLASSES[incident.severity]}`}
          >
            {incident.severity}
          </span>
          <span
            className={`text-xs font-medium px-2 py-0.5 rounded ${STATUS_CLASSES[incident.status]}`}
          >
            {incident.status}
          </span>
        </div>
      </div>

      {/* Confidence bar */}
      <div>
        <div className="flex justify-between text-xs text-gray-400 mb-1">
          <span>Confidence</span>
          <span>{(incident.confidence * 100).toFixed(0)}%</span>
        </div>
        <div className="w-full bg-gray-700 rounded-full h-1.5">
          <div
            className="bg-green-500 h-1.5 rounded-full transition-all"
            style={{ width: `${incident.confidence * 100}%` }}
          />
        </div>
      </div>

      {/* Location */}
      <div className="flex items-center gap-2 text-sm text-gray-300">
        <span>📍</span>
        <span>
          {incident.lat.toFixed(4)}, {incident.lon.toFixed(4)}
        </span>
      </div>

      {/* Sources */}
      <div className="flex flex-wrap gap-1.5">
        {incident.source_provenance.map((src) => (
          <span
            key={src}
            className="text-xs bg-gray-700 text-gray-300 px-2 py-0.5 rounded"
          >
            {SOURCE_ICONS[src] ?? ""} {src}
          </span>
        ))}
      </div>

      {/* Needs */}
      {activeNeeds.length > 0 && (
        <div>
          <p className="text-xs text-gray-400 mb-1">Needs</p>
          <div className="flex flex-wrap gap-1.5">
            {activeNeeds.map((need) => (
              <span
                key={need}
                className="text-xs bg-red-900/50 text-red-300 px-2 py-0.5 rounded border border-red-800"
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
          className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white text-sm font-medium py-2 px-3 rounded transition-colors"
        >
          {dispatching ? "⏳ Dispatching..." : "🚒 Dispatch"}
        </button>
        <button
          onClick={handleSummary}
          disabled={loadingSummary}
          className="bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 text-gray-300 text-sm py-2 px-3 rounded transition-colors"
        >
          {loadingSummary ? "⏳" : "📋"}
        </button>
      </div>

      {/* Dispatch result */}
      {dispatchResult && (
        <div className="bg-gray-800 rounded p-3 text-xs space-y-1">
          <p className="text-green-400 font-medium">
            ✓ Dispatched {dispatchResult.assignments.length} responder(s)
          </p>
          <p className="text-gray-400">
            Solver: {dispatchResult.solver_status} | Min ETA:{" "}
            {Math.round(dispatchResult.min_eta_seconds / 60)} min
          </p>
          {dispatchResult.assignments.map((a) => (
            <p key={a.id} className="text-gray-500">
              🚒 {a.responder_id.slice(0, 12)}… Match:{" "}
              {(a.capability_match_score * 100).toFixed(0)}%
            </p>
          ))}
        </div>
      )}

      {/* Summary */}
      {summary && (
        <div className="bg-gray-800 rounded p-3 text-xs space-y-2">
          <p className="text-gray-300 font-medium">📋 Situational Summary</p>
          <pre className="text-gray-400 whitespace-pre-wrap text-[11px] leading-relaxed">
            {summary.human_summary}
          </pre>
        </div>
      )}
    </div>
  );
}
