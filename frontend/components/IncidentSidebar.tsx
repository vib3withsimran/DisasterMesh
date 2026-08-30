"use client";

import type { Incident } from "@/lib/api";
import IncidentCard from "./IncidentCard";

const PRIORITY_BADGE: Record<string, string> = {
  P1: "bg-red-500",
  P2: "bg-orange-500",
  P3: "bg-yellow-400",
  P4: "bg-gray-500",
};

interface IncidentSidebarProps {
  incidents: Incident[];
  selectedClusterId: string | null;
  onSelect: (clusterId: string) => void;
  isLoading: boolean;
}

export default function IncidentSidebar({
  incidents,
  selectedClusterId,
  onSelect,
  isLoading,
}: IncidentSidebarProps) {
  const selected = incidents.find((i) => i.cluster_id === selectedClusterId);

  // Sort by severity (P1 first) then by confidence descending
  const sorted = [...incidents].sort((a, b) => {
    const pOrder: Record<string, number> = { P1: 0, P2: 1, P3: 2, P4: 3 };
    const pa = pOrder[a.severity] ?? 4;
    const pb = pOrder[b.severity] ?? 4;
    if (pa !== pb) return pa - pb;
    return b.confidence - a.confidence;
  });

  return (
    <div className="flex flex-col h-full">
      {/* Selected incident detail */}
      {selected ? (
        <div className="border-b border-gray-700 max-h-[55%] overflow-y-auto">
          <IncidentCard incident={selected} />
        </div>
      ) : (
        <div className="p-4 text-center text-gray-500 text-sm border-b border-gray-700">
          <p className="text-2xl mb-1">👈</p>
          <p>Select an incident from the list</p>
        </div>
      )}

      {/* Incident list */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-2 text-xs text-gray-400 font-medium sticky top-0 bg-gray-900/95 backdrop-blur border-b border-gray-800">
          {isLoading ? "Loading..." : `${incidents.length} incidents`}
        </div>

        {sorted.length === 0 && !isLoading && (
          <div className="p-6 text-center text-gray-500 text-sm">
            <p className="text-3xl mb-2">📭</p>
            <p>No incidents found</p>
            <p className="text-xs mt-1">Submit a report to get started</p>
          </div>
        )}

        {sorted.map((inc) => {
          const isSelected = inc.cluster_id === selectedClusterId;
          return (
            <button
              key={inc.cluster_id}
              onClick={() => onSelect(inc.cluster_id)}
              className={`w-full text-left px-3 py-2 border-b border-gray-800 transition-colors
                ${isSelected ? "bg-blue-900/30 border-l-2 border-l-blue-500" : "hover:bg-gray-800/50"}
              `}
            >
              <div className="flex items-center gap-2">
                <span
                  className={`w-2 h-2 rounded-full flex-shrink-0 ${PRIORITY_BADGE[inc.severity]}`}
                />
                <span className="text-xs font-medium text-gray-300 truncate">
                  {inc.severity} · {inc.status}
                </span>
                <span className="text-[10px] text-gray-500 ml-auto flex-shrink-0">
                  {(inc.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <p className="text-[11px] text-gray-500 truncate mt-0.5 font-mono">
                {inc.cluster_id.slice(0, 28)}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
