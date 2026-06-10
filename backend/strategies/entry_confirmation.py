"""
Entry Strategy — H1 50 EMA + M5 Pullback + Fixed TP at Key Zone + Profit Locks
==============================================================================
  H1:  50 EMA bias. BUY only when price > 50 EMA. SELL only when price < 50 EMA.
  M5:  Pullback to key zone aligned with H1 trend (Support/Resistance, EQH/EQL).
       Entry: IMMEDIATE bounce from zone (HL for BUY, LH for SELL).
       Optional: engulfing or pin bar boosts tag but does NOT block entry.
  SL:  max(1.5 ATR, 50 pips / 0.50 for XAUUSD).
  TP:  nearest key zone in trade direction (next resistance for BUY, next support for SELL).
  Profit Locks: 25% → SL@25%, 50% → SL@50%, 75% → SL@75%. Past 75%: let it run to TP
                or get stopped at 75%.
  Session: London Opening 08:00-11:00 UTC, London/NY overlap 13:00-17:00 UTC.
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd

from mt5.data_streamer import get_candles, get_current_tick
from ai.indicators import compute_ema, compute_atr
from ai.entry_filters import check_news_filter, check_session_filter, check_spread_filter
from config import SESSION_FILTER_ENABLED

logger = logging.getLogger("strategies.entry_confirmation")

# ── Tunable params ────────────────────────────────────────────────────────────
H1_EMA_LEN = 50
M5_EMA_LEN = 50
ATR_LEN = 14
SL_ATR_MULT = 1.5          # SL = entry ± 1.5 × ATR
MIN_SL_PIPS = 0.50         # 50 pips minimum for XAUUSD (0.50)
MAX_HOLD_HOURS = 24
SESSION_FILTER = True
SESSION_WINDOWS = [(8, 11), (13, 17)]  # London open + London/NY overlap

MIN_BODY_PCT = 0.55        # engulfing body > 55% of prev candle range
WICK_REJECTION_PCT = 0.60  # pin bar wick > 60% of total range

_bot_state: dict[str, str] = {}


class _SetupShim:
    def __init__(self, direction, entry, sl, tp, poi):
        self.direction = direction
        self.entry_price = entry
        self.sl_price = sl
        self.tp_price = tp
        self.confirmation = poi
        self.ob_high = 0.0
        self.ob_low = 0.0

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "confirmation": self.confirmation,
            "entry_price": round(self.entry_price, 5),
            "ob_mid": round(self.entry_price, 5),
            "ob_high": 0.0, "ob_low": 0.0,
            "sl_price": round(self.sl_price, 5),
            "tp_price": round(self.tp_price, 5),
        }


class TradeSignal:
    def __init__(self, action: str, symbol: str, entry_price: float,
                 sl_price: float = 0.0, tp_price: float = 0.0,
                 reason: str = "", poi: str = "NONE"):
        self.action = action
        self.symbol = symbol
        self.entry_price = entry_price
        self.sl_price = sl_price
        self.tp_price = tp_price
        self.reason = reason
        self.h1_bias = "NEUTRAL"
        self.daily_bias = "NEUTRAL"
        self.trade_type = "H1_MOMENTUM"
        self.order_kind = "MARKET"
        self.ai_decision_str = "H1_MOMENTUM" if action in ("BUY", "SELL") else "WAIT"
        self.m5_zone_str = poi
        self.ict_result = None
        self.ict_setup = (_SetupShim(action, entry_price, sl_price, tp_price, poi)
                          if action in ("BUY", "SELL") else None)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "symbol": self.symbol,
            "entry_price": round(float(self.entry_price), 6),
            "reason": self.reason,
            "daily_bias": self.h1_bias,
            "trade_type": self.trade_type,
            "order_kind": self.order_kind,
            "ict": ({"valid": True, "reason": self.reason, "setup": self.ict_setup.to_dict()}
                    if self.ict_setup else None),
            "state": _bot_state.get(self.symbol, "IDLE"),
        }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _swings(df, lookback=3):
    h, l = df["high"].values, df["low"].values
    highs, lows = [], []
    for i in range(lookback, len(df) - lookback):
        if all(h[i] >= h[i - j] and h[i] >= h[i + j] for j in range(1, lookback + 1)):
            highs.append(float(h[i]))
        if all(l[i] <= l[i - j] and l[i] <= l[i + j] for j in range(1, lookback + 1)):
            lows.append(float(l[i]))
    return highs, lows


def _find_eqh_eql(values: list[float], tol: float) -> list[float]:
    """Find Equal Highs / Equal Lows — clusters of values within tolerance."""
    if len(values) < 2:
        return []
    clusters = []
    sorted_vals = sorted(values)
    i = 0
    while i < len(sorted_vals):
        cluster = [sorted_vals[i]]
        j = i + 1
        while j < len(sorted_vals) and abs(sorted_vals[j] - sorted_vals[i]) <= tol:
            cluster.append(sorted_vals[j])
            j += 1
        if len(cluster) >= 2:
            clusters.append(float(np.mean(cluster)))
        i = j
    return clusters


def _m5_horizontal_levels(m5c: pd.DataFrame, atr: float) -> dict:
    """Recent swing highs/lows + EQH/EQL on M5 as horizontal S/R zones."""
    levels = {"resistance": [], "support": []}
    if len(m5c) > 10:
        hi, lo = _swings(m5c, 3)
        tol = 0.3 * atr  # EQH/EQL tolerance: 0.3 × ATR
        eqh = _find_eqh_eql(hi, tol)
        eql = _find_eqh_eql(lo, tol)
        for v in hi[-3:]:
            levels["resistance"].append(v)
        for v in eqh:
            levels["resistance"].append(v)
        for v in lo[-3:]:
            levels["support"].append(v)
        for v in eql:
            levels["support"].append(v)
    return levels


def _find_nearest_level(price: float, levels: list, direction: str) -> Optional[float]:
    if not levels:
        return None
    valid = [v for v in levels
             if (direction == "below" and v < price) or (direction == "above" and v > price)]
    if not valid:
        return None
    return min(valid, key=lambda v: abs(v - price))


def _is_engulfing(cur, prev, side: str) -> bool:
    """Current candle body engulfs previous candle body."""
    cur_o, cur_c = float(cur["open"]), float(cur["close"])
    prev_o, prev_c = float(prev["open"]), float(prev["close"])
    prev_rng = abs(prev_c - prev_o)
    cur_body = abs(cur_c - cur_o)
    if prev_rng <= 0:
        return False
    if side == "BUY":
        return cur_c > cur_o and cur_body >= MIN_BODY_PCT * prev_rng and cur_c > prev_o
    else:
        return cur_c < cur_o and cur_body >= MIN_BODY_PCT * prev_rng and cur_c < prev_o


def _is_pin_bar(cur, side: str) -> bool:
    """Rejection wick > 60% of total range."""
    o, h, l, c = float(cur["open"]), float(cur["high"]), float(cur["low"]), float(cur["close"])
    rng = h - l
    if rng <= 0:
        return False
    if side == "BUY":
        if c <= o:
            return False
        lower_wick = min(o, c) - l
        return lower_wick / rng >= WICK_REJECTION_PCT
    else:
        if c >= o:
            return False
        upper_wick = h - max(o, c)
        return upper_wick / rng >= WICK_REJECTION_PCT


# ── Main entry evaluation ────────────────────────────────────────────────────

def evaluate_entry(symbol: str) -> TradeSignal:
    def _wait(reason, bias="NEUTRAL"):
        _bot_state[symbol] = "SCANNING"
        sig = TradeSignal("WAIT", symbol, 0, reason=reason)
        sig.h1_bias = bias
        sig.daily_bias = bias
        return sig

    # ── Pre-trade filters ──
    ok, r = check_news_filter()
    if not ok:
        return _wait(r)
    if SESSION_FILTER_ENABLED:
        ok, r = check_session_filter()
        if not ok:
            return _wait(r)
    ok, r = check_spread_filter(symbol)
    if not ok:
        return _wait(r)

    tick = get_current_tick(symbol)
    if tick is None:
        return _wait("No tick data")

    # Session: London open 08-11 UTC, London/NY overlap 13-17 UTC
    if SESSION_FILTER and tick.get("time"):
        t = pd.to_datetime(tick["time"])
        hour = t.hour
        in_window = any(start <= hour <= end for start, end in SESSION_WINDOWS)
        if not in_window:
            return _wait(f"Outside trade window (hour={hour} UTC)")

    mid = (tick["bid"] + tick["ask"]) / 2

    # ── H1 bias: 50 EMA only ──
    h1 = get_candles(symbol, "H1", 120)
    if h1 is None or len(h1) < H1_EMA_LEN + 5:
        return _wait("Insufficient H1 data")

    ema50_h1 = float(compute_ema(h1["close"], H1_EMA_LEN).iloc[-1])
    side = "BUY" if mid > ema50_h1 else "SELL"
    bias = "BULLISH" if side == "BUY" else "BEARISH"

    # ── M5 analysis ──
    m5 = get_candles(symbol, "M5", 80)
    if m5 is None or len(m5) < M5_EMA_LEN + 5:
        return _wait("Insufficient M5 data", bias)

    m5c = m5.iloc[:-1]
    if len(m5c) < 5:
        return _wait("Insufficient completed M5 bars", bias)

    atr_m5 = float(compute_atr(m5c, ATR_LEN).iloc[-1])
    if atr_m5 <= 0:
        return _wait("Invalid M5 ATR", bias)

    ema50_m5 = float(compute_ema(m5["close"], M5_EMA_LEN).iloc[-1])

    # Price must be pulling back toward 50 EMA (not overextended)
    if side == "BUY" and mid > ema50_m5 + 1.0 * atr_m5:
        return _wait(f"Price overextended above M5 50 EMA", bias)
    if side == "SELL" and mid < ema50_m5 - 1.0 * atr_m5:
        return _wait(f"Price overextended below M5 50 EMA", bias)

    # ── Structural pullback filter ──
    # BUY only at Higher Low (HL); SELL only at Lower High (LH)
    hi, lo = _swings(m5c, 3)
    if side == "BUY":
        if len(lo) < 2:
            return _wait("Need 2+ swing lows for HL structure", bias)
        if lo[-1] <= lo[-2]:
            return _wait(f"Not a Higher Low ({lo[-1]:.2f} <= {lo[-2]:.2f})", bias)
    else:
        if len(hi) < 2:
            return _wait("Need 2+ swing highs for LH structure", bias)
        if hi[-1] >= hi[-2]:
            return _wait(f"Not a Lower High ({hi[-1]:.2f} >= {hi[-2]:.2f})", bias)

    # ── Horizontal S/R + EQH/EQL levels ──
    levels = _m5_horizontal_levels(m5c, atr_m5)
    if side == "BUY":
        zone = _find_nearest_level(mid, levels["support"], "below")
        if zone is None:
            return _wait("No M5 support/EQL level found", bias)
        if mid < zone - 1.5 * atr_m5:
            return _wait(f"Too far from support zone", bias)
    else:
        zone = _find_nearest_level(mid, levels["resistance"], "above")
        if zone is None:
            return _wait("No M5 resistance/EQH level found", bias)
        if mid > zone + 1.5 * atr_m5:
            return _wait(f"Too far from resistance zone", bias)

    # ── Price action at zone (optional confirmation, does NOT block) ──
    confirmation = "ZONE_BOUNCE"
    if len(m5c) >= 2:
        cur = m5c.iloc[-1]
        prev = m5c.iloc[-2]
        if _is_engulfing(cur, prev, side):
            confirmation = "ENGULFING"
        elif _is_pin_bar(cur, side):
            confirmation = "PIN_BAR"

    # ── Entry ──
    entry = tick["ask"] if side == "BUY" else tick["bid"]

    # ── SL: 1.5 ATR, minimum 50 pips ──
    sl_dist = max(SL_ATR_MULT * atr_m5, MIN_SL_PIPS)
    if side == "BUY":
        sl = entry - sl_dist
        risk = entry - sl
    else:
        sl = entry + sl_dist
        risk = sl - entry
    if risk <= 0:
        return _wait("Invalid risk", bias)

    # ── TP: nearest key zone in trade direction ──
    if side == "BUY":
        tp = _find_nearest_level(entry, levels["resistance"], "above")
        if tp is None:
            tp = entry + 2.0 * atr_m5
    else:
        tp = _find_nearest_level(entry, levels["support"], "below")
        if tp is None:
            tp = entry - 2.0 * atr_m5

    tag = confirmation
    return _confirm(side, symbol, entry, sl, tp, bias, tag, MAX_HOLD_HOURS)


def _confirm(action, symbol, entry, sl, tp, bias, poi, max_hold_hours=24):
    _bot_state[symbol] = "IN_TRADE"
    reason = f"[{bias}] {action} {poi} {entry:.2f} (SL {sl:.2f}, TP {tp:.2f})"
    logger.info(f"{action} CONFIRMED for {symbol}: {reason}")
    sig = TradeSignal(action, symbol, entry, sl_price=sl, tp_price=tp, reason=reason, poi=poi)
    sig.h1_bias = bias
    sig.daily_bias = bias
    sig.max_hold_hours = max_hold_hours
    return sig
