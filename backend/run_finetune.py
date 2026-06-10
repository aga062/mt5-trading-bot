"""Fine-tune H4 swing breakout with filters on live backtest harness."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.data_loader import HistoricalData, clock
from backtest.harness import run, patch_strategy, _simulate_trade
from backtest.report import build_report
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

h1_ema50 = h1_raw["close"].ewm(span=50, adjust=False).mean().values

def test(body_mult, sl_mult, tp_mult, max_hold_days, overextend_mult,
         min_atr, min_body_range, require_both_dirs, session_filter):
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
        if atr <= 0 or atr < min_atr:
            continue

        if abs(mid - h4_ema20[i]) > overextend_mult * atr:
            continue

        # Session filter: only trade during London/NY overlap (13-17 UTC) or all
        if session_filter:
            hour = T.hour
            if not (8 <= hour <= 17):  # London opens 8, NY closes 17
                continue

        body = h4_body[i - 1]
        if body < body_mult * atr:
            continue

        cur = h4_raw.iloc[i - 1]
        prev = h4_raw.iloc[i - 2]
        prev2 = h4_raw.iloc[i - 3] if i >= 3 else prev

        rng = float(cur["high"]) - float(cur["low"])
        if rng > 0 and body / rng < min_body_range:
            continue

        # H1 confirmation
        h1_idx = min(i * 4, len(h1_raw) - 1)
        h1_bull = mid > h1_ema50[min(h1_idx, len(h1_ema50)-1)]
        if h1_bull != h4_bull:
            continue

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
            trades.append({"r": result["r"], "side": side})

    if len(trades) < 10:
        return None
    
    wins = [t["r"] for t in trades if t["r"] > 0]
    losses = [t["r"] for t in trades if t["r"] <= 0]
    wr = len(wins) / len(trades)
    pf = sum(wins) / abs(sum(losses)) if losses else 0
    cum = 0.0; peak = 0.0; mdd = 0.0
    for t in trades:
        cum += t["r"]; peak = max(peak, cum); mdd = max(mdd, peak - cum)
    
    sell_wins = len([t for t in trades if t["side"] == "SELL" and t["r"] > 0])
    sell_total = len([t for t in trades if t["side"] == "SELL"])
    buy_wins = len([t for t in trades if t["side"] == "BUY" and t["r"] > 0])
    buy_total = len([t for t in trades if t["side"] == "BUY"])
    
    return {
        "n": len(trades), "wr": wr*100, "pf": pf, "mdd": mdd,
        "total": sum(t["r"] for t in trades),
        "sell_wr": sell_wins/sell_total*100 if sell_total else 0,
        "sell_n": sell_total,
        "buy_wr": buy_wins/buy_total*100 if buy_total else 0,
        "buy_n": buy_total,
    }


print("Fine-tuning H4 swing...")
results = []
for tp in [2.0, 2.5, 3.0]:
    for sl in [0.5, 1.0, 1.5]:
        for body in [0.2, 0.3, 0.5]:
            for oe in [2.0, 3.0, 4.0]:
                for min_br in [0.3, 0.5, 0.7]:
                    for sess in [False, True]:
                        r = test(body, sl, tp, 3, oe, 0.0, min_br, False, sess)
                        if r and r["n"] >= 10:
                            results.append((tp, sl, body, oe, min_br, sess, r))
                            sess_str = "SESS" if sess else "ALL"
                            print(f"TP={tp} SL={sl} body={body} oe={oe} br={min_br} {sess_str} | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f} SELL={r['sell_wr']:.0f}%({r['sell_n']}) BUY={r['buy_wr']:.0f}%({r['buy_n']})")

if results:
    # Best overall
    results.sort(key=lambda x: x[6]["pf"], reverse=True)
    print("\n=== TOP BY PF ===")
    for tp, sl, body, oe, br, sess, r in results[:15]:
        s = "SESS" if sess else "ALL"
        print(f"TP={tp} SL={sl} body={body} oe={oe} br={br} {s} | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f}")

    # Best WR
    results.sort(key=lambda x: x[6]["wr"], reverse=True)
    print("\n=== TOP BY WR ===")
    for tp, sl, body, oe, br, sess, r in results[:15]:
        s = "SESS" if sess else "ALL"
        print(f"TP={tp} SL={sl} body={body} oe={oe} br={br} {s} | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f}")

    # Best with WR >= 50 and PF >= 1.3
    balanced = [x for x in results if x[6]["wr"] >= 50 and x[6]["pf"] >= 1.3]
    balanced.sort(key=lambda x: x[6]["mdd"])
    if balanced:
        print("\n=== BALANCED (WR>=50%, PF>=1.3) ===")
        for tp, sl, body, oe, br, sess, r in balanced[:15]:
            s = "SESS" if sess else "ALL"
            print(f"TP={tp} SL={sl} body={body} oe={oe} br={br} {s} | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f}")
