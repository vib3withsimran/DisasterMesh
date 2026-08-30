"use client";

import { useCallback, useState } from "react";
import dynamic from "next/dynamic";
import { useIncidents } from "@/hooks/useIncidents";
import { useWebSocket } from "@/hooks/useWebSocket";
import IncidentSidebar from "@/components/IncidentSidebar";
import EventFeed from "@/components/EventFeed";
import StatusSummary from "@/components/StatusSummary";
import type { WsEvent } from "@/lib/api";
import { fetchResponders, type Responder } from "@/lib/api";
import { useEffect } from "react";

// Dynamic import for MapView (uses maplibre-gl which needs window)
const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

export default function DashboardPage() {
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null);
  const [responders, setResponders] = useState<Responder[]>([]);

  const { incidents, isLoading, error } = useIncidents(5_000);

  const handleWsEvent = useCallback((event: WsEvent) => {
    console.log("[WS Event]", event);
  }, []);

  const { connected, events } = useWebSocket(handleWsEvent);

  // Load responders
  useEffect(() => {
    const load = async () => {
      try {
        const resp = await fetchResponders();
        setResponders(resp);
      } catch {
        console.warn("Failed to load responders");
      }
    };
    load();
    const interval = setInterval(load, 10_000);
    return () => clearInterval(interval);
  }, []);

  const handleSelectIncident = useCallback((clusterId: string) => {
    setSelectedClusterId(clusterId);
  }, []);

  return (
    <div className="h-screen flex flex-col" style={{ background: "var(--bg-primary)" }}>
      {/* Status bar */}
      <StatusSummary incidents={incidents} responders={responders} />

      {/* Error banner */}
      {error && (
        <div className="px-4 py-1.5 text-[10px] border-b" style={{ background: "rgba(239,68,68,0.1)", borderColor: "rgba(239,68,68,0.2)", color: "#fca5a5" }}>
          API connection error -- check if backend is running on localhost:8000
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 flex min-h-0">
        {/* Left: Map */}
        <div className="flex-1 relative">
          <MapView
            incidents={incidents}
            responders={responders}
            selectedClusterId={selectedClusterId}
            onSelectIncident={handleSelectIncident}
          />

          {/* Loading overlay */}
          {isLoading && incidents.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center" style={{ background: "rgba(10,14,23,0.8)" }}>
              <div className="text-center">
                <div className="w-8 h-8 mx-auto mb-3 rounded-lg border-2 border-blue-500/30 border-t-blue-500 animate-spin" />
                <p className="text-xs" style={{ color: "var(--text-muted)" }}>Loading incidents...</p>
              </div>
            </div>
          )}
        </div>

        {/* Right: Sidebar */}
        <div className="w-[380px] flex-shrink-0 border-l flex flex-col min-h-0" style={{ borderColor: "var(--border-subtle)", background: "var(--bg-secondary)" }}>
          {/* Incident list + detail (top 70%) */}
          <div className="flex-1 min-h-0">
            <IncidentSidebar
              incidents={incidents}
              selectedClusterId={selectedClusterId}
              onSelect={handleSelectIncident}
              isLoading={isLoading}
            />
          </div>

          {/* Event feed (bottom 30%) */}
          <div className="h-[220px] flex-shrink-0 border-t" style={{ borderColor: "var(--border-subtle)" }}>
            <EventFeed events={events} connected={connected} />
          </div>
        </div>
      </div>
    </div>
  );
}
