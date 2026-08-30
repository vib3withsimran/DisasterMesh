"use client";

import type { Incident, Responder } from "@/lib/api";

interface StatusSummaryProps {
  incidents: Incident[];
  responders: Responder[];
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
    <div className="flex items-center gap-4 px-4 py-2 bg-gray-900/80 backdrop-blur border-b border-gray-800 text-xs">
      {/* Logo / title */}
      <div className="flex items-center gap-2 mr-2">
        <span className="text-lg">🌐</span>
        <span className="font-semibold text-white text-sm">DisasterMesh</span>
      </div>

      <div className="h-4 w-px bg-gray-700" />

      {/* Incident severity counts */}
      <div className="flex items-center gap-1.5">
        <span className="text-gray-400">Incidents:</span>
        <span className="bg-red-500 text-white px-1.5 py-0.5 rounded font-medium">
          P1:{counts.P1}
        </span>
        <span className="bg-orange-500 text-white px-1.5 py-0.5 rounded font-medium">
          P2:{counts.P2}
        </span>
        <span className="bg-yellow-400 text-gray-900 px-1.5 py-0.5 rounded font-medium">
          P3:{counts.P3}
        </span>
        <span className="bg-gray-500 text-white px-1.5 py-0.5 rounded font-medium">
          P4:{counts.P4}
        </span>
      </div>

      <div className="h-4 w-px bg-gray-700" />

      {/* Responder status */}
      <div className="flex items-center gap-1.5">
        <span className="text-gray-400">Responders:</span>
        <span className="text-green-400">✓{respCounts.available}</span>
        <span className="text-orange-400">🚒{respCounts.assigned}</span>
        <span className="text-yellow-400">⏱{respCounts.en_route}</span>
        <span className="text-blue-400">📍{respCounts.on_scene}</span>
      </div>
    </div>
  );
}
