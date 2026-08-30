"use client";

import type { Incident } from "@/lib/api";
import IncidentCard from "./IncidentCard";

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
    <div className="flex flex-col h-full" style={{ background: "var(--bg-secondary)" }}>
      {/* Selected incident detail */}
      {selected ? (
        <div className="border-b" style={{ borderColor: "var(--border-subtle)" }}>
          <IncidentCard incident={selected} />
        </div>
      ) : (
        <div className="p-5 text-center border-b" style={{ borderColor: "var(--border-subtle)" }}>
          <div className="w-10 h-10 mx-auto mb-2 rounded-xl bg-slate-800/50 border border-slate-700/50 flex items-center justify-center">
            <svg className="w-5 h-5 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M15 15l-2 5L9 9l11 4-5 2zm0 0l5 5M7.188 2.239l.777 2.897M5.136 7.965l-2.898-.777M13.95 4.05l-2.122 2.122m-5.657 5.656l-2.12 2.122" />
            </svg>
          </div>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>Select an incident</p>
        </div>
      )}

      {/* Incident list */}
      <div className="flex-1 overflow-y-auto">
        <div className="px-3 py-2 text-[10px] font-medium tracking-wider uppercase sticky top-0 backdrop-blur border-b" style={{ background: "var(--bg-secondary)", color: "var(--text-muted)", borderColor: "var(--border-subtle)" }}>
          {isLoading ? "Loading..." : `${incidents.length} incidents`}
        </div>

        {sorted.length === 0 && !isLoading && (
          <div className="p-8 text-center">
            <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-slate-800/50 border border-slate-700/50 flex items-center justify-center">
              <svg className="w-6 h-6 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
              </svg>
            </div>
            <p className="text-xs font-medium" style={{ color: "var(--text-secondary)" }}>No incidents</p>
            <p className="text-[10px] mt-1" style={{ color: "var(--text-muted)" }}>Reports will appear here</p>
          </div>
        )}

        {sorted.map((inc) => {
          const isSelected = inc.cluster_id === selectedClusterId;
          const style = PRIORITY_STYLES[inc.severity] || PRIORITY_STYLES.P4;
          const dot = STATUS_DOT[inc.status] || "bg-slate-400";

          return (
            <button
              key={inc.cluster_id}
              onClick={() => onSelect(inc.cluster_id)}
              className="w-full text-left px-3 py-2.5 border-b transition-all duration-150"
              style={{
                borderColor: "var(--border-subtle)",
                background: isSelected ? "var(--bg-elevated)" : "transparent",
                borderLeft: isSelected ? "2px solid var(--accent-blue)" : "2px solid transparent",
              }}
            >
              <div className="flex items-center gap-2">
                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dot}`} />
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border ${style.bg} ${style.border} ${style.text}`}>
                  {inc.severity}
                </span>
                <span className="text-[11px] font-medium" style={{ color: "var(--text-secondary)" }}>
                  {inc.status}
                </span>
                <span className="text-[10px] ml-auto flex-shrink-0 font-mono" style={{ color: "var(--text-muted)" }}>
                  {(inc.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <p className="text-[10px] truncate mt-1 font-mono" style={{ color: "var(--text-muted)" }}>
                {inc.cluster_id?.slice(0, 24) ?? "--"}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
