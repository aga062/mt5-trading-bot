import logging
from typing import Optional

import pandas as pd

from ai.indicators import add_all_indicators
from ai.trend_analyzer import TrendAnalysis
from mt5.data_streamer import get_candles
from config import H1_CANDLE_COUNT

logger = logging.getLogger("ai.decision_engine")


class AIDecision:
    def __init__(self, decision: str, confidence: float, reasons: list[str], indicators: dict):
        self.decision = decision       # "BUY", "SELL", or "WAIT"
        self.confidence = confidence    # 0.0 - 1.0
        self.reasons = reasons
        self.indicators = indicators

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "confidence": round(float(self.confidence), 4),
            "reasons": self.reasons,
            "indicators": {k: round(float(v), 6) for k, v in self.indicators.items()},
        }


def make_decision(symbol: str, trend: TrendAnalysis) -> Optional[AIDecision]:
    df = get_candles(symbol, "H1", H1_CANDLE_COUNT)
    if df is None or len(df) < 30:
        logger.error(f"Insufficient data for AI decision on {symbol}")
        return None

    df = add_all_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    rsi = latest["rsi"]
    macd_line = latest["macd_line"]
    macd_signal = latest["macd_signal"]
    macd_hist = latest["macd_histogram"]
    momentum = latest["momentum"]
    atr = latest["atr"]
    close = latest["close"]
    ema8 = latest["ema8"]
    ema21 = latest["ema21"]
    volume = latest["volume"]
    volume_sma = latest["volume_sma"]

    if any(pd.isna(v) for v in [rsi, macd_line, macd_signal, momentum, atr]):
        logger.error("Indicator values contain NaN")
        return None

    score = 0.0
    reasons = []

    # --- TREND ALIGNMENT (5-level bias) ---
    if trend.bias == "STRONG_BULLISH":
        score += 1.5
        reasons.append(f"H1 trend STRONG_BULLISH (structure={trend.market_structure}, ADX={trend.adx:.1f})")
    elif trend.bias == "WEAK_BULLISH":
        score += 0.7
        reasons.append(f"H1 trend WEAK_BULLISH (structure={trend.market_structure})")
    elif trend.bias == "STRONG_BEARISH":
        score -= 1.5
        reasons.append(f"H1 trend STRONG_BEARISH (structure={trend.market_structure}, ADX={trend.adx:.1f})")
    elif trend.bias == "WEAK_BEARISH":
        score -= 0.7
        reasons.append(f"H1 trend WEAK_BEARISH (structure={trend.market_structure})")
    else:
        reasons.append("H1 trend is NEUTRAL — no directional edge")

    # --- RSI ---
    if rsi < 30:
        score += 0.8
        reasons.append(f"RSI oversold ({rsi:.1f})")
    elif rsi < 45:
        score += 0.4
        reasons.append(f"RSI bullish zone ({rsi:.1f})")
    elif rsi > 70:
        score -= 0.8
        reasons.append(f"RSI overbought ({rsi:.1f})")
    elif rsi > 55:
        score -= 0.4
        reasons.append(f"RSI bearish zone ({rsi:.1f})")

    # --- MACD ---
    if macd_line > macd_signal and macd_hist > 0:
        score += 0.7
        reasons.append("MACD bullish crossover")
    elif macd_line < macd_signal and macd_hist < 0:
        score -= 0.7
        reasons.append("MACD bearish crossover")

    # MACD histogram momentum
    prev_hist = prev["macd_histogram"] if not pd.isna(prev["macd_histogram"]) else 0
    if macd_hist > prev_hist:
        score += 0.3
        reasons.append("MACD histogram increasing")
    elif macd_hist < prev_hist:
        score -= 0.3
        reasons.append("MACD histogram decreasing")

    # --- MOMENTUM ---
    if momentum > 0:
        score += 0.5
        reasons.append(f"Positive momentum ({momentum:.5f})")
    elif momentum < 0:
        score -= 0.5
        reasons.append(f"Negative momentum ({momentum:.5f})")

    # --- CANDLE STRUCTURE ---
    body = abs(close - latest["open"])
    upper_wick = latest["high"] - max(close, latest["open"])
    lower_wick = min(close, latest["open"]) - latest["low"]
    candle_range = latest["high"] - latest["low"]

    if candle_range > 0:
        body_ratio = body / candle_range
        if body_ratio > 0.7:
            if close > latest["open"]:
                score += 0.4
                reasons.append("Strong bullish candle")
            else:
                score -= 0.4
                reasons.append("Strong bearish candle")

        # Pin bar / rejection
        if lower_wick > body * 2 and upper_wick < body * 0.5:
            score += 0.5
            reasons.append("Bullish rejection candle (long lower wick)")
        elif upper_wick > body * 2 and lower_wick < body * 0.5:
            score -= 0.5
            reasons.append("Bearish rejection candle (long upper wick)")

    # --- VOLUME ---
    if not pd.isna(volume_sma) and volume_sma > 0:
        vol_ratio = volume / volume_sma
        if vol_ratio > 1.5:
            score += 0.3 if score > 0 else -0.3
            reasons.append(f"High volume confirmation ({vol_ratio:.1f}x avg)")

    # --- VOLATILITY ---
    if atr > 0 and close > 0:
        atr_pct = (atr / close) * 100
        if atr_pct > 0.5:
            reasons.append(f"High volatility (ATR {atr_pct:.3f}% of price)")

    # --- DECISION ---
    confidence = min(abs(score) / 4.0, 1.0)

    if score >= 1.5 and trend.is_bullish:
        decision = "BUY"
        # Boost confidence for strong trends
        if trend.is_strong:
            confidence = min(confidence * 1.2, 1.0)
    elif score <= -1.5 and trend.is_bearish:
        decision = "SELL"
        if trend.is_strong:
            confidence = min(confidence * 1.2, 1.0)
    elif trend.bias == "NEUTRAL":
        decision = "WAIT"
        confidence *= 0.3
        reasons.append("NEUTRAL bias — staying out")
    else:
        decision = "WAIT"
        confidence *= 0.5

    indicators = {
        "rsi": float(rsi),
        "macd_line": float(macd_line),
        "macd_signal": float(macd_signal),
        "macd_histogram": float(macd_hist),
        "momentum": float(momentum),
        "atr": float(atr),
        "ema8": float(ema8),
        "ema21": float(ema21),
        "close": float(close),
        "volume": float(volume),
        "volume_sma": float(volume_sma) if not pd.isna(volume_sma) else 0.0,
        "adx": float(trend.adx),
        "score": float(score),
    }

    logger.info(f"AI Decision for {symbol}: {decision} (score={score:.2f}, confidence={confidence:.4f})")
    return AIDecision(decision=decision, confidence=confidence, reasons=reasons, indicators=indicators)
