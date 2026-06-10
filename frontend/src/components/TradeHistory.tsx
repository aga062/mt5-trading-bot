"use client";
import React, { useState, useEffect } from "react";
import { TradeLog, FillStatsData, analyticsApi } from "@/lib/api";
import { History, RefreshCw, Trash2 } from "lucide-react";

interface Props {
  logs: TradeLog[];
  onRefresh: () => void;
}

export default function TradeHistory({ logs, onRefresh }: Props) {
  const [fills, setFills] = useState<FillStatsData | null>(null);

  useEffect(() => {
    let active = true;
    const load = () => analyticsApi.fillStats().then((s) => { if (active) setFills(s); }).catch(() => {});
    load();
    const id = setInterval(load, 10000);
    return () => { active = false; clearInterval(id); };
  }, []);

  const handleClear = async () => {
    if (!confirm("Clear all trade history? This cannot be undone.")) return;
    try {
      await analyticsApi.clearTradeLogs();
      onRefresh();
    } catch (err: any) {
      alert(err.message || "Failed to clear trade history");
    }
  };

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <History className="w-5 h-5 text-brand-400" />
          <h3 className="font-semibold text-white">Trade History</h3>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleClear} className="btn-outline text-xs flex items-center gap-1.5 text-red-400 border-red-500/30 hover:bg-red-500/10">
            <Trash2 className="w-3.5 h-3.5" /> Clear
          </button>
          <button onClick={onRefresh} className="btn-outline text-xs flex items-center gap-1.5">
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
        </div>
      </div>

      {/* Limit-order fill rate (bot orders only) */}
      {fills && fills.placed > 0 && (
        <div className="flex flex-wrap items-center gap-2 mb-4 text-xs">
          <span className="px-2.5 py-1 rounded-md bg-surface border border-surface-border">
            Fill rate <span className="font-bold text-white">{(fills.fill_rate * 100).toFixed(0)}%</span>
          </span>
          <span className="px-2.5 py-1 rounded-md bg-green-500/10 text-buy">Filled {fills.filled}</span>
          <span className="px-2.5 py-1 rounded-md bg-gray-600/15 text-gray-400">Cancelled {fills.cancelled}</span>
          <span className="px-2.5 py-1 rounded-md bg-yellow-500/10 text-yellow-400">Pending {fills.pending}</span>
          {fills.failed > 0 && (
            <span className="px-2.5 py-1 rounded-md bg-red-500/10 text-loss">Failed {fills.failed}</span>
          )}
        </div>
      )}

      {logs.length === 0 ? (
        <p className="text-gray-500 text-sm text-center py-8">No trades recorded yet</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-xs uppercase tracking-wider border-b border-surface-border">
                <th className="text-left pb-3 pr-4">Time</th>
                <th className="text-left pb-3 pr-4">Symbol</th>
                <th className="text-left pb-3 pr-4">Action</th>
                <th className="text-right pb-3 pr-4">Lot</th>
                <th className="text-right pb-3 pr-4">Entry</th>
                <th className="text-right pb-3 pr-4">SL</th>
                <th className="text-right pb-3 pr-4">TP</th>
                <th className="text-left pb-3 pr-4">H1 Bias</th>
                <th className="text-left pb-3 pr-4">AI</th>
                <th className="text-left pb-3 pr-4">Zone</th>
                <th className="text-left pb-3 pr-4">Status</th>
                <th className="text-right pb-3">Profit</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id} className="border-b border-surface-border/50 hover:bg-surface-hover/50">
                  <td className="py-2.5 pr-4 text-gray-400 text-xs whitespace-nowrap">
                    {(() => {
                      try {
                        let ts = log.opened_at;
                        if (!ts) return "—";
                        // Normalize: replace space with T, ensure UTC suffix
                        ts = ts.replace(" ", "T");
                        if (!ts.endsWith("Z") && !ts.includes("+")) ts += "Z";
                        const d = new Date(ts);
                        if (isNaN(d.getTime())) return "—";
                        return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "medium" });
                      } catch { return "—"; }
                    })()}
                  </td>
                  <td className="py-2.5 pr-4 text-white font-medium">{log.symbol}</td>
                  <td className="py-2.5 pr-4">
                    <span className={log.action === "BUY" ? "badge-buy" : "badge-sell"}>{log.action}</span>
                  </td>
                  <td className="py-2.5 pr-4 text-right font-mono text-gray-300">{log.lot_size}</td>
                  <td className="py-2.5 pr-4 text-right font-mono text-gray-300">{log.entry_price}</td>
                  <td className="py-2.5 pr-4 text-right font-mono text-gray-400">{log.stop_loss ? log.stop_loss : "—"}</td>
                  <td className="py-2.5 pr-4 text-right font-mono text-gray-400">{log.take_profit ? log.take_profit : "—"}</td>
                  <td className="py-2.5 pr-4">
                    <span className={`text-xs font-medium ${log.h1_bias === "BULLISH" ? "text-buy" : "text-sell"}`}>
                      {log.h1_bias}
                    </span>
                  </td>
                  <td className="py-2.5 pr-4 text-xs text-gray-300">{log.ai_decision}</td>
                  <td className="py-2.5 pr-4 text-xs text-gray-400">{log.m5_zone}</td>
                  <td className="py-2.5 pr-4">
                    <span className={`badge ${
                      log.status === "OPEN" ? "bg-blue-500/15 text-blue-400" :
                      log.status === "PENDING" ? "bg-yellow-500/15 text-yellow-400" :
                      log.status === "CLOSED" ? "bg-gray-500/15 text-gray-400" :
                      log.status === "CANCELLED" ? "bg-gray-600/15 text-gray-500" :
                      "bg-red-500/15 text-red-400"
                    }`}>{log.status}</span>
                  </td>
                  <td className={`py-2.5 text-right font-mono font-semibold ${
                    log.profit >= 0 ? "text-profit" : "text-loss"
                  }`}>
                    {log.profit >= 0 ? "+" : ""}{log.profit.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
