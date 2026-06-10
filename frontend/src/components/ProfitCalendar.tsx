"use client";
import React, { useState, useEffect } from "react";
import { Calendar, ChevronLeft, ChevronRight } from "lucide-react";
import { analyticsApi, DailyProfit } from "@/lib/api";

export default function ProfitCalendar() {
  const [currentDate, setCurrentDate] = useState(new Date());
  const [dailyProfits, setDailyProfits] = useState<DailyProfit[]>([]);

  useEffect(() => {
    analyticsApi.dailyProfits().then(setDailyProfits).catch(() => {});
  }, []);

  const year = currentDate.getFullYear();
  const month = currentDate.getMonth();

  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const profitMap = new Map<string, DailyProfit>();
  dailyProfits.forEach((dp) => profitMap.set(dp.date, dp));

  const prevMonth = () => setCurrentDate(new Date(year, month - 1, 1));
  const nextMonth = () => setCurrentDate(new Date(year, month + 1, 1));

  const monthLabel = currentDate.toLocaleString(undefined, { month: "long", year: "numeric" });

  // Calculate monthly total
  const monthlyTotal = dailyProfits
    .filter((dp) => {
      const d = new Date(dp.date);
      return d.getFullYear() === year && d.getMonth() === month;
    })
    .reduce((sum, dp) => sum + dp.total_profit, 0);

  const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  const cells: (number | null)[] = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  return (
    <div className="card mt-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Calendar className="w-5 h-5 text-brand-400" />
          <h3 className="font-semibold text-white">Daily Profit Calendar</h3>
        </div>
        <div className={`text-sm font-mono font-semibold ${monthlyTotal >= 0 ? "text-profit" : "text-loss"}`}>
          Month: {monthlyTotal >= 0 ? "+" : ""}{monthlyTotal.toFixed(2)}
        </div>
      </div>

      {/* Month navigation */}
      <div className="flex items-center justify-between mb-3">
        <button onClick={prevMonth} className="p-1.5 rounded-md hover:bg-surface-hover text-gray-400 hover:text-white transition-colors">
          <ChevronLeft className="w-4 h-4" />
        </button>
        <span className="text-sm font-medium text-gray-200">{monthLabel}</span>
        <button onClick={nextMonth} className="p-1.5 rounded-md hover:bg-surface-hover text-gray-400 hover:text-white transition-colors">
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>

      {/* Day headers */}
      <div className="grid grid-cols-7 gap-1 mb-1">
        {dayNames.map((name) => (
          <div key={name} className="text-center text-[10px] text-gray-500 font-medium py-1">
            {name}
          </div>
        ))}
      </div>

      {/* Calendar grid */}
      <div className="grid grid-cols-7 gap-1">
        {cells.map((day, idx) => {
          if (day === null) {
            return <div key={`empty-${idx}`} className="aspect-square" />;
          }

          const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
          const dp = profitMap.get(dateStr);
          const isToday =
            day === new Date().getDate() &&
            month === new Date().getMonth() &&
            year === new Date().getFullYear();

          let bgClass = "bg-surface-hover/30";
          let textClass = "text-gray-500";

          if (dp) {
            if (dp.total_profit > 0) {
              bgClass = "bg-green-500/15 border border-green-500/30";
              textClass = "text-green-400";
            } else if (dp.total_profit < 0) {
              bgClass = "bg-red-500/15 border border-red-500/30";
              textClass = "text-red-400";
            } else {
              bgClass = "bg-gray-500/15 border border-gray-500/30";
              textClass = "text-gray-400";
            }
          }

          return (
            <div
              key={dateStr}
              className={`aspect-square rounded-md flex flex-col items-center justify-center ${bgClass} ${
                isToday ? "ring-1 ring-brand-400" : ""
              }`}
              title={dp ? `${dp.trade_count} trade(s) | ${dp.total_profit >= 0 ? "+" : ""}${dp.total_profit.toFixed(2)}` : ""}
            >
              <span className={`text-[10px] ${isToday ? "text-brand-400 font-bold" : "text-gray-400"}`}>
                {day}
              </span>
              {dp && (
                <span className={`text-[9px] font-mono font-semibold ${textClass} leading-tight`}>
                  {dp.total_profit >= 0 ? "+" : ""}{dp.total_profit.toFixed(0)}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
