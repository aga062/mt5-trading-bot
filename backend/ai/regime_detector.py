"""
Regime Detector — classifies H1 market into TRENDING_UP / TRENDING_DOWN / RANGING.
Uses ADX + EMA50 bias for fast, deterministic classification.
"""
import logging
import numpy as np
import pandas as pd

from ai.indicators import compute_ema, compute_adx

logger = logging.getLogger("ai.regime_detector")

# Cached regime states: {symbol: {pd.Timestamp: str}}
_regime_cache: dict[str, dict] = {}

ADX_TREND_THRESHOLD = 25.0
ADX_RANGE_THRESHOLD = 20.0


def _compute_regimes(h1_df: pd.DataFrame) -> list[str]:
    """Classify each H1 bar into regime using ADX + EMA50."""
    close = h1_df["close"].values
    adx = compute_adx(h1_df, 14).values
    ema50 = compute_ema(h1_df["close"], 50).values

    states = []
    for i in range(len(h1_df)):
        a = adx[i] if not np.isnan(adx[i]) else 0.0
        if a >= ADX_TREND_THRESHOLD:
            states.append("TRENDING_UP" if close[i] > ema50[i] else "TRENDING_DOWN")
        elif a <= ADX_RANGE_THRESHOLD:
            states.append("RANGING")
        else:
            # Neutral zone — carry forward previous or default to ranging
            states.append(states[-1] if states else "RANGING")
    return states


def precompute_regimes(symbol: str, h1_df: pd.DataFrame, window: int = 200):
    """Pre-compute regime states for all H1 bars."""
    global _regime_cache
    if symbol in _regime_cache:
        return

    n = len(h1_df)
    if n < 20:
        logger.warning(f"Insufficient H1 data ({n} bars) for regime detection")
        return

    states = _compute_regimes(h1_df)
    times = pd.to_datetime(h1_df["datetime"].values)
    _regime_cache[symbol] = {pd.Timestamp(t): s for t, s in zip(times, states)}
    logger.info(f"Pre-computed {n} regime states for {symbol}")


def get_regime(symbol: str, current_time) -> str:
    """Return regime state for given symbol and time. Must call precompute_regimes first."""
    cache = _regime_cache.get(symbol, {})
    if not cache:
        return "RANGING"
    t = pd.Timestamp(current_time)
    keys = sorted(cache.keys())
    idx = np.searchsorted(keys, t, side="right") - 1
    if idx < 0:
        idx = 0
    return cache[keys[idx]]


def clear_cache(symbol: str = None):
    """Clear regime cache (useful between backtest runs)."""
    global _regime_cache
    if symbol:
        _regime_cache.pop(symbol, None)
    else:
        _regime_cache = {}
