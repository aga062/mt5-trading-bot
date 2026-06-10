"""
Daily Bias — Layer 0 (D1/H4)
============================
Top-of-funnel directional filter. Decides whether the symbol is more likely to
go up or down today using only D1 and H4 of the traded symbol (broker-independent).

Four factors (each ±1): D1 trend structure, D1 price location, H4 trend structure,
and price vs the current week's open. A clear majority (|score| >= threshold) is
required, otherwise bias is NEUTRAL — meaning no trade today.

Result is cached per symbol so the 3-second trading loop stays fast.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from mt5.data_streamer import get_candles
from ai.indicators import compute_ema
from config import (
    D1_CANDLE_COUNT, H4_CANDLE_COUNT,
    DAILY_BIAS_CACHE_SECONDS, DAILY_BIAS_THRESHOLD,
)

logger = logging.getLogger("ai.daily_bias")

EMA_FAST = 20
EMA_SLOW = 50

_lock = threading.Lock()
_cache: dict[str, tuple[float, "DailyBias"]] = {}  # symbol -> (timestamp, result)


@dataclass
class DailyBias:
    bias: str                 # "BULLISH", "BEARISH", "NEUTRAL"
    score: int = 0
    current_price: float = 0.0
    d1_ema20: float = 0.0
    d1_ema50: float = 0.0
    h4_ema20: float = 0.0
    h4_ema50: float = 0.0
    weekly_open: float = 0.0
    reasons: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "bias": self.bias,
            "score": self.score,
            "current_price": round(self.current_price, 3),
            "d1_ema20": round(self.d1_ema20, 3),
            "d1_ema50": round(self.d1_ema50, 3),
            "h4_ema20": round(self.h4_ema20, 3),
            "h4_ema50": round(self.h4_ema50, 3),
            "weekly_open": round(self.weekly_open, 3),
            "reasons": self.reasons,
        }


def _weekly_open(df_d1) -> float:
    """Open price of the earliest D1 candle in the current ISO week."""
    last_iso = df_d1.iloc[-1]["datetime"].isocalendar()
    current_week = (last_iso[0], last_iso[1])
    for i in range(len(df_d1)):
        d_iso = df_d1.iloc[i]["datetime"].isocalendar()
        if (d_iso[0], d_iso[1]) == current_week:
            return float(df_d1.iloc[i]["open"])
    return float(df_d1.iloc[-1]["open"])


def _compute(symbol: str) -> Optional[DailyBias]:
    d1 = get_candles(symbol, "D1", D1_CANDLE_COUNT)
    if d1 is None or len(d1) < 50:
        logger.warning(f"Insufficient D1 data for daily bias on {symbol}")
        return None
    h4 = get_candles(symbol, "H4", H4_CANDLE_COUNT)
    if h4 is None or len(h4) < 50:
        logger.warning(f"Insufficient H4 data for daily bias on {symbol}")
        return None

    current_price = float(d1.iloc[-1]["close"])
    d1_ema20 = float(compute_ema(d1["close"], EMA_FAST).iloc[-1])
    d1_ema50 = float(compute_ema(d1["close"], EMA_SLOW).iloc[-1])
    h4_ema20 = float(compute_ema(h4["close"], EMA_FAST).iloc[-1])
    h4_ema50 = float(compute_ema(h4["close"], EMA_SLOW).iloc[-1])
    weekly_open = _weekly_open(d1)

    score = 0
    reasons = []

    # Factor 1: D1 trend structure
    if d1_ema20 > d1_ema50:
        score += 1
        reasons.append("D1 EMA20>EMA50 (uptrend structure)")
    else:
        score -= 1
        reasons.append("D1 EMA20<EMA50 (downtrend structure)")

    # Factor 2: D1 price location
    if current_price > d1_ema50:
        score += 1
        reasons.append("Price above D1 EMA50")
    else:
        score -= 1
        reasons.append("Price below D1 EMA50")

    # Factor 3: H4 trend structure
    if h4_ema20 > h4_ema50:
        score += 1
        reasons.append("H4 EMA20>EMA50 (uptrend structure)")
    else:
        score -= 1
        reasons.append("H4 EMA20<EMA50 (downtrend structure)")

    # Factor 4: Price vs weekly open
    if current_price > weekly_open:
        score += 1
        reasons.append("Price above weekly open")
    else:
        score -= 1
        reasons.append("Price below weekly open")

    if score >= DAILY_BIAS_THRESHOLD:
        bias = "BULLISH"
    elif score <= -DAILY_BIAS_THRESHOLD:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    logger.debug(f"Daily bias {symbol}: {bias} (score={score}) — {reasons}")

    return DailyBias(
        bias=bias, score=score, current_price=current_price,
        d1_ema20=d1_ema20, d1_ema50=d1_ema50,
        h4_ema20=h4_ema20, h4_ema50=h4_ema50,
        weekly_open=weekly_open, reasons=reasons,
    )


def analyze_daily_bias(symbol: str) -> Optional[DailyBias]:
    """Cached daily bias. Recomputes at most once per DAILY_BIAS_CACHE_SECONDS per symbol."""
    now = time.time()
    with _lock:
        cached = _cache.get(symbol)
        if cached and (now - cached[0]) < DAILY_BIAS_CACHE_SECONDS:
            return cached[1]
    result = _compute(symbol)
    if result is not None:
        with _lock:
            _cache[symbol] = (now, result)
    return result
