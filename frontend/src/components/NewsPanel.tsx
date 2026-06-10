"use client";
import React, { useEffect, useState, useCallback } from "react";
import { newsApi, NewsStatus } from "@/lib/api";
import { ShieldAlert, ShieldCheck, Clock } from "lucide-react";

export default function NewsPanel({ connected }: { connected: boolean }) {
  const [status, setStatus] = useState<NewsStatus | null>(null);

  const refresh = useCallback(async () => {
    if (!connected) return;
    try {
      const s = await newsApi.status();
      setStatus(s);
    } catch { /* ignore */ }
  }, [connected]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 60_000); // refresh every minute
    return () => clearInterval(id);
  }, [refresh]);

  if (!connected || !status) return null;

  const { blocked, reason, upcoming_events } = status;

  return (
    <div className={`rounded-lg border px-3 py-2.5 flex flex-col gap-2 text-xs ${
      blocked
        ? "border-red-500/40 bg-red-500/10"
        : "border-surface-border bg-surface-card"
    }`}>
      {/* Status row */}
      <div className="flex items-center gap-2">
        {blocked
          ? <ShieldAlert className="w-4 h-4 text-red-400 shrink-0" />
          : <ShieldCheck className="w-4 h-4 text-green-400 shrink-0" />}
        <span className={`font-semibold ${blocked ? "text-red-400" : "text-green-400"}`}>
          {blocked ? "NEWS BLACKOUT" : "NEWS CLEAR"}
        </span>
        <span className="text-gray-400 truncate">{reason}</span>
      </div>

      {/* Upcoming events (up to 3) */}
      {upcoming_events.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {upcoming_events.slice(0, 3).map((ev, i) => (
            <div key={i} className="flex items-center gap-1 text-gray-400">
              <Clock className="w-3 h-3 shrink-0" />
              <span className="text-gray-300 font-medium">{ev.title}</span>
              <span className="text-gray-500">
                {ev.minutes_away < 60
                  ? `in ${ev.minutes_away}m`
                  : `in ${Math.round(ev.minutes_away / 60)}h`}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
