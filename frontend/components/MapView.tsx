"use client";

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Incident, Responder } from "@/lib/api";

const PRIORITY_COLORS: Record<string, string> = {
  P1: "#ef4444",
  P2: "#f97316",
  P3: "#eab308",
  P4: "#64748b",
};

const STATUS_COLORS: Record<string, string> = {
  REPORTED: "#3b82f6",
  VERIFIED: "#a855f7",
  ASSIGNED: "#f97316",
  EN_ROUTE: "#eab308",
  ON_SCENE: "#22c55e",
  RESOLVED: "#64748b",
};

function createIncidentMarker(el: HTMLElement, severity: string, status: string) {
  const color = PRIORITY_COLORS[severity] || "#64748b";
  const pulse = status !== "RESOLVED";
  el.className = "incident-marker";
  el.innerHTML = `
    <div style="position:relative;width:20px;height:20px;">
      ${pulse ? `<div style="position:absolute;inset:-4px;border-radius:50%;background:${color};opacity:0.3;animation:pulse 2s infinite;"></div>` : ""}
      <div style="width:20px;height:20px;border-radius:50%;background:${color};border:2px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.4);"></div>
    </div>
  `;
  return el;
}

function createResponderMarker(el: HTMLElement) {
  el.className = "responder-marker";
  el.innerHTML = `
    <div style="width:14px;height:14px;border-radius:3px;background:#3b82f6;border:2px solid white;transform:rotate(45deg);box-shadow:0 2px 6px rgba(0,0,0,0.3);"></div>
  `;
  return el;
}

interface MapViewProps {
  incidents: Incident[];
  responders: Responder[];
  selectedClusterId: string | null;
  onSelectIncident: (clusterId: string) => void;
}

export default function MapView({
  incidents,
  responders,
  selectedClusterId,
  onSelectIncident,
}: MapViewProps) {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<Map<string, maplibregl.Marker>>(new Map());

  // Initialize map
  useEffect(() => {
    if (!mapContainer.current || map.current) return;

    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "",
          },
        },
        layers: [
          {
            id: "osm",
            type: "raster",
            source: "osm",
            paint: {
              "raster-brightness-max": 0.15,
              "raster-saturation": -1,
              "raster-contrast": 0.1,
            },
          },
        ],
      },
      center: [85.324, 27.7172],
      zoom: 10,
      pitch: 0,
      attributionControl: false,
    });

    map.current.addControl(new maplibregl.NavigationControl(), "top-right");

    // Add pulse animation CSS
    const style = document.createElement("style");
    style.textContent = `
      @keyframes pulse {
        0%, 100% { transform: scale(1); opacity: 0.3; }
        50% { transform: scale(1.5); opacity: 0; }
      }
    `;
    document.head.appendChild(style);

    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []);

  // Update incident markers
  useEffect(() => {
    if (!map.current) return;

    const seen = new Set<string>();

    incidents.forEach((inc) => {
      seen.add(inc.cluster_id);
      const isSelected = inc.cluster_id === selectedClusterId;

      if (markersRef.current.has(inc.cluster_id)) {
        const existing = markersRef.current.get(inc.cluster_id);
        if (existing) {
          const el = existing.getElement();
          if (isSelected) {
            el.style.zIndex = "100";
            el.style.transform = "scale(1.3)";
          } else {
            el.style.zIndex = "1";
            el.style.transform = "scale(1)";
          }
        }
        return;
      }

      const el = document.createElement("div");
      createIncidentMarker(el, inc.severity, inc.status);
      if (isSelected) {
        el.style.zIndex = "100";
        el.style.transform = "scale(1.3)";
      }

      const popup = new maplibregl.Popup({
        offset: 15,
        closeButton: false,
        closeOnClick: false,
      }).setHTML(`
        <div style="padding:4px 0;font-family:Inter,sans-serif;">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
            <div style="width:8px;height:8px;border-radius:50%;background:${PRIORITY_COLORS[inc.severity] || "#64748b"};"></div>
            <strong style="font-size:12px;">${inc.severity}</strong>
            <span style="font-size:11px;color:#94a3b8;">${inc.status}</span>
          </div>
          <div style="font-size:10px;color:#64748b;">
            Confidence: ${(inc.confidence * 100).toFixed(0)}%
          </div>
          <div style="font-size:10px;color:#475569;font-family:monospace;margin-top:2px;">
            ${(inc.cluster_id ?? "--").slice(0, 16)}...
          </div>
        </div>
      `);

      el.addEventListener("mouseenter", () => marker.setPopup(popup));
      el.addEventListener("mouseleave", () => marker.setPopup(undefined));
      el.addEventListener("click", () => onSelectIncident(inc.cluster_id));

      const currentMap = map.current;
      if (!currentMap) return;
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([inc.lon, inc.lat])
        .addTo(currentMap);

      markersRef.current.set(inc.cluster_id, marker);
    });

    // Remove stale markers
    markersRef.current.forEach((marker, id) => {
      if (!seen.has(id)) {
        marker.remove();
        markersRef.current.delete(id);
      }
    });
  }, [incidents, selectedClusterId, onSelectIncident]);

  // Update responder markers
  useEffect(() => {
    if (!map.current) return;

    // Remove old responder markers
    markersRef.current.forEach((marker, id) => {
      if (id.startsWith("resp-")) {
        marker.remove();
        markersRef.current.delete(id);
      }
    });

    responders.forEach((r) => {
      const el = document.createElement("div");
      createResponderMarker(el);

      const popup = new maplibregl.Popup({
        offset: 10,
        closeButton: false,
        closeOnClick: false,
      }).setHTML(`
        <div style="padding:4px 0;font-family:Inter,sans-serif;">
          <div style="font-size:11px;font-weight:600;margin-bottom:2px;">${r.name}</div>
          <div style="font-size:10px;color:#94a3b8;">
            ${r.team_type} | ${r.team_size} members | ${r.status}
          </div>
        </div>
      `);

      el.addEventListener("mouseenter", () => marker.setPopup(popup));
      el.addEventListener("mouseleave", () => marker.setPopup(undefined));

      const currentMap = map.current;
      if (!currentMap) return;
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([r.lon, r.lat])
        .addTo(currentMap);

      markersRef.current.set(`resp-${r.id}`, marker);
    });
  }, [responders]);

  // Fly to selected incident
  useEffect(() => {
    if (!map.current || !selectedClusterId) return;
    const inc = incidents.find((i) => i.cluster_id === selectedClusterId);
    if (inc) {
      map.current.flyTo({ center: [inc.lon, inc.lat], zoom: 13, duration: 800 });
    }
  }, [selectedClusterId, incidents]);

  return (
    <div ref={mapContainer} className="w-full h-full" style={{ background: "var(--bg-primary)" }} />
  );
}
