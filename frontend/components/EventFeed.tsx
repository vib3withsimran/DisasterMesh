"use client";

import type { WsEvent } from "@/lib/api";

const EVENT_ICONS: Record<string, string> = {
  lifecycle_transition: "🔄",
  dispatch_assigned: "🚒",
  incident_verified: "🔍",
  incident_reported: "📩",
};

const STATUS_COLORS: Record<string, string> = {
  REPORTED: "text-blue-400",
  VERIFIED: "text-purple-400",
  ASSIGNED: "text-orange-400",
  EN_ROUTE: "text-yellow-400",
  ON_SCENE: "text-green-400",
  RESOLVED: "text-gray-400",
};

interface EventFeedProps {
  events: WsEvent[];
  connected: boolean;
}

export default function EventFeed({ events, connected }: EventFeedProps) {
  return (
    <div className="h-full flex flex-col bg-gray-950 border-t border-gray-800">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-gray-800">
        <span className="text-xs font-medium text-gray-400">📡 Live Events</span>
        <span
          className={`text-[10px] px-1.5 py-0.5 rounded ${
            connected ? "bg-green-900 text-green-400" : "bg-red-900 text-red-400"
          }`}
        >
          {connected ? "● Connected" : "○ Disconnected"}
        </span>
      </div>

      {/* Events */}
      <div className="flex-1 overflow-y-auto px-3 py-1 space-y-0.5 text-xs">
        {events.length === 0 && (
          <p className="text-gray-600 py-2 text-center">Waiting for events...</p>
        )}
        {events.map((ev, i) => {
          const icon = EVENT_ICONS[ev.event] ?? "📌";
          const newStatusColor = ev.new_status ? STATUS_COLORS[ev.new_status] ?? "" : "";
          const ts = new Date(ev.timestamp).toLocaleTimeString();

          return (
            <div key={i} className="flex items-start gap-1.5 py-0.5">
              <span className="flex-shrink-0">{icon}</span>
              <span className="text-gray-500 flex-shrink-0">{ts}</span>
              <span className="text-gray-300 truncate">
                <span className="font-mono text-gray-400">{ev.cluster_id.slice(0, 16)}…</span>
                {ev.old_status && ev.new_status && (
                  <>
                    : {ev.old_status} →{" "}
                    <span className={`font-medium ${newStatusColor}`}>{ev.new_status}</span>
                  </>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
