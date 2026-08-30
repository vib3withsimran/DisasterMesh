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

// Dynamic import for MapView (uses mapbox-gl which needs window)
const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

export default function DashboardPage() {
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null);
  const [responders, setResponders] = useState<Responder[]>([]);

  const { incidents, isLoading } = useIncidents(5_000);

  const handleWsEvent = useCallback((event: WsEvent) => {
    // Could trigger SWR revalidation here if needed
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
    <div className="h-screen flex flex-col">
      {/* Status bar */}
      <StatusSummary incidents={incidents} responders={responders} />

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
        </div>

        {/* Right: Sidebar */}
        <div className="w-[380px] flex-shrink-0 border-l border-gray-800 flex flex-col min-h-0">
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
          <div className="h-[220px] flex-shrink-0">
            <EventFeed events={events} connected={connected} />
          </div>
        </div>
      </div>
    </div>
  );
}
