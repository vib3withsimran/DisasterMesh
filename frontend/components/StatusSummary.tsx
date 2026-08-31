"use client";

import type { Incident, Responder } from "@/lib/api";

interface StatusSummaryProps {
  incidents: Incident[];
  responders: Responder[];
}

// SVG Icon components
function AlertTriangle({ className = "w-3.5 h-3.5", style }: { className?: string; style?: React.CSSProperties }) {
  return (
    <svg className={className} style={style} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

function Users({ className = "w-3.5 h-3.5", style }: { className?: string; style?: React.CSSProperties }) {
  return (
    <svg className={className} style={style} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}

function Shield({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  );
}

function Truck({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1" y="3" width="15" height="13" />
      <polygon points="16 8 20 8 23 11 23 16 16 16 16 8" />
      <circle cx="5.5" cy="18.5" r="2.5" />
      <circle cx="18.5" cy="18.5" r="2.5" />
    </svg>
  );
}

function MapPin({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  );
}

export default function StatusSummary({ incidents, responders }: StatusSummaryProps) {
  const counts = { P1: 0, P2: 0, P3: 0, P4: 0 };
  incidents.forEach((inc) => {
    counts[inc.severity as keyof typeof counts]++;
  });

  const respCounts = { available: 0, assigned: 0, en_route: 0, on_scene: 0 };
  responders.forEach((r) => {
    respCounts[r.status as keyof typeof respCounts]++;
  });

  return (
    <div className="flex items-center gap-3 px-5 py-2.5 border-b border-slate-800/80" style={{ background: "var(--bg-secondary)" }}>
      {/* Logo */}
      <div className="flex items-center gap-2.5 mr-1">
        <div className="w-7 h-7 rounded-lg bg-blue-600/20 border border-blue-500/30 flex items-center justify-center">
          <Shield className="w-4 h-4 text-blue-400" />
        </div>
        <span className="font-semibold text-sm tracking-tight" style={{ color: "var(--text-primary)" }}>
          DisasterMesh
        </span>
      </div>

      <div className="h-5 w-px" style={{ background: "var(--border-subtle)" }} />

      {/* Incident counts */}
      <div className="flex items-center gap-2">
        <AlertTriangle className="w-3.5 h-3.5" style={{ color: "var(--text-muted)" }} />
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>Incidents</span>
        <div className="flex items-center gap-1">
          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-red-500/20 text-red-400 border border-red-500/30">
            P1 {counts.P1}
          </span>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-orange-500/20 text-orange-400 border border-orange-500/30">
            P2 {counts.P2}
          </span>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-yellow-500/20 text-yellow-400 border border-yellow-500/30">
            P3 {counts.P3}
          </span>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-500/20 text-slate-400 border border-slate-500/30">
            P4 {counts.P4}
          </span>
        </div>
      </div>

      <div className="h-5 w-px" style={{ background: "var(--border-subtle)" }} />

      {/* Responder counts */}
      <div className="flex items-center gap-2">
        <Users className="w-3.5 h-3.5" style={{ color: "var(--text-muted)" }} />
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>Responders</span>
        <div className="flex items-center gap-1.5">
          <span className="flex items-center gap-1 text-[10px] font-medium text-green-400">
            <Shield className="w-3 h-3" /> {respCounts.available}
          </span>
          <span className="flex items-center gap-1 text-[10px] font-medium text-orange-400">
            <Truck className="w-3 h-3" /> {respCounts.assigned}
          </span>
          <span className="flex items-center gap-1 text-[10px] font-medium text-yellow-400">
            <Truck className="w-3 h-3" /> {respCounts.en_route}
          </span>
          <span className="flex items-center gap-1 text-[10px] font-medium text-blue-400">
            <MapPin className="w-3 h-3" /> {respCounts.on_scene}
          </span>
        </div>
      </div>

      {/* Right side: total */}
      <div className="ml-auto flex items-center gap-2">
        <span className="text-[10px] px-2 py-0.5 rounded-full border" style={{ color: "var(--text-muted)", borderColor: "var(--border-subtle)" }}>
          {incidents.length} total
        </span>
      </div>
    </div>
  );
}
