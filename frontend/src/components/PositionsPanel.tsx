"use client";
import React from "react";
import { Position } from "@/lib/api";
import { Briefcase } from "lucide-react";

interface Props {
  positions: Position[];
}

export default function PositionsPanel({ positions }: Props) {
  const safePositions = positions || [];

  return (
    <div className="card">
      <div className="flex items-center gap-2 mb-4">
        <Briefcase className="w-5 h-5 text-brand-400" />
        <h3 className="font-semibold text-white">Open Positions</h3>
        <span className="ml-auto text-xs text-gray-500">{safePositions.length} open</span>
      </div>

      {safePositions.length === 0 ? (
        <p className="text-gray-500 text-sm text-center py-8">No open positions</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-xs uppercase tracking-wider border-b border-surface-border">
                <th className="text-left pb-3 pr-4">Ticket</th>
                <th className="text-left pb-3 pr-4">Symbol</th>
                <th className="text-left pb-3 pr-4">Type</th>
                <th className="text-right pb-3 pr-4">Volume</th>
                <th className="text-right pb-3 pr-4">Open Price</th>
                <th className="text-right pb-3 pr-4">Current</th>
                <th className="text-right pb-3 pr-4">SL</th>
                <th className="text-right pb-3 pr-4">TP</th>
                <th className="text-right pb-3">Profit</th>
              </tr>
            </thead>
            <tbody>
              {safePositions.map((pos) => (
                <tr key={pos.ticket} className="border-b border-surface-border/50 hover:bg-surface-hover/50">
                  <td className="py-2.5 pr-4 font-mono text-gray-300">{pos.ticket}</td>
                  <td className="py-2.5 pr-4 text-white font-medium">{pos.symbol}</td>
                  <td className="py-2.5 pr-4">
                    <span className={pos.type === "BUY" ? "badge-buy" : "badge-sell"}>
                      {pos.type}
                    </span>
                  </td>
                  <td className="py-2.5 pr-4 text-right font-mono text-gray-300">{pos.volume}</td>
                  <td className="py-2.5 pr-4 text-right font-mono text-gray-300">{pos.price_open}</td>
                  <td className="py-2.5 pr-4 text-right font-mono text-gray-300">{pos.price_current}</td>
                  <td className="py-2.5 pr-4 text-right font-mono text-gray-400">{pos.sl || "—"}</td>
                  <td className="py-2.5 pr-4 text-right font-mono text-gray-400">{pos.tp || "—"}</td>
                  <td className={`py-2.5 text-right font-mono font-semibold ${
                    pos.profit >= 0 ? "text-profit" : "text-loss"
                  }`}>
                    {pos.profit >= 0 ? "+" : ""}{pos.profit.toFixed(2)}
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
