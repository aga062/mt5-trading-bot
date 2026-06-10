"""Fine-tune H4 swing — fixed ATR timing bug."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.data_loader import HistoricalData, clock
from backtest.harness import _simulate_trade, patch_strategy
from ai.indicators import compute_ema
import numpy as np
import pandas as pd

provider = HistoricalData(symbol="XAUUSD", spread=0.30)
patch_strategy(provider)

h4_raw = provider.candles["H4"]
h1_raw = provider.candles["H1"]
n = len(h4_raw)

h4_ema20 = h4_raw["close"].ewm(span=20, adjust=False).mean().values
h4_times = h4_raw["datetime"].values
h1_ema50 = h1_raw["close"].ewm(span=50, adjust=False).mean().values

def true_atr(df, length=14):
    """Compute ATR like the strategy does."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    tr = []
    for i in range(1, len(df)):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i-1])
        lc = abs(low[i] - close[i-1])
        tr.append(max(hl, hc, lc))
    atr = []
    for i in range(len(tr)):
        if i < length - 1:
            atr.append(np.mean(tr[:i+1]))
        elif i == length - 1:
            atr.append(np.mean(tr[:length]))
        else:
            atr.append((atr[-1] * (length - 1) + tr[i]) / length)
    # Pad with NaN for the first bar (no TR)
    return [np.nan] + atr

# Pre-compute ATR for each possible "completed bars" state
# For a given i, completed bars are h4_raw.iloc[:i]
# We'll cache ATR values

atr_cache = {}
for i in range(5, n):
    sub = h4_raw.iloc[:i]
    if len(sub) >= 15:
        atr_vals = true_atr(sub, 14)
        atr_cache[i] = atr_vals[-1] if len(atr_vals) > 0 else np.nan
    else:
        atr_cache[i] = np.nan


def test(body_mult, sl_mult, tp_mult, max_hold_days, overextend_mult,
         min_body_range, session_filter, skip_buys, skip_sells):
    trades = []
    next_eval = pd.Timestamp(h4_times[0])
    
    for i in range(5, n):
        T = pd.Timestamp(h4_times[i]) + pd.Timedelta(minutes=240)
        if T < next_eval:
            continue
        clock.now = T

        mid = (h4_raw["high"].iloc[i] + h4_raw["low"].iloc[i]) / 2
        h4_bull = mid > h4_ema20[i]
        side = "BUY" if h4_bull else "SELL"
        
        if side == "BUY" and skip_buys:
            continue
        if side == "SELL" and skip_sells:
            continue

        atr = atr_cache.get(i, np.nan)
        if np.isnan(atr) or atr <= 0:
            continue

        if abs(mid - h4_ema20[i]) > overextend_mult * atr:
            continue

        # Session filter
        if session_filter:
            hour = T.hour
            if not (8 <= hour <= 17):
                continue

        cur = h4_raw.iloc[i - 1]
        prev = h4_raw.iloc[i - 2]
        prev2 = h4_raw.iloc[i - 3] if i >= 3 else prev

        body = abs(float(cur["close"]) - float(cur["open"]))
        if body < body_mult * atr:
            continue

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


print("Fine-tuning H4 swing (v2, fixed ATR)...")
results = []
configs = []
for tp in [2.0, 2.5, 3.0]:
    for sl in [0.5, 1.0, 1.5]:
        for body in [0.2, 0.3, 0.5]:
            for oe in [2.0, 3.0, 4.0]:
                for min_br in [0.0, 0.3, 0.5]:
                    for sess in [False, True]:
                        for sb, ss in [(False, False), (False, True), (True, False)]:
                            if sb and ss:
                                continue
                            r = test(body, sl, tp, 3, oe, min_br, sess, sb, ss)
                            if r and r["n"] >= 10:
                                results.append((tp, sl, body, oe, min_br, sess, sb, ss, r))
                                sess_str = "SESS" if sess else "ALL"
                                dir_str = "BOTH" if not sb and not ss else ("BUY" if not sb else "SELL")
                                print(f"TP={tp} SL={sl} body={body} oe={oe} br={min_br} {sess_str} {dir_str} | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f} | SELL={r['sell_wr']:.0f}%({r['sell_n']}) BUY={r['buy_wr']:.0f}%({r['buy_n']})")

if results:
    results.sort(key=lambda x: x[8]["pf"], reverse=True)
    print("\n=== TOP BY PF ===")
    for tp, sl, body, oe, br, sess, sb, ss, r in results[:15]:
        s = "SESS" if sess else "ALL"
        d = "BOTH" if not sb and not ss else ("BUY" if not sb else "SELL")
        print(f"TP={tp} SL={sl} body={body} oe={oe} br={br} {s} {d} | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f}")

    results.sort(key=lambda x: x[8]["wr"], reverse=True)
    print("\n=== TOP BY WR ===")
    for tp, sl, body, oe, br, sess, sb, ss, r in results[:15]:
        s = "SESS" if sess else "ALL"
        d = "BOTH" if not sb and not ss else ("BUY" if not sb else "SELL")
        print(f"TP={tp} SL={sl} body={body} oe={oe} br={br} {s} {d} | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f}")

    balanced = [x for x in results if x[8]["wr"] >= 50 and x[8]["pf"] >= 1.3 and x[8]["n"] >= 15]
    balanced.sort(key=lambda x: x[8]["mdd"])
    if balanced:
        print("\n=== BALANCED (WR>=50%, PF>=1.3, N>=15) ===")
        for tp, sl, body, oe, br, sess, sb, ss, r in balanced[:15]:
            s = "SESS" if sess else "ALL"
            d = "BOTH" if not sb and not ss else ("BUY" if not sb else "SELL")
            print(f"TP={tp} SL={sl} body={body} oe={oe} br={br} {s} {d} | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f}")
