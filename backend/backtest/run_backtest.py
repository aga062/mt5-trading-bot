"""
Backtest CLI.

  Step 1 (once, with MT5 terminal open & logged in):
      python -m backtest.run_backtest --download --months 6

  Step 2 (offline, repeatable):
      python -m backtest.run_backtest --spread 0.30
"""
import argparse
import csv
import logging
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--download", action="store_true", help="Download history from MT5 (run once)")
    p.add_argument("--months", type=int, default=6)
    p.add_argument("--symbol", default="XAUUSD")
    p.add_argument("--spread", type=float, default=0.30, help="Modeled XAUUSD spread (price units)")
    p.add_argument("--risk-usd", type=float, default=100.0, help="$ risk per trade for the $ estimate")
    p.add_argument("--setup", default="ict", help="Setup to test: ict | mean_reversion")
    args = p.parse_args()

    from backtest.data_loader import download_history, HistoricalData
    from backtest.harness import run
    from backtest.report import build_report

    if args.download:
        print(f"Downloading {args.months} months of {args.symbol} history from MT5...")
        download_history(months=args.months, symbol=args.symbol)
        print("Download complete. Now run again without --download.")
        return

    print(f"Loading cached history for {args.symbol}...")
    provider = HistoricalData(symbol=args.symbol, spread=args.spread)

    signal_fn = None
    if args.setup != "ict":
        import backtest.setups as setups
        signal_fn = getattr(setups, args.setup)
        print(f"Setup: {args.setup}")
    print("Replaying strategy over history (this can take several minutes)...")
    trades = run(provider, symbol=args.symbol, signal_fn=signal_fn)

    report = build_report(trades, risk_per_trade_usd=args.risk_usd)
    print("\n" + report)

    # Persist the labeled trade list (foundation for future ML / attribution)
    out_path = Path(__file__).resolve().parent / "data" / f"{args.symbol}_trades.csv"
    if trades:
        with open(out_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
            w.writeheader()
            w.writerows(trades)
        print(f"\n{len(trades)} trades written to {out_path}")
    else:
        print("\nNo trades generated.")


if __name__ == "__main__":
    main()
