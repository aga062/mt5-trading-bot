"""Fine-tune with fresh provider per test — no state accumulation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.data_loader import HistoricalData, clock
from backtest.harness import run, patch_strategy
import strategies.entry_confirmation as ec

# Save originals
_orig = {
    "MIN_BODY_ATR_MULT": ec.MIN_BODY_ATR_MULT,
    "SL_ATR_MULT": ec.SL_ATR_MULT,
    "TP_R_MULT": ec.TP_R_MULT,
    "OVEREXTEND_ATR_MULT": ec.OVEREXTEND_ATR_MULT,
    "MAX_HOLD_HOURS": ec.MAX_HOLD_HOURS,
}

def test(tp, sl, body, oe, hold):
    # Set params
    ec.MIN_BODY_ATR_MULT = body
    ec.SL_ATR_MULT = sl
    ec.TP_R_MULT = tp
    ec.OVEREXTEND_ATR_MULT = oe
    ec.MAX_HOLD_HOURS = hold

    # Fresh provider + fresh clock
    provider = HistoricalData(symbol="XAUUSD", spread=0.30)
    patch_strategy(provider)
    trades = run(provider, symbol="XAUUSD", eval_tf="H4", progress=False)

    if len(trades) < 10:
        return None
    
    wins = [t for t in trades if t["outcome"] == "TP"]
    losses = [t for t in trades if t["outcome"] == "SL"]
    wr = len(wins) / len(trades)
    pf = sum(t["r"] for t in wins) / abs(sum(t["r"] for t in losses)) if losses else 0
    
    cum = 0.0; peak = 0.0; mdd = 0.0
    for t in trades:
        cum += t["r"]; peak = max(peak, cum); mdd = max(mdd, peak - cum)
    
    sell_wins = len([t for t in wins if t["action"] == "SELL"])
    sell_total = len([t for t in trades if t["action"] == "SELL"])
    buy_wins = len([t for t in wins if t["action"] == "BUY"])
    buy_total = len([t for t in trades if t["action"] == "BUY"])
    
    return {
        "n": len(trades), "wr": wr*100, "pf": pf, "mdd": mdd,
        "total": sum(t["r"] for t in trades),
        "sell_wr": sell_wins/sell_total*100 if sell_total else 0,
        "sell_n": sell_total,
        "buy_wr": buy_wins/buy_total*100 if buy_total else 0,
        "buy_n": buy_total,
    }

# Restore after all tests
import atexit
atexit.register(lambda: [setattr(ec, k, v) for k, v in _orig.items()])


print("Fine-tuning v4 (fresh provider per test)...")
configs = []
for tp in [2.0, 2.5, 3.0]:
    for sl in [0.5, 1.0, 1.5]:
        for body in [0.2, 0.3, 0.5]:
            for oe in [2.0, 3.0, 4.0]:
                for hold in [48, 72, 96]:
                    configs.append((tp, sl, body, oe, hold))

results = []
for tp, sl, body, oe, hold in configs:
    r = test(tp, sl, body, oe, hold)
    if r:
        results.append((tp, sl, body, oe, hold, r))
        print(f"TP={tp} SL={sl} body={body} oe={oe} hold={hold}h | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f} | SELL={r['sell_wr']:.0f}%({r['sell_n']}) BUY={r['buy_wr']:.0f}%({r['buy_n']})")

if results:
    results.sort(key=lambda x: x[5]["pf"], reverse=True)
    print("\n=== TOP BY PF ===")
    for tp, sl, body, oe, hold, r in results[:15]:
        print(f"TP={tp} SL={sl} body={body} oe={oe} hold={hold}h | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f}")

    results.sort(key=lambda x: x[5]["wr"], reverse=True)
    print("\n=== TOP BY WR ===")
    for tp, sl, body, oe, hold, r in results[:15]:
        print(f"TP={tp} SL={sl} body={body} oe={oe} hold={hold}h | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f}")

    balanced = [x for x in results if x[5]["wr"] >= 45 and x[5]["pf"] >= 1.2]
    balanced.sort(key=lambda x: x[5]["mdd"])
    if balanced:
        print("\n=== BALANCED (WR>=45%, PF>=1.2) ===")
        for tp, sl, body, oe, hold, r in balanced[:15]:
            print(f"TP={tp} SL={sl} body={body} oe={oe} hold={hold}h | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f}")

# Restore
for k, v in _orig.items():
    setattr(ec, k, v)
print("\nRestored original params.")
