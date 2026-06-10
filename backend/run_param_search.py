"""
Parametric search over breakout-strategy hyper-parameters.
Tests every combination quickly and prints the top performers.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.data_loader import HistoricalData, clock
from backtest.harness import _simulate_trade
from ai.indicators import compute_ema, compute_atr
import numpy as np
import pandas as pd

provider = HistoricalData(symbol="XAUUSD", spread=0.30)
m5 = provider.candles["M5"]
m1 = provider.candles["M1"]
n = len(m5)

d1_ct = provider.close_times["D1"]
warmup_T = pd.Timestamp(d1_ct[49]) if len(d1_ct) > 50 else m5.iloc[0]["datetime"]
m1_start = pd.Timestamp(m1["datetime"].iloc[0])
start_T = max(warmup_T, m1_start)

def run_variant(tp_mult, sl_mult, min_body_atr, close_pos, overextend_mult):
    trades = []
    next_eval = start_T
    
    for i in range(n):
        T = m5.iloc[i]["datetime"] + pd.Timedelta(minutes=5)
        if T < next_eval:
            continue
        clock.now = T
        
        h1 = provider.get_candles("XAUUSD", "H1", 250)
        m15 = provider.get_candles("XAUUSD", "M15", 120)
        m5c = provider.get_candles("XAUUSD", "M5", 100)
        if h1 is None or m15 is None or m5c is None:
            continue
        if len(h1) < 200 or len(m15) < 50 or len(m5c) < 31:
            continue
        
        h1_ema200 = float(compute_ema(h1["close"], 200).iloc[-1])
        m15_ema50 = float(compute_ema(m15["close"], 50).iloc[-1])
        m5_ema20  = float(compute_ema(m5c.iloc[:-1]["close"], 20).iloc[-1])
        
        mid = (m5c["high"].iloc[-1] + m5c["low"].iloc[-1]) / 2
        h1_bull = mid > h1_ema200
        m15_bull = mid > m15_ema50
        if h1_bull != m15_bull:
            continue
        
        side = "BUY" if h1_bull else "SELL"
        
        # Overextension filter
        if abs(mid - m5_ema20) > overextend_mult * 2.0:
            continue
        
        cur = m5c.iloc[-2]  # last completed
        atr = float(compute_atr(m5c.iloc[:-1], 14).iloc[-1])
        if atr <= 0:
            continue
        
        body = abs(float(cur["close"]) - float(cur["open"]))
        if body < min_body_atr * atr:
            continue
        
        r = float(cur["high"]) - float(cur["low"])
        if side == "BUY":
            if float(cur["close"]) <= float(cur["open"]):
                continue
            pos = (float(cur["close"]) - float(cur["low"])) / r if r > 0 else 0
            if pos < close_pos:
                continue
            entry = float(cur["close"])
            sl = float(cur["low"]) - sl_mult * atr
            risk = entry - sl
            if risk <= 0:
                continue
            tp = entry + tp_mult * risk
        else:
            if float(cur["close"]) >= float(cur["open"]):
                continue
            pos = (float(cur["high"]) - float(cur["close"])) / r if r > 0 else 0
            if pos < close_pos:
                continue
            entry = float(cur["close"])
            sl = float(cur["high"]) + sl_mult * atr
            risk = sl - entry
            if risk <= 0:
                continue
            tp = entry - tp_mult * risk
        
        result = _simulate_trade(provider, T, side, entry, sl, tp, "MARKET", 15, 24)
        next_eval = result["exit_time"]
        if result["status"] == "CLOSED":
            trades.append(result["r"])
    
    if not trades:
        return None
    wins = [r for r in trades if r > 0]
    losses = [r for r in trades if r <= 0]
    wr = len(wins) / len(trades) if trades else 0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_win / gross_loss if gross_loss > 0 else 0
    cum = 0.0; peak = 0.0; mdd = 0.0
    for r in trades:
        cum += r; peak = max(peak, cum); mdd = max(mdd, peak - cum)
    return {
        "n": len(trades),
        "wr": wr * 100,
        "pf": pf,
        "mdd": mdd,
        "total": sum(trades),
        "avg_win": sum(wins)/len(wins) if wins else 0,
        "avg_loss": sum(losses)/len(losses) if losses else 0,
    }

# Search space
params = []
for tp_mult in [1.5, 2.0, 2.5, 3.0]:
    for sl_mult in [0.3, 0.5, 0.7, 1.0]:
        for min_body in [0.4, 0.6, 0.8]:
            for close_pos in [0.5, 0.6, 0.7]:
                for overextend in [1.5, 2.0, 3.0]:
                    params.append((tp_mult, sl_mult, min_body, close_pos, overextend))

print(f"Testing {len(params)} combinations...")
results = []
for idx, (tp, sl, mb, cp, oe) in enumerate(params):
    res = run_variant(tp, sl, mb, cp, oe)
    if res and res["n"] >= 30:
        results.append((tp, sl, mb, cp, oe, res))
    if (idx + 1) % 50 == 0:
        print(f"  ...{idx+1}/{len(params)}")

results.sort(key=lambda x: x[5]["pf"], reverse=True)
print("\n=== TOP 10 BY PROFIT FACTOR ===")
print(f"{'TP':>4} {'SL':>4} {'Body':>5} {'Close':>6} {'Over':>5} | {'N':>5} {'WR%':>6} {'PF':>5} {'MaxDD':>7} {'TotalR':>8}")
for tp, sl, mb, cp, oe, r in results[:10]:
    print(f"{tp:4.1f} {sl:4.1f} {mb:5.1f} {cp:6.1f} {oe:5.1f} | {r['n']:5d} {r['wr']:6.1f} {r['pf']:5.2f} {r['mdd']:7.2f} {r['total']:+8.2f}")

results.sort(key=lambda x: x[5]["wr"], reverse=True)
print("\n=== TOP 10 BY WIN RATE (n>=30) ===")
print(f"{'TP':>4} {'SL':>4} {'Body':>5} {'Close':>6} {'Over':>5} | {'N':>5} {'WR%':>6} {'PF':>5} {'MaxDD':>7} {'TotalR':>8}")
for tp, sl, mb, cp, oe, r in results[:10]:
    print(f"{tp:4.1f} {sl:4.1f} {mb:5.1f} {cp:6.1f} {oe:5.1f} | {r['n']:5d} {r['wr']:6.1f} {r['pf']:5.2f} {r['mdd']:7.2f} {r['total']:+8.2f}")

# Best balanced: high PF, WR>40, low DD
balanced = [x for x in results if x[5]["wr"] >= 40 and x[5]["pf"] >= 1.2]
balanced.sort(key=lambda x: x[5]["mdd"])
if balanced:
    print("\n=== BEST BALANCED (WR>=40%, PF>=1.2) ===")
    print(f"{'TP':>4} {'SL':>4} {'Body':>5} {'Close':>6} {'Over':>5} | {'N':>5} {'WR%':>6} {'PF':>5} {'MaxDD':>7} {'TotalR':>8}")
    for tp, sl, mb, cp, oe, r in balanced[:10]:
        print(f"{tp:4.1f} {sl:4.1f} {mb:5.1f} {cp:6.1f} {oe:5.1f} | {r['n']:5d} {r['wr']:6.1f} {r['pf']:5.2f} {r['mdd']:7.2f} {r['total']:+8.2f}")
