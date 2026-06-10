"""Quick backtest runner."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.data_loader import HistoricalData
from backtest.harness import run
from backtest.report import build_report
from ai.regime_detector import clear_cache

clear_cache()  # fresh regime cache per backtest
provider = HistoricalData(symbol="XAUUSD", spread=0.30)
print("Replaying H1 50-EMA + M5 Pullback + Key-Zone TP + Profit Locks...")
trades = run(provider, symbol="XAUUSD", eval_tf="M5")
report = build_report(trades, risk_per_trade_usd=100.0)
print("\n" + report)

# Persist
if trades:
    import csv
    out = Path(__file__).resolve().parent / "backtest" / "data" / "XAUUSD_trades.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
        w.writeheader()
        w.writerows(trades)
    print(f"\n{len(trades)} trades written to {out}")
