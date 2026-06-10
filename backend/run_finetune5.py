"""Fine-tune: session window × TP × direction filter."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.data_loader import HistoricalData
from backtest.harness import run, patch_strategy
import strategies.entry_confirmation as ec

# Save originals
_orig = {
    "TP_R_MULT": ec.TP_R_MULT,
    "SESSION_WINDOWS": list(ec.SESSION_WINDOWS),
    "SESSION_FILTER": ec.SESSION_FILTER,
}

def test(tp, session_windows, skip_buys, skip_sells):
    ec.TP_R_MULT = tp
    ec.SESSION_WINDOWS = session_windows
    ec.SESSION_FILTER = True

    provider = HistoricalData(symbol="XAUUSD", spread=0.30)
    patch_strategy(provider)
    trades = run(provider, symbol="XAUUSD", eval_tf="H4", progress=False)

    if len(trades) < 5:
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

    # Apply directional skip post-filter
    filtered = [t for t in trades if not (t["action"] == "BUY" and skip_buys) and not (t["action"] == "SELL" and skip_sells)]

    if len(filtered) >= 5:
        fw = [t for t in filtered if t["outcome"] == "TP"]
        fl = [t for t in filtered if t["outcome"] == "SL"]
        fwr = len(fw) / len(filtered)
        fpf = sum(t["r"] for t in fw) / abs(sum(t["r"] for t in fl)) if fl else 0
        fc = 0.0; fp = 0.0; fm = 0.0
        for t in filtered:
            fc += t["r"]; fp = max(fp, fc); fm = max(fm, fp - fc)
    else:
        fwr = fpf = fm = 0
        filtered = []

    return {
        "n": len(trades), "wr": wr*100, "pf": pf, "mdd": mdd,
        "total": sum(t["r"] for t in trades),
        "sell_wr": sell_wins/sell_total*100 if sell_total else 0,
        "sell_n": sell_total,
        "buy_wr": buy_wins/buy_total*100 if buy_total else 0,
        "buy_n": buy_total,
        "fn": len(filtered), "fwr": fwr*100, "fpf": fpf, "fmdd": fm,
        "ftotal": sum(t["r"] for t in filtered),
    }


print("Fine-tuning: session × TP × direction...")
results = []

session_configs = [
    [(8, 9), (13, 17)],
    [(8, 10), (13, 18)],
    [(8, 10), (13, 17)],
    [(8, 9), (13, 18)],
    [(7, 10), (13, 18)],
    [(8, 11), (13, 19)],
]

tp_values = [2.5, 3.0, 3.5, 4.0, 5.0]
dir_configs = [(False, False), (False, True), (True, False)]

for sess in session_configs:
    for tp in tp_values:
        for sb, ss in dir_configs:
            r = test(tp, sess, sb, ss)
            if r and r["n"] >= 5:
                results.append((tp, sess, sb, ss, r))
                sess_str = "+".join(f"{s}-{e}" for s, e in sess)
                dir_str = "BOTH" if not sb and not ss else ("BUY" if not sb else "SELL")
                print(f"TP={tp} sess={sess_str} dir={dir_str} | N={r['n']:3d} WR={r['wr']:5.1f}% PF={r['pf']:5.2f} MDD={r['mdd']:6.2f} | "
                      f"F_N={r['fn']:3d} F_WR={r['fwr']:5.1f}% F_PF={r['fpf']:5.2f} F_MDD={r['fmdd']:6.2f} | "
                      f"SELL={r['sell_wr']:.0f}%({r['sell_n']}) BUY={r['buy_wr']:.0f}%({r['buy_n']})")

if results:
    results.sort(key=lambda x: x[4]["fpf"], reverse=True)
    print("\n=== TOP BY FILTERED PF ===")
    for tp, sess, sb, ss, r in results[:20]:
        s = "+".join(f"{a}-{b}" for a, b in sess)
        d = "BOTH" if not sb and not ss else ("BUY" if not sb else "SELL")
        print(f"TP={tp} sess={s} dir={d} | N={r['fn']:3d} WR={r['fwr']:5.1f}% PF={r['fpf']:5.2f} MDD={r['fmdd']:6.2f} Total={r['ftotal']:.2f}R")

    balanced = [x for x in results if x[4]["fwr"] >= 55 and x[4]["fpf"] >= 2.0 and x[4]["fn"] >= 8]
    balanced.sort(key=lambda x: x[4]["fmdd"])
    if balanced:
        print("\n=== BALANCED (F_WR>=55%, F_PF>=2.0, F_N>=8) ===")
        for tp, sess, sb, ss, r in balanced[:15]:
            s = "+".join(f"{a}-{b}" for a, b in sess)
            d = "BOTH" if not sb and not ss else ("BUY" if not sb else "SELL")
            print(f"TP={tp} sess={s} dir={d} | N={r['fn']:3d} WR={r['fwr']:5.1f}% PF={r['fpf']:5.2f} MDD={r['fmdd']:6.2f} Total={r['ftotal']:.2f}R")

# Restore
for k, v in _orig.items():
    setattr(ec, k, v)
print("\nRestored original params.")
