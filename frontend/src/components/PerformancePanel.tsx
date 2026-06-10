"use client";
import React, { useEffect, useState } from "react";
import { PerformanceData, BacktestData, analyticsApi } from "@/lib/api";
import { BarChart3, Trophy, TrendingDown, Target, DollarSign, Trash2, History } from "lucide-react";

interface Props {
  performance: PerformanceData | null;
  onClear?: () => void;
}

export default function PerformancePanel({ performance, onClear }: Props) {
  const [backtest, setBacktest] = useState<BacktestData | null>(null);

  useEffect(() => {
    analyticsApi.backtest().then(setBacktest).catch(() => setBacktest(null));
  }, []);

  const handleClear = async () => {
    if (!confirm("Clear performance metrics? This will also clear trade history and cannot be undone.")) return;
    try {
      await analyticsApi.clearPerformance();
      if (onClear) onClear();
    } catch (err: any) {
      alert(err.message || "Failed to clear performance metrics");
    }
  };
  const p = performance || {
    total_trades: 0, winning_trades: 0, losing_trades: 0,
    total_profit: 0, max_drawdown: 0, win_rate: 0,
  };

  const stats = [
    { label: "Total Trades", value: p.total_trades.toString(), icon: BarChart3, color: "text-brand-400" },
    { label: "Winning Trades", value: p.winning_trades.toString(), icon: Trophy, color: "text-profit" },
    { label: "Losing Trades", value: p.losing_trades.toString(), icon: TrendingDown, color: "text-loss" },
    { label: "Win Rate", value: `${(p.win_rate * 100).toFixed(1)}%`, icon: Target, color: "text-brand-400" },
    { label: "Total Profit", value: `$${p.total_profit.toFixed(2)}`, icon: DollarSign, color: p.total_profit >= 0 ? "text-profit" : "text-loss" },
    { label: "Max Drawdown", value: `$${p.max_drawdown.toFixed(2)}`, icon: TrendingDown, color: "text-loss" },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-brand-400" />
          <h2 className="text-xl font-bold text-white">Performance Analytics</h2>
        </div>
        <button onClick={handleClear} className="btn-outline text-xs flex items-center gap-1.5 text-red-400 border-red-500/30 hover:bg-red-500/10">
          <Trash2 className="w-3.5 h-3.5" /> Clear
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {stats.map((stat) => (
          <div key={stat.label} className="card flex items-start gap-4">
            <div className={`p-2.5 rounded-lg bg-surface ${stat.color}`}>
              <stat.icon className="w-5 h-5" />
            </div>
            <div>
              <p className="stat-label">{stat.label}</p>
              <p className={`stat-value ${stat.color}`}>{stat.value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Win rate bar */}
      <div className="card">
        <h3 className="font-semibold text-white mb-3">Win / Loss Ratio</h3>
        <div className="w-full h-4 bg-surface rounded-full overflow-hidden flex">
          {p.total_trades > 0 && (
            <>
              <div className="h-full bg-profit transition-all" style={{ width: `${(p.winning_trades / p.total_trades) * 100}%` }} />
              <div className="h-full bg-loss transition-all" style={{ width: `${(p.losing_trades / p.total_trades) * 100}%` }} />
            </>
          )}
        </div>
        <div className="flex justify-between mt-2 text-xs text-gray-500">
          <span>{p.winning_trades} wins</span>
          <span>{p.losing_trades} losses</span>
        </div>
      </div>

      {/* Backtest Results */}
      {backtest?.available && (
        <div className="card">
          <div className="flex items-center gap-2 mb-4">
            <History className="w-5 h-5 text-brand-400" />
            <h3 className="font-semibold text-white">Backtest Results — Fixed TP + Profit Locks</h3>
          </div>
          <p className="text-xs text-gray-400 mb-3">{backtest.strategy}</p>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border text-gray-400 text-left">
                  <th className="pb-2 pr-4 font-medium">Metric</th>
                  <th className="pb-2 pr-4 font-medium text-right">Value</th>
                </tr>
              </thead>
              <tbody className="text-gray-200">
                <tr className="border-b border-surface-border/50">
                  <td className="py-2 pr-4">Trades</td>
                  <td className="py-2 pr-4 text-right font-mono">{backtest.trades}</td>
                </tr>
                <tr className="border-b border-surface-border/50">
                  <td className="py-2 pr-4">Win Rate</td>
                  <td className="py-2 pr-4 text-right font-mono text-profit">{(backtest.win_rate! * 100).toFixed(1)}%</td>
                </tr>
                <tr className="border-b border-surface-border/50">
                  <td className="py-2 pr-4">Total R</td>
                  <td className="py-2 pr-4 text-right font-mono text-profit">+{backtest.total_r}R</td>
                </tr>
                <tr className="border-b border-surface-border/50">
                  <td className="py-2 pr-4">Expectancy</td>
                  <td className="py-2 pr-4 text-right font-mono">{backtest.expectancy}R / trade</td>
                </tr>
                <tr className="border-b border-surface-border/50">
                  <td className="py-2 pr-4">Profit Factor</td>
                  <td className="py-2 pr-4 text-right font-mono text-profit">{backtest.profit_factor}</td>
                </tr>
                <tr className="border-b border-surface-border/50">
                  <td className="py-2 pr-4">Avg Win</td>
                  <td className="py-2 pr-4 text-right font-mono text-profit">+{backtest.avg_win}R</td>
                </tr>
                <tr className="border-b border-surface-border/50">
                  <td className="py-2 pr-4">Avg Loss</td>
                  <td className="py-2 pr-4 text-right font-mono text-loss">{backtest.avg_loss}R</td>
                </tr>
                <tr>
                  <td className="py-2 pr-4">Max Drawdown</td>
                  <td className="py-2 pr-4 text-right font-mono text-loss">-{backtest.max_drawdown_r}R</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
