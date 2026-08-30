"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { WsEvent } from "@/lib/api";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/updates";

/**
 * Connect to the DisasterMesh WebSocket and return live events.
 * Auto-reconnects on disconnect.
 */
export function useWebSocket(onEvent?: (event: WsEvent) => void) {
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<WsEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        setConnected(true);
        console.log("[WS] Connected");
      };

      ws.onmessage = (msg) => {
        try {
          const event: WsEvent = JSON.parse(msg.data);
          setEvents((prev) => [event, ...prev].slice(0, 200)); // keep last 200
          onEventRef.current?.(event);
        } catch {
          console.warn("[WS] Non-JSON message:", msg.data);
        }
      };

      ws.onclose = () => {
        setConnected(false);
        console.log("[WS] Disconnected — reconnecting in 3s");
        reconnectTimer.current = setTimeout(connect, 3_000);
      };

      ws.onerror = () => {
        ws.close();
      };

      wsRef.current = ws;
    } catch {
      reconnectTimer.current = setTimeout(connect, 3_000);
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected, events };
}
