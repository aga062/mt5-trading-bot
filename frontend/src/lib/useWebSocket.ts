"use client";
import { useEffect, useRef, useState, useCallback } from "react";

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

export interface WSMessage {
  type: string;
  data?: any;
  message?: string;
  timestamp?: string;
  [key: string]: any;
}

export function useWebSocket(userId: number | null) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const reconnectTimer = useRef<NodeJS.Timeout | null>(null);

  const connect = useCallback(() => {
    if (!userId) return;
    const token = localStorage.getItem("token");
    const url = `${WS_BASE}/ws/${userId}${token ? `?token=${token}` : ""}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        setLastMessage(msg);
      } catch {
        // pong or non-JSON
      }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      reconnectTimer.current = setTimeout(() => connect(), 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [userId]);

  useEffect(() => {
    connect();
    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send("ping");
      }
    }, 15000);

    return () => {
      clearInterval(pingInterval);
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected, lastMessage };
}
