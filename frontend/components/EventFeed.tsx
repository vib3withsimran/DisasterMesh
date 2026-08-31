"use client";

import type { WsEvent } from "@/lib/api";

const EVENT_ICONS: Record<string, string> = {
  lifecycle_transition: "lifecycle",
  dispatch_assigned: "dispatch",
  incident_verified: "verified",
  incident_reported: "reported",
};

const STATUS_COLORS: Record<string, string> = {
  REPORTED: "text-blue-400",
  VERIFIED: "text-purple-400",
  ASSIGNED: "text-orange-400",
  EN_ROUTE: "text-yellow-400",
  ON_SCENE: "text-green-400",
  RESOLVED: "text-slate-400",
};

interface EventFeedProps {
  events: WsEvent[];
  connected: boolean;
}

export default function EventFeed({ events, connected }: EventFeedProps) {
  return (
    <div className="h-full flex flex-col" style={{ background: "var(--bg-secondary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: "var(--border-subtle)" }}>
        <span className="text-[10px] font-medium tracking-wider uppercase" style={{ color: "var(--text-muted)" }}>
          Live Events
        </span>
        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-green-400" : "bg-red-400"}`} />
          <span className="text-[10px]" style={{ color: connected ? "var(--accent-green)" : "var(--accent-red)" }}>
            {connected ? "Connected" : "Disconnected"}
          </span>
        </div>
      </div>

      {/* Events list */}
      <div className="flex-1 overflow-y-auto px-3 py-1">
        {events.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>Waiting for events...</p>
          </div>
        ) : (
          <div className="space-y-0.5">
            {events.slice(-20).reverse().map((ev, i) => {
              const ts = new Date(ev.timestamp).toLocaleTimeString();
              const newColor = STATUS_COLORS[ev.new_status ?? ""] ?? "text-slate-400";

              return (
                <div key={i} className="flex items-start gap-2 py-1">
                  <span className="text-[9px] font-mono flex-shrink-0 pt-0.5" style={{ color: "var(--text-muted)" }}>
                    {ts}
                  </span>
                  <span className="text-[10px] font-mono" style={{ color: "var(--text-secondary)" }}>
                    {ev.cluster_id?.slice(0, 12) ?? "--"}
                  </span>
                  {ev.old_status && ev.new_status && (
                    <span className="text-[10px]">
                      <span style={{ color: "var(--text-muted)" }}>{ev.old_status}</span>
                      <span style={{ color: "var(--text-muted)" }}> &rarr; </span>
                      <span className={`font-medium ${newColor}`}>{ev.new_status}</span>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
