"use client";
import React, { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/lib/AuthContext";
import { useWebSocket, WSMessage } from "@/lib/useWebSocket";
import {
  mt5Api, tradingApi, marketApi, aiApi, analyticsApi,
  MT5Status, MT5StatusResponse, AccountInfo, Position, SignalData, PerformanceData, TradeLog,
} from "@/lib/api";
import MT5Connect from "./MT5Connect";
import AIStatusPanel from "./AIStatusPanel";
import PositionsPanel from "./PositionsPanel";
import TradeHistory from "./TradeHistory";
import PerformancePanel from "./PerformancePanel";
import PriceChart from "./PriceChart";
import ProfitCalendar from "./ProfitCalendar";
import NewsPanel from "./NewsPanel";
import {
  TrendingUp, LogOut, Wifi, WifiOff, Play, Square,
  Activity, RefreshCw, BarChart3, Settings, ShieldAlert,
} from "lucide-react";

export default function Dashboard() {
  const { user, logout } = useAuth();
  const { connected: wsConnected, lastMessage } = useWebSocket(user?.id ?? null);

  const [mt5Status, setMt5Status] = useState<MT5StatusResponse>({
    connected: false, account: null, trading_active: false,
  });
  const [signal, setSignal] = useState<SignalData | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [performance, setPerformance] = useState<PerformanceData | null>(null);
  const [tradeLogs, setTradeLogs] = useState<TradeLog[]>([]);
  const [symbol, setSymbol] = useState("XAUUSD");
  const [showMT5Modal, setShowMT5Modal] = useState(false);
  const [tradingLoading, setTradingLoading] = useState(false);
  const [manualLot, setManualLot] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<"dashboard" | "history" | "analytics">("dashboard");

  const refreshStatus = useCallback(async () => {
    try {
      const status = await mt5Api.status();
      setMt5Status(status);
    } catch { /* not connected yet */ }
  }, []);

  const refreshData = useCallback(async () => {
    try {
      const [pos, perf, logs] = await Promise.all([
        marketApi.positions().catch(() => []),
        analyticsApi.performance().catch(() => null),
        analyticsApi.tradeLogs(20).catch(() => []),
      ]);
      setPositions(pos);
      if (perf) setPerformance(perf);
      setTradeLogs(logs);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    refreshStatus();
    refreshData();
    const interval = setInterval(() => { refreshStatus(); refreshData(); }, 5000);
    return () => clearInterval(interval);
  }, [refreshStatus, refreshData]);

  // Handle WebSocket messages
  useEffect(() => {
    if (!lastMessage) return;
    const msg = lastMessage as WSMessage;
    if (msg.type === "signal_update" && msg.data) setSignal(msg.data);
    if (msg.type === "account_update") {
      if (msg.data) setMt5Status((p) => ({ ...p, account: msg.data }));
      if (msg.positions) setPositions(msg.positions);
    }
    if (msg.type === "trade_executed" || msg.type === "trade_failed") refreshData();
  }, [lastMessage, refreshData]);

  const handleStartTrading = async () => {
    setTradingLoading(true);
    try {
      await tradingApi.start([symbol], manualLot);
      setMt5Status((p) => ({ ...p, trading_active: true }));
    } catch (err: any) { alert(err.message); }
    finally { setTradingLoading(false); }
  };

  const handleStopTrading = async () => {
    setTradingLoading(true);
    try {
      await tradingApi.stop();
      setMt5Status((p) => ({ ...p, trading_active: false }));
    } catch (err: any) { alert(err.message); }
    finally { setTradingLoading(false); }
  };

  const handleMT5Connected = (status: MT5Status) => {
    setMt5Status({ connected: status.connected, account: status as any, trading_active: false });
    setShowMT5Modal(false);
  };

  const acct = mt5Status.account;

  return (
    <div className="min-h-screen bg-surface">
      {/* Header */}
      <header className="border-b border-surface-border bg-surface-card/80 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-[1920px] mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-brand-600 rounded-lg flex items-center justify-center">
              <TrendingUp className="w-5 h-5 text-white" />
            </div>
            <span className="font-bold text-lg text-white">Algo Trade AI</span>
            <div className="hidden sm:flex items-center gap-1 ml-4">
              {(["dashboard", "history", "analytics"] as const).map((tab) => (
                <button key={tab} onClick={() => setActiveTab(tab)}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    activeTab === tab ? "bg-brand-600/20 text-brand-400" : "text-gray-400 hover:text-gray-200"
                  }`}>
                  {tab.charAt(0).toUpperCase() + tab.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* WS indicator */}
            <div className={`flex items-center gap-1.5 text-xs ${wsConnected ? "text-green-400" : "text-gray-500"}`}>
              {wsConnected ? <Wifi className="w-3.5 h-3.5" /> : <WifiOff className="w-3.5 h-3.5" />}
              <span className="hidden sm:inline">WS</span>
            </div>

            {/* MT5 status */}
            <button onClick={() => setShowMT5Modal(true)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium border transition-colors ${
                mt5Status.connected
                  ? "border-green-500/30 bg-green-500/10 text-green-400"
                  : "border-surface-border bg-surface hover:bg-surface-hover text-gray-400"
              }`}>
              <div className={`w-2 h-2 rounded-full ${mt5Status.connected ? "bg-green-400 animate-pulse" : "bg-gray-600"}`} />
              {mt5Status.connected ? "MT5 Connected" : "Connect MT5"}
            </button>

            {/* Lot size selector */}
            {mt5Status.connected && !mt5Status.trading_active && (
              <select
                value={manualLot ?? "auto"}
                onChange={(e) => setManualLot(e.target.value === "auto" ? null : parseFloat(e.target.value))}
                className="bg-surface border border-surface-border text-gray-300 text-xs rounded-md px-2 py-1.5 focus:outline-none focus:border-brand-500">
                <option value="auto">Auto Lot</option>
                {[0.01, 0.02, 0.03, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0].map((v) => (
                  <option key={v} value={v}>{v.toFixed(2)}</option>
                ))}
              </select>
            )}

            {/* Daily loss limit */}
            {mt5Status.connected && mt5Status.daily_loss_limit != null && (
              <div className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium border ${
                mt5Status.halted
                  ? "border-red-500/40 bg-red-500/15 text-red-400"
                  : (mt5Status.losses_today ?? 0) > 0
                    ? "border-yellow-500/30 bg-yellow-500/10 text-yellow-400"
                    : "border-surface-border bg-surface text-gray-400"
              }`} title="Daily loss limit — bot halts new trades after this many losses today">
                <ShieldAlert className="w-3.5 h-3.5" />
                {mt5Status.halted ? "HALTED" : "Losses"} {mt5Status.losses_today ?? 0}/{mt5Status.daily_loss_limit}
              </div>
            )}

            {/* Trading toggle */}
            {mt5Status.connected && (
              <button
                onClick={mt5Status.trading_active ? handleStopTrading : handleStartTrading}
                disabled={tradingLoading}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${
                  mt5Status.trading_active
                    ? "bg-red-500/15 text-red-400 hover:bg-red-500/25 border border-red-500/30"
                    : "bg-green-500/15 text-green-400 hover:bg-green-500/25 border border-green-500/30"
                }`}>
                {mt5Status.trading_active ? <Square className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                {mt5Status.trading_active ? "Stop AI" : "Start AI"}
              </button>
            )}

            <span className="text-sm text-gray-400 hidden md:inline">{user?.username}</span>
            <button onClick={logout} className="text-gray-500 hover:text-gray-300 p-1.5">
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      {/* MT5 Modal */}
      {showMT5Modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-md mx-4">
            <MT5Connect onConnected={handleMT5Connected} onClose={() => setShowMT5Modal(false)} />
          </div>
        </div>
      )}

      {/* Main content */}
      <main className="max-w-[1920px] mx-auto p-4">
        {activeTab === "dashboard" && (
          <>
            {/* Account stats bar */}
            {acct && (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
                {[
                  { label: "Balance", value: `$${acct.balance?.toLocaleString(undefined, { minimumFractionDigits: 2 })}` },
                  { label: "Equity", value: `$${acct.equity?.toLocaleString(undefined, { minimumFractionDigits: 2 })}` },
                  { label: "Profit", value: `$${acct.profit?.toFixed(2)}`, color: (acct.profit ?? 0) >= 0 ? "text-profit" : "text-loss" },
                  { label: "Free Margin", value: `$${acct.free_margin?.toLocaleString(undefined, { minimumFractionDigits: 2 })}` },
                  { label: "Leverage", value: `1:${acct.leverage}` },
                  { label: "Server", value: acct.server || "-" },
                ].map((s) => (
                  <div key={s.label} className="card py-3">
                    <p className="stat-label">{s.label}</p>
                    <p className={`text-lg font-bold font-mono ${(s as any).color || "text-white"}`}>{s.value}</p>
                  </div>
                ))}
              </div>
            )}

            {/* News filter status */}
            <div className="mb-3">
              <NewsPanel connected={mt5Status.connected} />
            </div>

            {/* Symbol selector + refresh */}
            <div className="flex items-center gap-3 mb-4">
              <select value={symbol} onChange={(e) => setSymbol(e.target.value)}
                className="input w-40 text-sm">
                {["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "US30"].map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <button onClick={() => { refreshStatus(); refreshData(); }}
                className="btn-outline text-sm flex items-center gap-1.5">
                <RefreshCw className="w-3.5 h-3.5" /> Refresh
              </button>
            </div>

            {/* Chart + AI panel row */}
            <div className="grid grid-cols-1 xl:grid-cols-4 gap-4 mb-4">
              <div className="xl:col-span-3">
                <PriceChart symbol={symbol} connected={mt5Status.connected} />
              </div>
              <div>
                <AIStatusPanel signal={signal} symbol={symbol} connected={mt5Status.connected} />
              </div>
            </div>

            {/* Positions */}
            <PositionsPanel positions={positions} />
          </>
        )}

        {activeTab === "history" && (
          <>
            <TradeHistory logs={tradeLogs} onRefresh={refreshData} />
            <ProfitCalendar />
          </>
        )}
        {activeTab === "analytics" && <PerformancePanel performance={performance} onClear={refreshData} />}
      </main>
    </div>
  );
}
