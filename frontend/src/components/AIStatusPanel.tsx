"use client";
import React, { useState, useEffect } from "react";
import { aiApi, SignalData, DailyBiasData } from "@/lib/api";
import { Brain, TrendingUp, TrendingDown, Target, Zap, Clock, Crosshair, Shield, CalendarDays } from "lucide-react";

interface Props {
  signal: SignalData | null;
  symbol: string;
  connected: boolean;
}

export default function AIStatusPanel({ signal, symbol, connected }: Props) {
  const [localSignal, setLocalSignal] = useState<SignalData | null>(signal);
  const [dailyBias, setDailyBias] = useState<DailyBiasData | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (signal) setLocalSignal(signal);
  }, [signal]);

  const fetchSignal = async () => {
    if (!connected) return;
    setLoading(true);
    try {
      const s = await aiApi.signal(symbol);
      setLocalSignal(s);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  const fetchDailyBias = async () => {
    if (!connected) return;
    try {
      const b = await aiApi.dailyBias(symbol);
      setDailyBias(b);
    } catch { /* ignore */ }
  };

  useEffect(() => {
    if (connected) { fetchSignal(); fetchDailyBias(); }
    const interval = setInterval(() => { if (connected) fetchSignal(); }, 15000);
    const biasInterval = setInterval(() => { if (connected) fetchDailyBias(); }, 60000);
    return () => { clearInterval(interval); clearInterval(biasInterval); };
  }, [connected, symbol]);

  const s = localSignal;
  const ict = s?.ict;
  const setup = ict?.setup;
  const action = s?.action || "WAIT";
  const reason = s?.reason || "—";

  const actionColor = action === "BUY" ? "text-buy" : action === "SELL" ? "text-sell" : "text-warn";
  const actionBg = action === "BUY" ? "bg-green-500/10" : action === "SELL" ? "bg-red-500/10" : "bg-yellow-500/10";

  return (
    <div className="card h-full flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Brain className="w-5 h-5 text-brand-400" />
          <h3 className="font-semibold text-white">ICT Setup Scanner</h3>
        </div>
        {loading && <div className="w-4 h-4 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />}
      </div>

      <div className="space-y-4 flex-1">
        {/* Daily Bias (Layer 0 — D1/H4) */}
        {dailyBias && (
          <div className={`rounded-lg p-3 border ${
            dailyBias.bias === "BULLISH" ? "border-green-500/30 bg-green-500/10"
            : dailyBias.bias === "BEARISH" ? "border-red-500/30 bg-red-500/10"
            : "border-yellow-500/30 bg-yellow-500/10"
          }`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-gray-400 text-sm">
                <CalendarDays className="w-4 h-4" />
                Daily Bias
              </div>
              <span className={`font-bold text-sm flex items-center gap-1 ${
                dailyBias.bias === "BULLISH" ? "text-buy"
                : dailyBias.bias === "BEARISH" ? "text-sell" : "text-warn"
              }`}>
                {dailyBias.bias === "BULLISH" && <TrendingUp className="w-4 h-4" />}
                {dailyBias.bias === "BEARISH" && <TrendingDown className="w-4 h-4" />}
                {dailyBias.bias}
                <span className="text-gray-500 font-mono text-xs">({dailyBias.score > 0 ? "+" : ""}{dailyBias.score})</span>
              </span>
            </div>
            {dailyBias.bias === "NEUTRAL" && (
              <p className="text-xs text-gray-500 mt-1.5">No trades today — D1/H4 not aligned</p>
            )}
          </div>
        )}

        {/* ICT Setup Valid */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-gray-400 text-sm">
            <Crosshair className="w-4 h-4" />
            Setup Status
          </div>
          <span className={`font-bold text-sm ${ict?.valid ? "text-buy" : "text-gray-500"}`}>
            {ict?.valid ? "SETUP FOUND" : "SCANNING"}
          </span>
        </div>

        {/* Direction */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-gray-400 text-sm">
            <Zap className="w-4 h-4" />
            Direction
          </div>
          <span className={`font-bold text-sm px-2 py-0.5 rounded ${actionBg} ${actionColor}`}>{action}</span>
        </div>

        {/* Trade Type (TREND vs COUNTER-TREND) */}
        {s?.trade_type && action !== "WAIT" && (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-gray-400 text-sm">
              <Shield className="w-4 h-4" />
              Trade Type
            </div>
            <span className={`font-bold text-xs px-2 py-0.5 rounded ${
              s.trade_type === "COUNTER_TREND" ? "bg-amber-500/15 text-amber-400" : "bg-green-500/10 text-buy"
            }`}>
              {s.trade_type === "COUNTER_TREND" ? "COUNTER-TREND" : "TREND"}
            </span>
          </div>
        )}

        {/* ICT Setup Details (when found) */}
        {setup && (
          <div className="bg-surface rounded-lg p-3 text-xs space-y-1.5">
            <div className="flex justify-between">
              <span className="text-gray-500">Limit Entry (OB 50%)</span>
              <span className="text-brand-400 font-mono font-semibold">{setup.ob_mid}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Order Block</span>
              <span className="text-gray-200 font-mono">{setup.ob_low}–{setup.ob_high}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Stop Loss</span>
              <span className="text-loss font-mono">{setup.sl_price}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Take Profit</span>
              <span className="text-profit font-mono">{setup.tp_price}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Confirmation</span>
              <span className="text-brand-400 font-semibold">{setup.confirmation}</span>
            </div>
          </div>
        )}

        {/* Trade Status */}
        <div className="mt-auto pt-4 border-t border-surface-border">
          <div className="flex items-center justify-between">
            <span className="text-gray-400 text-sm">Trade Status</span>
            <span className={`font-bold text-sm ${
              action === "BUY" || action === "SELL" ? "text-buy" : "text-warn"
            }`}>
              {action === "BUY" || action === "SELL" ? "LIMIT PLACED" : "WAITING"}
            </span>
          </div>
          {s?.entry_price ? (
            <p className="text-xs text-gray-500 mt-1">
              Limit Entry: <span className="text-gray-300 font-mono">{s.entry_price}</span>
            </p>
          ) : null}
        </div>

        {/* Reason */}
        <div className="pt-2 border-t border-surface-border">
          <p className="text-xs text-gray-500 mb-1.5">Current Status</p>
          <p className="text-xs text-gray-400">{reason}</p>
        </div>
      </div>
    </div>
  );
}
