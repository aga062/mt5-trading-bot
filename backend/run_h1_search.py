"""Fast param search for H1 momentum breakout."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.data_loader import HistoricalData, clock
from backtest.harness import _simulate_trade, patch_strategy
from ai.indicators import compute_ema, compute_atr
import numpy as np
import pandas as pd

provider = HistoricalData(symbol="XAUUSD", spread=0.30)
patch_strategy(provider)

h1_raw = provider.candles["H1"]
h4_raw = provider.candles["H4"]
d1_raw = provider.candles["D1"]

# Pre-compute indicators
h1_ema50 = h1_raw["close"].ewm(span=50, adjust=False).mean().values
h4_ema20 = h4_raw["close"].ewm(span=20, adjust=False).mean().values
h1_atr = (h1_raw["high"] - h1_raw["low"]).rolling(14).mean().values
h1_body = (h1_raw["close"] - h1_raw["open"]).abs().values

h1_times = h1_raw["datetime"].values
h4_times = h4_raw["datetime"].values
d1_times = d1_raw["datetime"].values

def closest_idx(times, target):
    return int(np.searchsorted(times, np.datetime64(target), side="right")) - 1

n = len(h1_raw)

# Swing detection for key levels
def _swings(hi, lo, lookback=3):
    highs, lows = [], []
    for i in range(lookback, len(hi) - lookback):
        if all(hi[i] >= hi[i - j] and hi[i] >= hi[i + j] for j in range(1, lookback + 1)):
            highs.append(float(hi[i]))
        if all(lo[i] <= lo[i - j] and lo[i] <= lo[i + j] for j in range(1, lookback + 1)):
            lows.append(float(lo[i]))
    return highs, lows

h1_hi, h1_lo = _swings(h1_raw["high"].values, h1_raw["low"].values, 3)

# D1 PDL/PDH
pd_levels = {}
for side in ["BUY", "SELL"]:
    pd_levels[side] = []
    if len(d1_raw) >= 3:
        pd_bar = d1_raw.iloc[-2]
        pd_levels[side].append(float(pd_bar["low"] if side == "BUY" else pd_bar["high"]))


def test(body_mult, sl_mult, min_rr, overextend_mult):
    trades = []
    next_eval = pd.Timestamp(h1_times[0])
    for i in range(5, n):
        T = pd.Timestamp(h1_times[i]) + pd.Timedelta(minutes=60)
        if T < next_eval:
            continue
        clock.now = T

        h4_i = closest_idx(h4_times, T)
        if h4_i < 0:
            continue

        mid = (h1_raw["high"].iloc[i] + h1_raw["low"].iloc[i]) / 2
        h4_bull = mid > h4_ema20[h4_i]
        h1_bull = mid > h1_ema50[i]
        if h4_bull != h1_bull:
            continue

        side = "BUY" if h4_bull else "SELL"
        atr = h1_atr[i]
        if atr <= 0:
            continue

        if abs(mid - h1_ema50[i]) > overextend_mult * atr:
            continue

        body = h1_body[i - 1]
        if body < body_mult * atr:
            continue

        cur = h1_raw.iloc[i - 1]
        prev = h1_raw.iloc[i - 2]
        prev2 = h1_raw.iloc[i - 3] if i >= 3 else prev

        if side == "BUY":
            close = float(cur["close"])
            if close <= float(cur["open"]):
                continue
            prior_high = max(float(prev["high"]), float(prev2["high"]))
            if close <= prior_high:
                continue
            entry = close
            sl = float(cur["low"]) - sl_mult * atr
            risk = entry - sl
            if risk <= 0:
                continue
            # TP = nearest H1 swing high above entry, or min_rr
            cands = [v for v in h1_hi if v > entry + max(risk, atr)]
            tp = min(cands) if cands else entry + min_rr * risk
            if (tp - entry) / risk < min_rr:
                continue
        else:
            close = float(cur["close"])
            if close >= float(cur["open"]):
                continue
            prior_low = min(float(prev["low"]), float(prev2["low"]))
            if close >= prior_low:
                continue
            entry = close
            sl = float(cur["high"]) + sl_mult * atr
            risk = sl - entry
            if risk <= 0:
                continue
            cands = [v for v in h1_lo if v < entry - max(risk, atr)]
            tp = max(cands) if cands else entry - min_rr * risk
            if (entry - tp) / risk < min_rr:
                continue

        result = _simulate_trade(provider, T, side, entry, sl, tp, "MARKET", 15, 24)
        next_eval = result["exit_time"]
        if result["status"] == "CLOSED" and not np.isnan(result["r"]):
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


print("H1 param search...")
results = []
for body in [0.3, 0.5, 0.7, 1.0]:
    for sl in [0.3, 0.5, 0.7, 1.0]:
        for rr in [1.5, 2.0, 2.5, 3.0]:
            for oe in [2.0, 3.0, 4.0]:
                r = test(body, sl, rr, oe)
                if r:
                    results.append((body, sl, rr, oe, r))
                    print(f"body={body} sl={sl} rr={rr} oe={oe} | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f} Total={r['total']:+7.2f}")

results.sort(key=lambda x: x[4]["pf"], reverse=True)
print("\n=== TOP BY PF ===")
for b, s, r, o, res in results[:10]:
    print(f"body={b} sl={s} rr={r} oe={o} | N={res['n']:3d} WR={res['wr']:5.1f}% PF={res['pf']:5.2f} MDD={res['mdd']:6.2f}")

results.sort(key=lambda x: x[4]["wr"], reverse=True)
print("\n=== TOP BY WR ===")
for b, s, r, o, res in results[:10]:
    print(f"body={b} sl={s} rr={r} oe={o} | N={res['n']:3d} WR={res['wr']:5.1f}% PF={res['pf']:5.2f} MDD={res['mdd']:6.2f}")

# Best balanced
balanced = [x for x in results if x[4]["wr"] >= 45 and x[4]["pf"] >= 1.3]
balanced.sort(key=lambda x: x[4]["mdd"])
if balanced:
    print("\n=== BALANCED (WR>=45%, PF>=1.3) ===")
    for b, s, r, o, res in balanced[:10]:
        print(f"body={b} sl={s} rr={r} oe={o} | N={res['n']:3d} WR={res['wr']:5.1f}% PF={res['pf']:5.2f} MDD={res['mdd']:6.2f}")
