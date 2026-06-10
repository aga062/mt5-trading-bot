"""Fast focused param search — pre-computes all indicators."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.data_loader import HistoricalData, clock
from backtest.harness import _simulate_trade
from ai.indicators import compute_ema, compute_atr
import numpy as np
import pandas as pd

provider = HistoricalData(symbol="XAUUSD", spread=0.30)
m5_raw = provider.candles["M5"]
m1 = provider.candles["M1"]

# Pre-compute everything on full history
h1_raw = provider.candles["H1"]
m15_raw = provider.candles["M15"]

h1_ema200 = h1_raw["close"].ewm(span=200, adjust=False).mean().values
m15_ema50 = m15_raw["close"].ewm(span=50, adjust=False).mean().values
m5_ema20  = m5_raw["close"].ewm(span=20, adjust=False).mean().values
m5_atr = (m5_raw["high"] - m5_raw["low"]).rolling(14).mean().values
m5_body = (m5_raw["close"] - m5_raw["open"]).abs().values
m5_range = m5_raw["high"] - m5_raw["low"]

# Build time-indexed lookups for H1 and M15
h1_times = h1_raw["datetime"].values
m15_times = m15_raw["datetime"].values
m5_times = m5_raw["datetime"].values

def closest_idx(times, target):
    return int(np.searchsorted(times, np.datetime64(target), side="right")) - 1

# Build completed-bar indices at each M5 close time
n = len(m5_raw)
results = []

def test(tp_mult, sl_mult):
    trades = []
    next_eval = m5_times[0]
    for i in range(5, n):
        T = pd.Timestamp(m5_times[i]) + pd.Timedelta(minutes=5)
        if T < next_eval:
            continue
        clock.now = T
        
        h1_i = closest_idx(h1_times, T)
        m15_i = closest_idx(m15_times, T)
        if h1_i < 0 or m15_i < 0:
            continue
        
        mid = (m5_raw["high"].iloc[i] + m5_raw["low"].iloc[i]) / 2
        h1_bull = mid > h1_ema200[h1_i]
        m15_bull = mid > m15_ema50[m15_i]
        if h1_bull != m15_bull:
            continue
        
        side = "BUY" if h1_bull else "SELL"
        
        # Overextension filter
        if abs(mid - m5_ema20[i]) > 2.0 * m5_atr[i]:
            continue
        
        cur = m5_raw.iloc[i - 1]  # last completed M5 bar before T
        atr = m5_atr[i]
        if atr <= 0 or m5_body[i - 1] < 0.6 * atr:
            continue
        
        rng = float(cur["high"]) - float(cur["low"])
        if side == "BUY":
            if float(cur["close"]) <= float(cur["open"]):
                continue
            pos = (float(cur["close"]) - float(cur["low"])) / rng if rng > 0 else 0
            if pos < 0.6:
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
            pos = (float(cur["high"]) - float(cur["close"])) / rng if rng > 0 else 0
            if pos < 0.6:
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
    
    if len(trades) < 20:
        return None
    wins = [r for r in trades if r > 0]
    losses = [r for r in trades if r <= 0]
    wr = len(wins) / len(trades)
    pf = sum(wins) / abs(sum(losses)) if losses else 0
    cum = 0.0; peak = 0.0; mdd = 0.0
    for r in trades:
        cum += r; peak = max(peak, cum); mdd = max(mdd, peak - cum)
    return {"n": len(trades), "wr": wr*100, "pf": pf, "mdd": mdd,
            "total": sum(trades), "avg_win": sum(wins)/len(wins), "avg_loss": sum(losses)/len(losses)}

print("Running focused search...")
for tp in [1.5, 2.0, 2.5, 3.0]:
    for sl in [0.3, 0.5, 0.7, 1.0]:
        r = test(tp, sl)
        if r:
            results.append((tp, sl, r))
            print(f"TP={tp} SL={sl} | N={r['n']:4d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:7.2f} Total={r['total']:+7.2f}")

results.sort(key=lambda x: x[2]["pf"], reverse=True)
print("\n=== TOP BY PROFIT FACTOR ===")
for tp, sl, r in results[:5]:
    print(f"TP={tp} SL={sl} | N={r['n']:4d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:7.2f} Total={r['total']:+7.2f}")
