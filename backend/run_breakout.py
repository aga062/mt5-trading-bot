"""Quick breakout strategy test."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.data_loader import HistoricalData, clock
from backtest.harness import _simulate_trade
import numpy as np
import pandas as pd

provider = HistoricalData(symbol="XAUUSD", spread=0.30)
m5 = provider.candles["M5"]
m1 = provider.candles["M1"]
n = len(m5)

# Warmup
d1_ct = provider.close_times["D1"]
warmup_T = pd.Timestamp(d1_ct[49]) if len(d1_ct) > 50 else m5.iloc[0]["datetime"]
m1_start = pd.Timestamp(m1["datetime"].iloc[0])
start_T = max(warmup_T, m1_start)

trades = []
next_eval = start_T

for i in range(n):
    T = m5.iloc[i]["datetime"] + pd.Timedelta(minutes=5)
    if T < next_eval:
        continue
    clock.now = T
    
    # Get data
    h1 = provider.get_candles("XAUUSD", "H1", 50)
    m15 = provider.get_candles("XAUUSD", "M15", 30)
    m5c = provider.get_candles("XAUUSD", "M5", 20)
    if h1 is None or m15 is None or m5c is None:
        continue
    
    # H1 bias
    if len(h1) < 30:
        continue
    h1_close = h1["close"].values
    ema200_h1 = sum(h1_close[-200:]) / 200 if len(h1_close) >= 200 else sum(h1_close) / len(h1_close)
    
    # M15 bias
    m15_close = m15["close"].values
    ema50_m15 = sum(m15_close[-50:]) / 50 if len(m15_close) >= 50 else sum(m15_close) / len(m15_close)
    
    mid = (m5c["high"].iloc[-1] + m5c["low"].iloc[-1]) / 2
    h1_bull = mid > ema200_h1
    m15_bull = mid > ema50_m15
    
    if h1_bull != m15_bull:
        continue  # No alignment
    
    side = "BUY" if h1_bull else "SELL"
    
    # M5 momentum: last candle body > 0.6 ATR and closes in the direction of trend
    cur = m5c.iloc[-2]  # last completed candle (excluding forming)
    prev = m5c.iloc[-3] if len(m5c) >= 3 else cur
    
    atr = 0
    for k in range(-14, 0):
        atr += m5c.iloc[k]["high"] - m5c.iloc[k]["low"]
    atr /= 14
    
    body = abs(float(cur["close"]) - float(cur["open"]))
    if body < 0.6 * atr:
        continue
    
    if side == "BUY":
        if float(cur["close"]) <= float(cur["open"]):
            continue  # Not bullish
        # Close in upper 40% of range
        r = float(cur["high"]) - float(cur["low"])
        pos = (float(cur["close"]) - float(cur["low"])) / r if r > 0 else 0
        if pos < 0.6:
            continue
        entry = float(cur["close"])  # enter at close of momentum candle
        sl = float(cur["low"]) - 0.3 * atr
        risk = entry - sl
        if risk <= 0:
            continue
        tp = entry + 1.5 * risk
    else:
        if float(cur["close"]) >= float(cur["open"]):
            continue
        r = float(cur["high"]) - float(cur["low"])
        pos = (float(cur["high"]) - float(cur["close"])) / r if r > 0 else 0
        if pos < 0.6:
            continue
        entry = float(cur["close"])
        sl = float(cur["high"]) + 0.3 * atr
        risk = sl - entry
        if risk <= 0:
            continue
        tp = entry - 1.5 * risk
    
    result = _simulate_trade(provider, T, side, entry, sl, tp, "MARKET", 15, 24)
    next_eval = result["exit_time"]
    
    if result["status"] in ("CLOSED", "CANCELLED"):
        trades.append({
            "time": str(T), "action": side, "tag": "MOMENTUM",
            "entry": round(entry, 3), "sl": round(sl, 3), "tp": round(tp, 3),
            "status": result["status"], "outcome": result["outcome"],
            "exit": result["exit"], "r": result["r"],
        })

# Report
if trades:
    closed = [t for t in trades if t["status"] == "CLOSED"]
    rs = [t["r"] for t in closed]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    wr = len(wins)/len(rs)*100 if rs else 0
    pf = sum(wins)/abs(sum(losses)) if losses else 0
    cum = 0; peak = 0; mdd = 0
    for r in rs:
        cum += r; peak = max(peak, cum); mdd = max(mdd, peak - cum)
    print(f"Trades: {len(closed)} | WR: {wr:.1f}% | PF: {pf:.2f} | MaxDD: {mdd:.2f}R")
    print(f"Avg Win: +{sum(wins)/len(wins):.2f}R | Avg Loss: {sum(losses)/len(losses):.2f}R")
    print(f"Total R: {sum(rs):+.2f}")
    import csv
    out = Path(__file__).resolve().parent / "backtest" / "data" / "XAUUSD_trades.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
        w.writeheader(); w.writerows(trades)
    print(f"Saved to {out}")
else:
    print("No trades")
