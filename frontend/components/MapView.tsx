"use client";

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Incident, Responder } from "@/lib/api";

// Priority → color mapping
const SEVERITY_COLORS: Record<string, string> = {
  P1: "#ef4444",
  P2: "#f97316",
  P3: "#eab308",
  P4: "#6b7280",
};

// Status → icon emoji
const STATUS_ICONS: Record<string, string> = {
  REPORTED: "📩",
  VERIFIED: "🔍",
  ASSIGNED: "🚒",
  EN_ROUTE: "⏱️",
  ON_SCENE: "👨‍🚒",
  RESOLVED: "✅",
};

// Free tile style — no API key needed
const FREE_STYLE_URL =
  "https://demotiles.maplibre.org/style.json";

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
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<Map<string, maplibregl.Marker>>(new Map());
  const responderMarkersRef = useRef<Map<string, maplibregl.Marker>>(new Map());

  // ── Initialize map ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: FREE_STYLE_URL,
      center: [85.324, 27.717], // Kathmandu, Nepal
      zoom: 11,
      pitch: 0,
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.addControl(new maplibregl.FullscreenControl(), "top-right");

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // ── Update incident markers ─────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const seen = new Set<string>();

    for (const inc of incidents) {
      seen.add(inc.cluster_id);
      const color = SEVERITY_COLORS[inc.severity] ?? "#6b7280";
      const icon = STATUS_ICONS[inc.status] ?? "❓";
      const isSelected = inc.cluster_id === selectedClusterId;

      if (markersRef.current.has(inc.cluster_id)) {
        // Update existing marker
        const existing = markersRef.current.get(inc.cluster_id)!;
        existing.setLngLat([inc.lon, inc.lat]);
        continue;
      }

      // Create new marker
      const el = document.createElement("div");
      el.className = "incident-marker";
      el.style.cssText = `
        width: ${isSelected ? 36 : 28}px;
        height: ${isSelected ? 36 : 28}px;
        background: ${color};
        border: ${isSelected ? "3px solid white" : "2px solid rgba(255,255,255,0.8)"};
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: ${isSelected ? 16 : 12}px;
        cursor: pointer;
        box-shadow: 0 2px 6px rgba(0,0,0,0.4);
        transition: all 0.2s;
      `;
      el.textContent = icon;
      el.title = `${inc.severity} — ${inc.status}\n${inc.cluster_id}`;

      el.addEventListener("click", () => onSelectIncident(inc.cluster_id));

      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([inc.lon, inc.lat])
        .addTo(map);

      // Tooltip
      const popup = new maplibregl.Popup({
        offset: 20,
        closeButton: false,
        closeOnClick: false,
      }).setHTML(`
        <div style="padding:4px 8px;font-family:system-ui;font-size:13px;">
          <strong>${inc.severity}</strong> · ${inc.status}<br/>
          Confidence: ${(inc.confidence * 100).toFixed(0)}%<br/>
          <span style="color:#888;font-size:11px;">${(inc.cluster_id ?? "—").slice(0, 20)}…</span>
        </div>
      `);

      el.addEventListener("mouseenter", () => marker.setPopup(popup));
      el.addEventListener("mouseleave", () => marker.setPopup(undefined));

      markersRef.current.set(inc.cluster_id, marker);
    }

    // Remove stale markers
    for (const [id, marker] of markersRef.current) {
      if (!seen.has(id)) {
        marker.remove();
        markersRef.current.delete(id);
      }
    }
  }, [incidents, selectedClusterId, onSelectIncident]);

  // ── Update responder markers ────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const seen = new Set<string>();

    for (const resp of responders) {
      seen.add(resp.id);

      if (responderMarkersRef.current.has(resp.id)) {
        responderMarkersRef.current.get(resp.id)!.setLngLat([resp.lon, resp.lat]);
        continue;
      }

      const el = document.createElement("div");
      el.style.cssText = `
        width: 22px;
        height: 22px;
        background: #3b82f6;
        border: 2px solid white;
        border-radius: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        cursor: pointer;
        box-shadow: 0 1px 4px rgba(0,0,0,0.3);
      `;
      el.textContent = "🚒";
      el.title = `${resp.name} (${resp.status})`;

      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([resp.lon, resp.lat])
        .addTo(map);

      responderMarkersRef.current.set(resp.id, marker);
    }

    for (const [id, marker] of responderMarkersRef.current) {
      if (!seen.has(id)) {
        marker.remove();
        responderMarkersRef.current.delete(id);
      }
    }
  }, [responders]);

  // ── Highlight selected incident ─────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedClusterId) return;

    const inc = incidents.find((i) => i.cluster_id === selectedClusterId);
    if (inc) {
      map.flyTo({ center: [inc.lon, inc.lat], zoom: 13, duration: 800 });
    }
  }, [selectedClusterId, incidents]);

  return <div ref={mapContainer} className="w-full h-full rounded-lg" />;
}
