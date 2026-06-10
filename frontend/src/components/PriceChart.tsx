"use client";
import React, { useEffect, useRef, useState } from "react";
import { createChart, IChartApi, ISeriesApi, CandlestickData, Time } from "lightweight-charts";
import { marketApi, CandleData } from "@/lib/api";
import { BarChart3 } from "lucide-react";

interface Props {
  symbol: string;
  connected: boolean;
}

export default function PriceChart({ symbol, connected }: Props) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const [timeframe, setTimeframe] = useState("H1");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { color: "#161822" },
        textColor: "#9ca3af",
      },
      grid: {
        vertLines: { color: "#1c1f2e" },
        horzLines: { color: "#1c1f2e" },
      },
      crosshair: {
        mode: 0,
      },
      rightPriceScale: {
        borderColor: "#262940",
      },
      timeScale: {
        borderColor: "#262940",
        timeVisible: true,
        secondsVisible: false,
      },
      width: chartContainerRef.current.clientWidth,
      height: 450,
    });

    const series = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderDownColor: "#ef4444",
      borderUpColor: "#22c55e",
      wickDownColor: "#ef4444",
      wickUpColor: "#22c55e",
    });

    chartRef.current = chart;
    seriesRef.current = series;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!connected || !seriesRef.current) return;

    const fetchCandles = async () => {
      setLoading(true);
      try {
        const candles = await marketApi.candles(symbol, timeframe, 200);
        if (seriesRef.current && candles.length > 0) {
          const mapped: CandlestickData[] = candles.map((c: CandleData) => ({
            time: (new Date(c.datetime).getTime() / 1000) as Time,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
          }));
          seriesRef.current.setData(mapped);
          chartRef.current?.timeScale().fitContent();
        }
      } catch {
        /* no data yet */
      } finally {
        setLoading(false);
      }
    };

    fetchCandles();
    const interval = setInterval(fetchCandles, 15000);
    return () => clearInterval(interval);
  }, [connected, symbol, timeframe]);

  const timeframes = ["M5", "M15", "M30", "H1", "H4", "D1"];

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-brand-400" />
          <h3 className="font-semibold text-white">{symbol}</h3>
          {loading && (
            <div className="w-3.5 h-3.5 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
          )}
        </div>
        <div className="flex gap-1">
          {timeframes.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                timeframe === tf
                  ? "bg-brand-600/20 text-brand-400"
                  : "text-gray-500 hover:text-gray-300 hover:bg-surface-hover"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>
      <div ref={chartContainerRef} className="w-full rounded-lg overflow-hidden" />
      {!connected && (
        <div className="absolute inset-0 flex items-center justify-center bg-surface/80 rounded-xl">
          <p className="text-gray-500">Connect to MT5 to view live charts</p>
        </div>
      )}
    </div>
  );
}
