import logging
from typing import Optional

import pandas as pd
import numpy as np

from mt5.data_streamer import get_candles
from ai.indicators import compute_rsi, compute_ema, compute_momentum
from config import M5_CANDLE_COUNT

logger = logging.getLogger("ai.ob_fvg_detector")


class Zone:
    def __init__(self, zone_type: str, direction: str, high: float, low: float,
                 index: int, datetime_val, active: bool = True, strength: str = "NORMAL"):
        self.zone_type = zone_type    # "OB", "FVG", "DEMAND", or "SUPPLY"
        self.direction = direction    # "BULLISH" or "BEARISH"
        self.high = high
        self.low = low
        self.index = index
        self.datetime = datetime_val
        self.active = active
        self.strength = strength      # "STRONG", "NORMAL", or "WEAK"

    def contains_price(self, price: float) -> bool:
        return self.low <= price <= self.high

    def price_near_zone(self, price: float, tolerance_pct: float = 0.001) -> bool:
        zone_range = self.high - self.low
        tolerance = max(zone_range * 0.5, price * tolerance_pct)
        return (self.low - tolerance) <= price <= (self.high + tolerance)

    def to_dict(self) -> dict:
        return {
            "zone_type": self.zone_type,
            "direction": self.direction,
            "high": round(float(self.high), 6),
            "low": round(float(self.low), 6),
            "index": int(self.index),
            "datetime": str(self.datetime),
            "active": self.active,
            "strength": self.strength,
        }


class ZoneDetectionResult:
    def __init__(self, zones: list[Zone], valid: bool, active_zone: Optional[Zone] = None):
        self.zones = zones
        self.valid = valid
        self.active_zone = active_zone

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "zone_count": len(self.zones),
            "active_zone": self.active_zone.to_dict() if self.active_zone else None,
            "zones": [z.to_dict() for z in self.zones[-5:]],  # last 5 zones
        }


def detect_order_blocks(df: pd.DataFrame, direction: str) -> list[Zone]:
    zones = []
    if len(df) < 5:
        return zones

    for i in range(2, len(df) - 1):
        curr = df.iloc[i]
        prev = df.iloc[i - 1]
        next_candle = df.iloc[i + 1] if i + 1 < len(df) else None

        curr_body = curr["close"] - curr["open"]
        prev_body = prev["close"] - prev["open"]

        if direction == "BULLISH":
            # Bullish OB: bearish candle followed by a strong bullish candle that breaks above
            if prev_body < 0 and curr_body > 0:
                # The bullish candle must engulf or break above the bearish candle high
                if curr["close"] > prev["high"]:
                    # The OB zone is the body of the bearish candle
                    ob = Zone(
                        zone_type="OB",
                        direction="BULLISH",
                        high=prev["open"],
                        low=prev["close"],
                        index=i - 1,
                        datetime_val=prev["datetime"]
                    )
                    zones.append(ob)

        elif direction == "BEARISH":
            # Bearish OB: bullish candle followed by a strong bearish candle that breaks below
            if prev_body > 0 and curr_body < 0:
                if curr["close"] < prev["low"]:
                    ob = Zone(
                        zone_type="OB",
                        direction="BEARISH",
                        high=prev["close"],
                        low=prev["open"],
                        index=i - 1,
                        datetime_val=prev["datetime"]
                    )
                    zones.append(ob)

    return zones


def detect_fair_value_gaps(df: pd.DataFrame, direction: str) -> list[Zone]:
    zones = []
    if len(df) < 4:
        return zones

    for i in range(2, len(df)):
        candle1 = df.iloc[i - 2]
        candle2 = df.iloc[i - 1]
        candle3 = df.iloc[i]

        if direction == "BULLISH":
            # Bullish FVG: gap between candle1 high and candle3 low
            if candle3["low"] > candle1["high"]:
                fvg = Zone(
                    zone_type="FVG",
                    direction="BULLISH",
                    high=candle3["low"],
                    low=candle1["high"],
                    index=i - 1,
                    datetime_val=candle2["datetime"]
                )
                zones.append(fvg)

        elif direction == "BEARISH":
            # Bearish FVG: gap between candle1 low and candle3 high
            if candle3["high"] < candle1["low"]:
                fvg = Zone(
                    zone_type="FVG",
                    direction="BEARISH",
                    high=candle1["low"],
                    low=candle3["high"],
                    index=i - 1,
                    datetime_val=candle2["datetime"]
                )
                zones.append(fvg)

    return zones


def detect_break_of_structure(df: pd.DataFrame) -> list[dict]:
    bos_events = []
    if len(df) < 10:
        return bos_events

    swing_highs = []
    swing_lows = []

    for i in range(2, len(df) - 2):
        if df.iloc[i]["high"] > df.iloc[i - 1]["high"] and df.iloc[i]["high"] > df.iloc[i + 1]["high"]:
            if df.iloc[i]["high"] > df.iloc[i - 2]["high"] and df.iloc[i]["high"] > df.iloc[i + 2]["high"]:
                swing_highs.append({"index": i, "price": df.iloc[i]["high"], "datetime": df.iloc[i]["datetime"]})

        if df.iloc[i]["low"] < df.iloc[i - 1]["low"] and df.iloc[i]["low"] < df.iloc[i + 1]["low"]:
            if df.iloc[i]["low"] < df.iloc[i - 2]["low"] and df.iloc[i]["low"] < df.iloc[i + 2]["low"]:
                swing_lows.append({"index": i, "price": df.iloc[i]["low"], "datetime": df.iloc[i]["datetime"]})

    # Detect BOS: price breaking above last swing high or below last swing low
    latest_close = df.iloc[-1]["close"]

    if swing_highs:
        last_sh = swing_highs[-1]
        if latest_close > last_sh["price"]:
            bos_events.append({
                "type": "BULLISH_BOS",
                "level": last_sh["price"],
                "datetime": str(last_sh["datetime"]),
            })

    if swing_lows:
        last_sl = swing_lows[-1]
        if latest_close < last_sl["price"]:
            bos_events.append({
                "type": "BEARISH_BOS",
                "level": last_sl["price"],
                "datetime": str(last_sl["datetime"]),
            })

    return bos_events


def detect_demand_supply_zones(df: pd.DataFrame, direction: str) -> list[Zone]:
    """Detect demand and supply zones based on strong rejection candles.
    Demand zone: area where price dropped then reversed up with strong bullish candle(s).
    Supply zone: area where price rose then reversed down with strong bearish candle(s)."""
    zones = []
    if len(df) < 10:
        return zones

    for i in range(3, len(df) - 1):
        c0 = df.iloc[i - 3]  # 3 candles back
        c1 = df.iloc[i - 2]
        c2 = df.iloc[i - 1]  # reversal candle
        c3 = df.iloc[i]      # confirmation candle

        c2_body = abs(c2["close"] - c2["open"])
        c2_range = c2["high"] - c2["low"]
        c3_body = abs(c3["close"] - c3["open"])

        if c2_range == 0:
            continue

        body_ratio = c2_body / c2_range

        if direction == "BULLISH":
            # Demand zone: price was falling, then strong bullish reversal
            was_falling = c0["close"] > c1["close"] and c1["close"] > c2["open"]
            strong_reversal = c2["close"] > c2["open"] and body_ratio > 0.5
            confirmed = c3["close"] > c2["close"]

            if was_falling and strong_reversal and confirmed:
                strength = "STRONG" if c3_body > c2_body else "NORMAL"
                zone = Zone(
                    zone_type="DEMAND",
                    direction="BULLISH",
                    high=c2["open"],
                    low=min(c2["low"], c1["low"]),
                    index=i - 1,
                    datetime_val=c2["datetime"],
                    strength=strength
                )
                zones.append(zone)

        elif direction == "BEARISH":
            # Supply zone: price was rising, then strong bearish reversal
            was_rising = c0["close"] < c1["close"] and c1["close"] < c2["open"]
            strong_reversal = c2["close"] < c2["open"] and body_ratio > 0.5
            confirmed = c3["close"] < c2["close"]

            if was_rising and strong_reversal and confirmed:
                strength = "STRONG" if c3_body > c2_body else "NORMAL"
                zone = Zone(
                    zone_type="SUPPLY",
                    direction="BEARISH",
                    high=max(c2["high"], c1["high"]),
                    low=c2["open"],
                    index=i - 1,
                    datetime_val=c2["datetime"],
                    strength=strength
                )
                zones.append(zone)

    return zones


def _check_momentum_alignment(df: pd.DataFrame, direction: str) -> tuple[bool, str]:
    """Check if M5 momentum supports the trade direction.
    Returns (aligned, reason)."""
    if len(df) < 20:
        return False, "Insufficient data for momentum check"

    close = df["close"]
    rsi = compute_rsi(close, 14)
    momentum = compute_momentum(close, 10)
    ema8 = compute_ema(close, 8)
    ema21 = compute_ema(close, 21)

    current_rsi = rsi.iloc[-1]
    current_momentum = momentum.iloc[-1]
    prev_momentum = momentum.iloc[-2]
    ema8_val = ema8.iloc[-1]
    ema21_val = ema21.iloc[-1]

    # Check momentum direction and whether it's accelerating or decelerating
    momentum_increasing = current_momentum > prev_momentum
    momentum_decreasing = current_momentum < prev_momentum

    if direction == "BULLISH":
        # Reject BUY if: momentum is negative AND decelerating, or RSI dropping below 40
        if current_momentum < 0 and momentum_decreasing:
            return False, f"Negative & falling momentum ({current_momentum:.5f})"
        if current_rsi < 35:
            return False, f"RSI too low for BUY ({current_rsi:.1f}) — bearish reversal"
        if ema8_val < ema21_val and current_momentum < 0:
            return False, f"EMA8 < EMA21 with negative momentum — downtrend"
        return True, "Bullish momentum OK"

    elif direction == "BEARISH":
        # Reject SELL if: momentum is positive AND increasing, or RSI rising above 65
        if current_momentum > 0 and momentum_increasing:
            return False, f"Positive & rising momentum ({current_momentum:.5f})"
        if current_rsi > 65:
            return False, f"RSI too high for SELL ({current_rsi:.1f}) — bullish reversal"
        if ema8_val > ema21_val and current_momentum > 0:
            return False, f"EMA8 > EMA21 with positive momentum — uptrend"
        return True, "Bearish momentum OK"

    return True, "Unknown direction"


def detect_zones(symbol: str, direction: str, current_price: float) -> ZoneDetectionResult:
    df = get_candles(symbol, "M5", M5_CANDLE_COUNT)
    if df is None or len(df) < 10:
        logger.error(f"Insufficient M5 data for zone detection on {symbol}")
        return ZoneDetectionResult(zones=[], valid=False)

    # Detect OBs, FVGs, and Demand/Supply zones
    order_blocks = detect_order_blocks(df, direction)
    fvg_zones = detect_fair_value_gaps(df, direction)
    ds_zones = detect_demand_supply_zones(df, direction)

    all_zones = order_blocks + fvg_zones + ds_zones

    # Invalidate zones that price has already passed through significantly
    active_zones = []
    for zone in all_zones:
        if direction == "BULLISH":
            if current_price < zone.high * 1.005:  # Price hasn't run too far past
                zone.active = True
                active_zones.append(zone)
        elif direction == "BEARISH":
            if current_price > zone.low * 0.995:
                zone.active = True
                active_zones.append(zone)

    # Find zone that price is currently inside or reacting to
    matching_zone = None
    for zone in reversed(active_zones):  # most recent first
        if zone.contains_price(current_price) or zone.price_near_zone(current_price):
            matching_zone = zone
            break

    if matching_zone is None:
        logger.debug(f"No valid {direction} zone for {symbol} at price {current_price}")
        return ZoneDetectionResult(zones=active_zones, valid=False)

    # Momentum validation — prevent entries against reversing momentum
    momentum_ok, momentum_reason = _check_momentum_alignment(df, direction)

    if not momentum_ok:
        logger.info(f"Zone found for {symbol} but REJECTED: {momentum_reason}")
        return ZoneDetectionResult(zones=active_zones, valid=False, active_zone=matching_zone)

    logger.info(f"Valid {direction} zone for {symbol}: {matching_zone.zone_type} "
                f"({matching_zone.strength}) [{matching_zone.low:.5f} - {matching_zone.high:.5f}] "
                f"| {momentum_reason}")

    return ZoneDetectionResult(zones=active_zones, valid=True, active_zone=matching_zone)
