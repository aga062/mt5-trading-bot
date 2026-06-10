"""H4 swing breakout — wider stops, 3-5 day hold, 3R+ TP."""
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

h4_raw = provider.candles["H4"]
h1_raw = provider.candles["H1"]
n = len(h4_raw)

h4_ema20 = h4_raw["close"].ewm(span=20, adjust=False).mean().values
h4_atr = (h4_raw["high"] - h4_raw["low"]).rolling(14).mean().values
h4_body = (h4_raw["close"] - h4_raw["open"]).abs().values
h4_times = h4_raw["datetime"].values

def closest_idx(times, target):
    return int(np.searchsorted(times, np.datetime64(target), side="right")) - 1


def test(tp_mult, sl_mult, max_hold_days, min_body_mult, overextend_mult):
    trades = []
    next_eval = pd.Timestamp(h4_times[0])
    for i in range(10, n):
        T = pd.Timestamp(h4_times[i]) + pd.Timedelta(minutes=240)
        if T < next_eval:
            continue
        clock.now = T

        mid = (h4_raw["high"].iloc[i] + h4_raw["low"].iloc[i]) / 2
        h4_bull = mid > h4_ema20[i]
        side = "BUY" if h4_bull else "SELL"
        atr = h4_atr[i]
        if atr <= 0:
            continue

        # Overextension
        if abs(mid - h4_ema20[i]) > overextend_mult * atr:
            continue

        # Body filter
        body = h4_body[i - 1]
        if body < min_body_mult * atr:
            continue

        cur = h4_raw.iloc[i - 1]
        prev = h4_raw.iloc[i - 2]
        prev2 = h4_raw.iloc[i - 3] if i >= 3 else prev

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
            tp = entry + tp_mult * risk
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
            tp = entry - tp_mult * risk

        result = _simulate_trade(provider, T, side, entry, sl, tp, "MARKET", 60, max_hold_days * 24)
        next_eval = result["exit_time"]
        if result["status"] == "CLOSED" and not np.isnan(result["r"]):
            trades.append(result["r"])

    if len(trades) < 15:
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


print("H4 Swing param search...")
results = []
for tp in [2.0, 2.5, 3.0, 3.5, 4.0]:
    for sl in [0.5, 0.7, 1.0, 1.5]:
        for hold in [2, 3, 5]:
            for body in [0.3, 0.5, 0.7]:
                for oe in [2.0, 3.0, 4.0]:
                    r = test(tp, sl, hold, body, oe)
                    if r:
                        results.append((tp, sl, hold, body, oe, r))
                        print(f"TP={tp} SL={sl} Hold={hold}d body={body} oe={oe} | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f} Total={r['total']:+7.2f}")

if results:
    results.sort(key=lambda x: x[5]["pf"], reverse=True)
    print("\n=== TOP BY PF ===")
    for tp, sl, h, b, o, r in results[:10]:
        print(f"TP={tp} SL={sl} Hold={h}d body={b} oe={o} | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f}")

    results.sort(key=lambda x: x[5]["wr"], reverse=True)
    print("\n=== TOP BY WR ===")
    for tp, sl, h, b, o, r in results[:10]:
        print(f"TP={tp} SL={sl} Hold={h}d body={b} oe={o} | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f}")
