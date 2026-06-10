"""
Quick parametric search over filter combinations.
Runs a lightweight backtest on the cached history for fast iteration.
"""
import csv
from pathlib import Path
import numpy as np
import pandas as pd
from backtest.data_loader import HistoricalData, clock
from backtest.harness import _simulate_trade

CWD = Path(__file__).resolve().parent.parent

def run_variant(
    provider,
    use_m15_align=True,
    use_m5_struct=True,
    use_close_confirm=True,
    use_bull_bear_candle=True,
    use_wick_ratio=False,
    wick_ratio=0.55,
    use_pdl_only=False,
    poi_tol=0.35,
    sl_atr=0.5,
):
    import strategies.entry_confirmation as ec
    ec.get_candles = provider.get_candles
    ec.get_current_tick = provider.get_current_tick
    ec.check_news_filter = lambda: (True, "news off")
    ec.check_session_filter = provider.check_session_filter
    ec.check_spread_filter = lambda s: (True, "ok")

    # Override parameters temporarily
    orig_poi_tol = ec.POI_TOL_ATR
    orig_sl_atr = ec.POI_SL_ATR
    orig_wick = ec.REJECTION_WICK_RATIO
    ec.POI_TOL_ATR = poi_tol
    ec.POI_SL_ATR = sl_atr
    ec.REJECTION_WICK_RATIO = wick_ratio

    # Temporarily patch the evaluate_entry internals by monkey-patching helper closures
    # Actually, easier: re-import after each change is impractical.
    # Instead, let's just inline a lightweight evaluator here.

    ec.POI_TOL_ATR = orig_poi_tol
    ec.POI_SL_ATR = orig_sl_atr
    ec.REJECTION_WICK_RATIO = orig_wick
    return []


if __name__ == "__main__":
    provider = HistoricalData(symbol="XAUUSD", spread=0.30)
    print("This is a stub. Implementing full inline evaluator...")
