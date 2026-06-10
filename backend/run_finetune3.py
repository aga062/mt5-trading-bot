"""Fine-tune by calling real evaluate_entry with monkey-patched params."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.data_loader import HistoricalData, clock
from backtest.harness import run, patch_strategy
from backtest.report import build_report
import strategies.entry_confirmation as ec

provider = HistoricalData(symbol="XAUUSD", spread=0.30)

# Save originals
_orig_params = {
    "MIN_BODY_ATR_MULT": ec.MIN_BODY_ATR_MULT,
    "SL_ATR_MULT": ec.SL_ATR_MULT,
    "TP_R_MULT": ec.TP_R_MULT,
    "OVEREXTEND_ATR_MULT": ec.OVEREXTEND_ATR_MULT,
    "MAX_HOLD_HOURS": ec.MAX_HOLD_HOURS,
}

def set_params(body, sl, tp, oe, hold):
    ec.MIN_BODY_ATR_MULT = body
    ec.SL_ATR_MULT = sl
    ec.TP_R_MULT = tp
    ec.OVEREXTEND_ATR_MULT = oe
    ec.MAX_HOLD_HOURS = hold

def restore():
    for k, v in _orig_params.items():
        setattr(ec, k, v)


print("Fine-tuning via real strategy...")
results = []

for tp in [2.0, 2.5, 3.0, 3.5]:
    for sl in [0.3, 0.5, 1.0, 1.5]:
        for body in [0.2, 0.3, 0.5]:
            for oe in [2.0, 3.0, 4.0]:
                for hold in [48, 72, 96]:
                    set_params(body, sl, tp, oe, hold)
                    patch_strategy(provider)
                    trades = run(provider, symbol="XAUUSD", eval_tf="H4", progress=False)
                    
                    if len(trades) < 10:
                        continue
                    
                    wins = [t for t in trades if t["outcome"] == "TP"]
                    losses = [t for t in trades if t["outcome"] == "SL"]
                    wr = len(wins) / len(trades)
                    
                    win_r = sum(t["r"] for t in wins)
                    loss_r = abs(sum(t["r"] for t in losses))
                    pf = win_r / loss_r if loss_r > 0 else 0
                    
                    cum = 0.0; peak = 0.0; mdd = 0.0
                    for t in trades:
                        cum += t["r"]; peak = max(peak, cum); mdd = max(mdd, peak - cum)
                    
                    sell_wins = len([t for t in wins if t["action"] == "SELL"])
                    sell_total = len([t for t in trades if t["action"] == "SELL"])
                    buy_wins = len([t for t in wins if t["action"] == "BUY"])
                    buy_total = len([t for t in trades if t["action"] == "BUY"])
                    
                    results.append({
                        "tp": tp, "sl": sl, "body": body, "oe": oe, "hold": hold,
                        "n": len(trades), "wr": wr*100, "pf": pf, "mdd": mdd,
                        "total": sum(t["r"] for t in trades),
                        "sell_wr": sell_wins/sell_total*100 if sell_total else 0,
                        "sell_n": sell_total,
                        "buy_wr": buy_wins/buy_total*100 if buy_total else 0,
                        "buy_n": buy_total,
                    })
                    print(f"TP={tp} SL={sl} body={body} oe={oe} hold={hold}h | N={len(trades):3d} WR={wr*100:5.1f}% PF={pf:5.2f} MDD={mdd:6.2f} | SELL={sell_wins/sell_total*100 if sell_total else 0:.0f}%({sell_total}) BUY={buy_wins/buy_total*100 if buy_total else 0:.0f}%({buy_total})")

restore()

if results:
    results.sort(key=lambda x: x["pf"], reverse=True)
    print("\n=== TOP BY PF ===")
    for r in results[:20]:
        print(f"TP={r['tp']} SL={r['sl']} body={r['body']} oe={r['oe']} hold={r['hold']}h | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f}")

    results.sort(key=lambda x: x["wr"], reverse=True)
    print("\n=== TOP BY WR ===")
    for r in results[:20]:
        print(f"TP={r['tp']} SL={r['sl']} body={r['body']} oe={r['oe']} hold={r['hold']}h | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f}")

    balanced = [r for r in results if r["wr"] >= 45 and r["pf"] >= 1.2]
    balanced.sort(key=lambda x: x["mdd"])
    if balanced:
        print("\n=== BALANCED (WR>=45%, PF>=1.2) ===")
        for r in balanced[:20]:
            print(f"TP={r['tp']} SL={r['sl']} body={r['body']} oe={r['oe']} hold={r['hold']}h | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f}")
