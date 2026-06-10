import logging
from typing import Optional

import pandas as pd

from ai.indicators import add_all_indicators
from mt5.data_streamer import get_candles
from config import H1_CANDLE_COUNT

logger = logging.getLogger("ai.trend_analyzer")

# Valid bias levels (ordered from strongest bull to strongest bear)
BIAS_LEVELS = [
    "STRONG_BULLISH",
    "WEAK_BULLISH",
    "NEUTRAL",
    "WEAK_BEARISH",
    "STRONG_BEARISH",
]


class TrendAnalysis:
    def __init__(self, bias: str, ema8: float, ema21: float, strength: float,
                 rsi: float = 0.0, adx: float = 0.0,
                 market_structure: str = "UNKNOWN",
                 price_vs_ema21: str = "UNKNOWN",
                 reasons: list[str] | None = None):
        self.bias = bias
        self.ema8 = ema8
        self.ema21 = ema21
        self.strength = strength
        self.rsi = rsi
        self.adx = adx
        self.market_structure = market_structure  # "HH_HL", "LH_LL", "MIXED"
        self.price_vs_ema21 = price_vs_ema21      # "ABOVE", "BELOW"
        self.reasons = reasons or []

    @property
    def is_bullish(self) -> bool:
        return self.bias in ("STRONG_BULLISH", "WEAK_BULLISH")

    @property
    def is_bearish(self) -> bool:
        return self.bias in ("STRONG_BEARISH", "WEAK_BEARISH")

    @property
    def is_strong(self) -> bool:
        return self.bias in ("STRONG_BULLISH", "STRONG_BEARISH")

    def to_dict(self) -> dict:
        return {
            "bias": self.bias,
            "ema8": round(float(self.ema8), 6),
            "ema21": round(float(self.ema21), 6),
            "strength": round(float(self.strength), 4),
            "rsi": round(float(self.rsi), 2),
            "adx": round(float(self.adx), 2),
            "market_structure": self.market_structure,
            "price_vs_ema21": self.price_vs_ema21,
            "reasons": self.reasons,
        }


# ── Market Structure Detection ──────────────────────────────────────────

def _detect_swing_points(df: pd.DataFrame, lookback: int = 2):
    """Identify swing highs and swing lows in the dataframe."""
    swing_highs = []
    swing_lows = []

    for i in range(lookback, len(df) - lookback):
        high = float(df.iloc[i]["high"])
        low = float(df.iloc[i]["low"])

        is_sh = all(high > float(df.iloc[i - j]["high"]) for j in range(1, lookback + 1)) and \
                all(high > float(df.iloc[i + j]["high"]) for j in range(1, lookback + 1))

        is_sl = all(low < float(df.iloc[i - j]["low"]) for j in range(1, lookback + 1)) and \
                all(low < float(df.iloc[i + j]["low"]) for j in range(1, lookback + 1))

        if is_sh:
            swing_highs.append({"index": i, "price": high})
        if is_sl:
            swing_lows.append({"index": i, "price": low})

    return swing_highs, swing_lows


def _classify_market_structure(swing_highs: list[dict], swing_lows: list[dict]) -> str:
    """Classify structure as HH_HL (bullish), LH_LL (bearish), or MIXED."""
    if len(swing_highs) < 2 and len(swing_lows) < 2:
        return "MIXED"

    hh_count = 0
    lh_count = 0
    hl_count = 0
    ll_count = 0

    # Check last 4 swing highs
    recent_sh = swing_highs[-4:] if len(swing_highs) >= 4 else swing_highs
    for i in range(1, len(recent_sh)):
        if recent_sh[i]["price"] > recent_sh[i - 1]["price"]:
            hh_count += 1
        else:
            lh_count += 1

    # Check last 4 swing lows
    recent_sl = swing_lows[-4:] if len(swing_lows) >= 4 else swing_lows
    for i in range(1, len(recent_sl)):
        if recent_sl[i]["price"] > recent_sl[i - 1]["price"]:
            hl_count += 1
        else:
            ll_count += 1

    bullish_score = hh_count + hl_count
    bearish_score = lh_count + ll_count

    if bullish_score > bearish_score and bullish_score >= 2:
        return "HH_HL"
    elif bearish_score > bullish_score and bearish_score >= 2:
        return "LH_LL"
    else:
        return "MIXED"


# ── Main Analysis ────────────────────────────────────────────────────────

def analyze_h1_trend(symbol: str) -> Optional[TrendAnalysis]:
    df = get_candles(symbol, "H1", H1_CANDLE_COUNT)
    if df is None or len(df) < 30:
        logger.error(f"Insufficient H1 data for {symbol}")
        return None

    df = add_all_indicators(df)
    latest = df.iloc[-1]
    ema8 = float(latest["ema8"])
    ema21 = float(latest["ema21"])
    rsi = float(latest["rsi"])
    adx = float(latest["adx"]) if not pd.isna(latest["adx"]) else 0.0
    close = float(latest["close"])

    if pd.isna(latest["ema8"]) or pd.isna(latest["ema21"]) or pd.isna(latest["rsi"]):
        logger.error("Indicator values are NaN")
        return None

    # ── EMA Crossover ────────────────────────────────────────────────
    ema_bullish = ema8 > ema21
    distance = abs(ema8 - ema21)
    ema_strength = min(distance / (close * 0.01), 1.0)

    # ── RSI Momentum ─────────────────────────────────────────────────
    rsi_bullish = rsi > 50
    rsi_bearish = rsi < 50

    # ── Price vs EMA21 ───────────────────────────────────────────────
    price_above_ema21 = close > ema21
    price_vs_ema21 = "ABOVE" if price_above_ema21 else "BELOW"

    # ── ADX Trend Strength ───────────────────────────────────────────
    trending = adx > 20  # Market is trending, not ranging

    # ── Market Structure ─────────────────────────────────────────────
    swing_highs, swing_lows = _detect_swing_points(df, lookback=2)
    market_structure = _classify_market_structure(swing_highs, swing_lows)

    # ── Composite Bias Scoring ───────────────────────────────────────
    score = 0.0
    reasons = []

    # EMA alignment (+/- 1.0)
    if ema_bullish:
        score += 1.0
        reasons.append(f"EMA8 > EMA21 (spread: {distance:.5f})")
    else:
        score -= 1.0
        reasons.append(f"EMA8 < EMA21 (spread: {distance:.5f})")

    # RSI momentum (+/- 0.5)
    if rsi_bullish:
        score += 0.5
        reasons.append(f"RSI {rsi:.1f} > 50 (bullish momentum)")
    elif rsi_bearish:
        score -= 0.5
        reasons.append(f"RSI {rsi:.1f} < 50 (bearish momentum)")

    # Price vs EMA21 (+/- 0.5)
    if price_above_ema21:
        score += 0.5
        reasons.append("Price above EMA21")
    else:
        score -= 0.5
        reasons.append("Price below EMA21")

    # Market structure (+/- 1.0)
    if market_structure == "HH_HL":
        score += 1.0
        reasons.append("HH/HL structure (bullish)")
    elif market_structure == "LH_LL":
        score -= 1.0
        reasons.append("LH/LL structure (bearish)")
    else:
        reasons.append("Mixed market structure")

    # ADX filter (dampens score if ranging)
    if not trending:
        score *= 0.5
        reasons.append(f"ADX {adx:.1f} < 20 (ranging — score dampened)")
    else:
        reasons.append(f"ADX {adx:.1f} > 20 (trending)")

    # ── Determine Bias Level ─────────────────────────────────────────
    if score >= 2.0:
        bias = "STRONG_BULLISH"
    elif score >= 0.5:
        bias = "WEAK_BULLISH"
    elif score <= -2.0:
        bias = "STRONG_BEARISH"
    elif score <= -0.5:
        bias = "WEAK_BEARISH"
    else:
        bias = "NEUTRAL"

    logger.info(
        f"H1 Trend for {symbol}: {bias} (score={score:.2f}, "
        f"EMA8={ema8:.5f}, EMA21={ema21:.5f}, RSI={rsi:.1f}, "
        f"ADX={adx:.1f}, structure={market_structure})"
    )

    return TrendAnalysis(
        bias=bias,
        ema8=ema8,
        ema21=ema21,
        strength=ema_strength,
        rsi=rsi,
        adx=adx,
        market_structure=market_structure,
        price_vs_ema21=price_vs_ema21,
        reasons=reasons,
    )
